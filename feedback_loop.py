#!/usr/bin/env python3
"""
JRVS Feedback Loop — nightly autonomous training orchestrator.

Reads flagged bad responses → generates better training examples
via teacher model → triggers fine-tuning → deploys updated model.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 RUN MANUALLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  source ~/finetune_env/bin/activate
  python feedback_loop.py            # process feedback + train if ready
  python feedback_loop.py --dry-run  # show what would happen, don't train
  python feedback_loop.py --status   # show feedback queue stats

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SET UP NIGHTLY CRON (runs at 2am every night)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  crontab -e
  # Add this line:
  0 2 * * * cd /path/to/JRVS-main && /path/to/finetune_env/bin/python feedback_loop.py >> logs/feedback_loop.log 2>&1
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

import requests
from search_utils import search as web_search, search_backend
from data_prep.model import DataPrepModel

# Add JRVS root to path so we can import core modules
sys.path.insert(0, str(Path(__file__).parent))
from config import DATABASE_PATH

# ─── Config ───────────────────────────────────────────────────────────────────

OLLAMA_URL       = "http://localhost:11434"
APPROVED_FILE    = Path("./data/distill/approved.jsonl")
LOG_DIR          = Path("./logs")
TRAIN_THRESHOLD  = 30    # min new approved examples before triggering training
SEARCH_RESULTS   = 4

# Log which search backend is active at startup
import sys as _sys
print(f"Search backend: {search_backend()}", file=_sys.stderr)

# Keywords that suggest a question needs a web search
SEARCH_KEYWORDS  = [
    "latest", "current", "recent", "now", "today", "this week", "new",
    "update", "release", "just", "news", "price", "cost", "available",
    "2024", "2025", "2026", "trending", "right now", "happening",
]

# ─── Logging ──────────────────────────────────────────────────────────────────

LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

def log(msg, also_print=True):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    if also_print:
        print(line)
    with open(log_file, "a") as f:
        f.write(line + "\n")

# ─── Database (sync wrapper — avoids importing the full async stack) ──────────

import sqlite3

def get_pending_feedback(db_path, limit=200):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM feedback WHERE processed = 0 ORDER BY created_at ASC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_processed(db_path, feedback_id):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE feedback SET processed = 1 WHERE id = ?", (feedback_id,))
    conn.commit()
    conn.close()

def log_training_run(db_path, examples_used, final_loss, model_path, status):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO training_runs (completed_at, examples_used, final_loss, model_path, status)
        VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?)
    """, (examples_used, final_loss, model_path, status))
    conn.commit()
    conn.close()

def count_approved():
    if not APPROVED_FILE.exists():
        return 0
    with open(APPROVED_FILE) as f:
        return sum(1 for l in f if l.strip())

# ─── Teacher / data-prep model ────────────────────────────────────────────────

def needs_search(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in SEARCH_KEYWORDS)

# web_search is imported from search_utils — uses Brave if BRAVE_API_KEY set, else DDG
# DataPrepModel (imported above) selects jrvs-data-prep (3B) when available,
# falls back to jrvs-teacher (20B) automatically.

_data_prep: "DataPrepModel | None" = None

def _get_data_prep() -> "DataPrepModel":
    global _data_prep
    if _data_prep is None:
        _data_prep = DataPrepModel()
    return _data_prep


def generate_ideal_response(question: str, bad_response: str) -> dict | None:
    use_search = needs_search(question)
    search_results = None

    if use_search:
        log(f"  Searching: {question[:60]}...")
        search_results = web_search(question)

    dp     = _get_data_prep()
    result = dp.generate(question, bad_response, search_results)
    if not result:
        return None

    # Store raw Q&A — training script applies the correct chat template
    # at training time so format is always right regardless of base model
    return {
        "id": f"feedback_{int(time.time())}",
        "category": "feedback_correction",
        "used_search": use_search,
        "question": result["question"],
        "answer":   result["answer"],
        "search_results": search_results,
        "teacher_model": dp.name,
        "generated_at": datetime.now().isoformat(),
        "source": "feedback_loop",
    }

def save_approved(example):
    APPROVED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(APPROVED_FILE, "a") as f:
        f.write(json.dumps(example) + "\n")

# ─── Pattern analysis ─────────────────────────────────────────────────────────

def analyze_failures(feedback_items: list) -> str:
    """Ask data-prep model to identify patterns across all bad responses."""
    if len(feedback_items) < 3:
        return "Not enough feedback to identify patterns yet."

    sample = feedback_items[:10]  # analyze first 10
    summary = "\n\n".join([
        f"Q: {item['question'][:100]}\nBad response: {item['response'][:150]}"
        for item in sample
    ])

    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json={
            "model": _get_data_prep().name,
            "messages": [
                {"role": "system", "content": "You are analyzing AI response failures to improve training. Be concise and specific."},
                {"role": "user",   "content": f"Analyze these bad AI responses and identify the top 2-3 failure patterns:\n\n{summary}\n\nBe brief — one sentence per pattern."},
            ],
            "stream": False,
            "options": {"temperature": 0.4},
        }, timeout=60)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception as e:
        return f"Could not analyze patterns: {e}"

# ─── Training trigger ─────────────────────────────────────────────────────────

def stop_ollama():
    """Stop Ollama — try graceful systemctl first, fall back to pkill."""
    log("Stopping Ollama to free VRAM...")
    # Try systemctl (works if passwordless sudo is configured — see cron setup docs)
    r = subprocess.run(["sudo", "-n", "systemctl", "stop", "ollama"],
                       capture_output=True)
    if r.returncode == 0:
        log("  Ollama stopped via systemctl.")
        time.sleep(3)
        return
    # Fall back: pkill (works if ollama runs as current user)
    subprocess.run(["pkill", "-f", "ollama"], capture_output=True)
    time.sleep(5)
    # Verify VRAM is free enough
    try:
        import torch
        free = (torch.cuda.get_device_properties(0).total_memory
                - torch.cuda.memory_reserved(0)) / 1e9
        log(f"  VRAM free after stopping Ollama: {free:.1f} GB")
        if free < 9.0:
            log("  WARNING: not enough VRAM free. Training may OOM.")
            log("  Configure passwordless sudo for systemctl stop ollama:")
            log("  Run: sudo visudo")
            log("  Add: xavier ALL=(ALL) NOPASSWD: /bin/systemctl stop ollama, /bin/systemctl start ollama")
    except Exception:
        pass

def start_ollama():
    """Start Ollama and wait until it's actually ready."""
    log("Starting Ollama...")
    subprocess.run(["sudo", "-n", "systemctl", "start", "ollama"],
                   capture_output=True)
    # Wait for Ollama API to be responsive (up to 30s)
    for i in range(30):
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
            if r.status_code == 200:
                log(f"  Ollama ready after {i+1}s.")
                return
        except Exception:
            pass
        time.sleep(1)
    log("  WARNING: Ollama may not have started correctly.")

def trigger_training():
    log("\nTriggering fine-tuning run...")
    approved = count_approved()
    log(f"Approved examples: {approved}")

    stop_ollama()

    # Pass the approved data so training actually uses it
    cmd = [sys.executable, "finetune_capybara.py",
           "--extra-data", str(APPROVED_FILE)]
    log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    start_ollama()

    if result.returncode == 0:
        log("Training completed successfully.")
        final_loss = None
        for line in result.stdout.splitlines():
            if "Final loss" in line:
                try:
                    final_loss = float(line.split(":")[-1].strip())
                except Exception:
                    pass
        log_training_run(
            str(DATABASE_PATH),
            approved,
            final_loss or 0.0,
            "./output/gemma-capybara-lora/final",
            "completed"
        )
        deploy_model()
    else:
        log("Training FAILED. Last 50 lines of output:")
        for line in result.stdout.splitlines()[-50:]:
            log(f"  {line}")
        log(f"Stderr:\n{result.stderr[-500:]}")
        log_training_run(str(DATABASE_PATH), 0, 0.0, "", "failed")

def deploy_model():
    """Create/update the ollama model from the new GGUF."""
    gguf_dir = Path("./output/gemma-capybara-gguf")
    gguf_files = list(gguf_dir.glob("*.gguf")) if gguf_dir.exists() else []
    if not gguf_files:
        log("No GGUF found to deploy — EXPORT_GGUF may be False or export failed.")
        log("LoRA adapter still saved at ./output/gemma-capybara-lora/final/")
        return

    gguf_path = gguf_files[0]
    modelfile = f"""FROM {gguf_path.absolute()}
SYSTEM "You are JRVS, an intelligent personal assistant. You research thoroughly, cite your sources, and are direct and concise."
"""
    modelfile_path = Path("/tmp/jrvs_modelfile")
    modelfile_path.write_text(modelfile)

    log(f"Deploying {gguf_path.name} to Ollama as 'jrvs-personal'...")
    result = subprocess.run(
        ["ollama", "create", "jrvs-personal", "-f", str(modelfile_path)],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        log("Deployed successfully.")
        log("Test it: ollama run jrvs-personal")
    else:
        log(f"Deploy failed: {result.stderr}")
        log(f"Manual deploy:\n  ollama create jrvs-personal -f {modelfile_path}")

# ─── Status ───────────────────────────────────────────────────────────────────

def show_status():
    pending = get_pending_feedback(str(DATABASE_PATH))
    approved = count_approved()
    print(f"\n{'='*50}")
    print("  FEEDBACK LOOP STATUS")
    print(f"{'='*50}")
    print(f"  Pending feedback    : {len(pending)}")
    print(f"  Approved examples   : {approved}")
    print(f"  Training threshold  : {TRAIN_THRESHOLD}")
    print(f"  Ready to train      : {'YES' if approved >= TRAIN_THRESHOLD else f'NO — need {TRAIN_THRESHOLD - approved} more'}")
    if pending:
        print("\n  Recent feedback:")
        for item in pending[-3:]:
            print(f"    - {item['question'][:70]}")
    print(f"{'='*50}\n")

# ─── Main ─────────────────────────────────────────────────────────────────────

_SENTINEL_FILE = Path("./data/retrain_queued")


def _consume_sentinel() -> bool:
    """Return True and delete the sentinel if it exists (auto-queue triggered)."""
    if _SENTINEL_FILE.exists():
        try:
            content = _SENTINEL_FILE.read_text().strip()
            log(f"Sentinel found: {content}")
            _SENTINEL_FILE.unlink()
            return True
        except Exception as exc:
            log(f"Could not read/delete sentinel: {exc}")
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without training")
    parser.add_argument("--status",  action="store_true", help="Show queue stats and exit")
    parser.add_argument("--force-train", action="store_true", help="Train even if below threshold")
    args = parser.parse_args()

    # Auto-trigger: if a sentinel was written by the self-improvement check, treat as --force-train
    if not args.force_train and _consume_sentinel():
        log("Auto-trigger: sentinel found — forcing training run")
        args.force_train = True

    if args.status:
        show_status()
        return

    log("=" * 50)
    log("  JRVS FEEDBACK LOOP")
    log(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 50)

    # Load pending feedback
    feedback = get_pending_feedback(str(DATABASE_PATH))
    log(f"\nPending feedback items: {len(feedback)}")

    if not feedback:
        log("Nothing to process.")
        if args.force_train or count_approved() >= TRAIN_THRESHOLD:
            if not args.dry_run:
                trigger_training()
        return

    # Analyze failure patterns
    log("\nAnalyzing failure patterns...")
    patterns = analyze_failures(feedback)
    log(f"Patterns:\n  {patterns}")

    # Check Ollama is available for teacher
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    except Exception:
        log("Ollama not running — cannot use teacher model. Start it and retry.")
        sys.exit(1)

    # Process each feedback item
    log(f"\nGenerating ideal responses for {len(feedback)} items...")
    generated = 0
    failed = 0

    for i, item in enumerate(feedback, 1):
        log(f"\n[{i}/{len(feedback)}] {item['question'][:70]}")

        example = generate_ideal_response(item["question"], item["response"])
        if example:
            if not args.dry_run:
                save_approved(example)
                mark_processed(str(DATABASE_PATH), item["id"])
            log(f"  Generated. Preview: {example['answer'][-200:].strip()[:120]}")
            generated += 1
        else:
            log("  Failed to generate.")
            failed += 1

    log(f"\nProcessed: {generated} generated, {failed} failed")
    log(f"Total approved examples: {count_approved()}")

    # Trigger training if threshold met
    should_train = (count_approved() >= TRAIN_THRESHOLD) or args.force_train
    if should_train:
        if args.dry_run:
            log(f"\n[DRY RUN] Would trigger training now ({count_approved()} examples)")
        else:
            trigger_training()
    else:
        remaining = TRAIN_THRESHOLD - count_approved()
        log(f"\nNot training yet — need {remaining} more approved examples.")
        log("Keep using JRVS and flagging bad responses with 'that was wrong'.")

    log(f"\nDone. Log saved to {log_file}")


if __name__ == "__main__":
    main()
