#!/usr/bin/env python3
"""
Distillation Agent — transfer gpt-oss:20b's research/tool-use skill to qwen2.5-7b.

Generates training data where the model learns:
  1. WHEN to search vs answer from memory
  2. HOW to formulate good search queries
  3. HOW to synthesize search results into clean spoken answers

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SETUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  source ~/finetune_env/bin/activate
  pip install duckduckgo-search   # (already installed)

 Make sure Ollama is running with gpt-oss:20b available:
  sudo systemctl start ollama

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 RUN MODES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python distill_agent.py               # generate + interactive review
  python distill_agent.py --auto        # generate + auto-approve (overnight run)
  python distill_agent.py --review      # review pending examples only, no generation
  python distill_agent.py --stats       # show dataset stats
  python distill_agent.py --train       # kick off fine-tuning on approved data

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ITERATIVE LOOP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Run agent → review examples → train → test model → add bad cases as new seeds → repeat
"""

import os
import sys
import json
import time
import random
import argparse
import textwrap
import subprocess
from datetime import datetime
from pathlib import Path

import requests
from search_utils import search as _web_search, search_backend

# ─── Config ───────────────────────────────────────────────────────────────────

OLLAMA_URL      = "http://localhost:11434"
TEACHER_MODEL   = "jrvs-teacher"       # gpt-oss:20b with teacher system prompt baked in
STUDENT_MODEL   = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"  # what we're training

DATA_DIR        = Path("./data/distill")
PENDING_FILE    = DATA_DIR / "pending.jsonl"    # generated, not yet reviewed
APPROVED_FILE   = DATA_DIR / "approved.jsonl"   # reviewed + approved training data
REJECTED_FILE   = DATA_DIR / "rejected.jsonl"   # rejected (useful to track patterns)

SEARCH_RESULTS  = 4      # how many DDG results to fetch per query
TEACHER_TEMP    = 0.7    # temperature for teacher generation
BATCH_SIZE      = 10     # examples to generate per run before pausing to review

# ─── Seed prompts ─────────────────────────────────────────────────────────────
# These are the kinds of things you'd actually ask JRVS.
# Add your own as you iterate — the more specific to your life, the better.

# ── Technical / AI research (current, needs search) ──────────────────────────
SEARCH_SEEDS_TECH = [
    "latest updates to Ollama",
    "what dropped on huggingface this week",
    "any new local LLM models released recently",
    "what's the current state of open source AI vs closed source",
    "what are people saying about fine-tuning small models lately",
    "any breakthroughs in TTS or voice AI recently",
    "whats the best open source embedding model right now",
    "latest on multimodal local models",
    "whats new with mistral ai",
    "any updates to the unsloth library",
    "current best practices for LoRA fine tuning",
    "what are devs saying about python 3.14 compatibility issues",
    "latest open webui features",
    "any new RAG techniques people are using",
    "whats happening with the llama model family",
    "recent papers on knowledge distillation for LLMs",
    "best consumer GPUs for local AI right now",
    "latest benchmarks for 7b models",
    "whats the current best quantization method for local inference",
    "any new voice assistant frameworks released recently",
]

# ── Market / business research (current, needs search) ───────────────────────
SEARCH_SEEDS_MARKET = [
    "what are businesses actually using AI for right now",
    "latest trends in AI automation for small business",
    "whats the going rate for AI consulting in 2025",
    "how are companies implementing local AI vs cloud AI",
    "latest on AI regulation and what it means for small businesses",
    "what industries are adopting AI fastest right now",
    "latest on no-code AI tools for businesses",
    "whats the current state of the AI agent market",
    "how much are companies spending on AI tools per employee",
    "latest on AI replacing vs augmenting workers",
    "what are the most in demand AI skills right now",
    "whats happening with AI startups and funding lately",
    "latest on open source vs proprietary AI for enterprise",
    "current pricing models for AI API services",
    "whats the ROI businesses are seeing from AI automation",
]

# ── Content / general research (current, needs search) ───────────────────────
SEARCH_SEEDS_CONTENT = [
    "whats trending in the AI creator space right now",
    "latest on AI generated content and copyright",
    "what are people building with local AI this week",
    "any interesting AI use cases people are sharing lately",
    "whats the current discourse around AI ethics",
    "latest on deepfakes and synthetic media",
    "whats happening with AI art tools recently",
    "any new ways people are using AI for productivity",
    "latest on AI in education",
    "whats the current sentiment around AI replacing jobs",
    "any new research on AI and mental health",
    "latest on AI assistants and privacy",
    "whats new in the AI hardware space",
    "recent stories about AI getting things wrong publicly",
    "latest on AI and search engines",
]

# Combine all search seeds
SEARCH_SEEDS = SEARCH_SEEDS_TECH + SEARCH_SEEDS_MARKET + SEARCH_SEEDS_CONTENT

NO_SEARCH_SEEDS = [
    # Stable knowledge — model answers from memory, no search needed
    "what is LoRA and how does it work",
    "explain the difference between RAG and fine tuning",
    "how does quantization affect model quality",
    "what is the transformer architecture",
    "explain RLHF in simple terms",
    "what does VRAM actually store during inference",
    "whats the difference between a base model and an instruct model",
    "how does vector similarity search work",
    "explain gradient descent like im not a machine learning researcher",
    "what makes a good fine tuning dataset",
    "explain context window limitations",
    "what is knowledge distillation",
    "explain the attention mechanism simply",
    "what makes Qwen2.5 different from Llama",
    "what is the difference between TTS and STT",
    "explain what an AI agent actually is",
    "what is the difference between inference and training",
    "how does temperature affect model output",
    "what makes a dataset high quality for fine tuning",
    "explain embeddings in plain terms",
]

JRVS_SEEDS = [
    # JRVS-specific interactions — short, voice-optimized responses
    "jarvis what time is it",
    "add a reminder to check the training run at 8am",
    "whats on my schedule today",
    "search my notes for anything about fine tuning",
    "give me a quick summary of what we worked on recently",
    "how much VRAM does a 7b model use",
    "jarvis remind me to review the distilled dataset tomorrow morning",
    "whats the best model i have locally right now for coding",
    "how long would it take to fine tune on 500 examples",
    "jarvis look up the latest on open source AI and give me a quick brief",
]

# ─── Prompts sent to the teacher model ────────────────────────────────────────

TEACHER_SYSTEM = ""  # baked into jrvs-teacher Modelfile — no need to repeat it here

TEACHER_SEARCH_PROMPT = """The user asked: "{question}"

Web search results:
{search_results}

Write a direct, cited response. Lead with the answer. Weave citations in naturally
as (Source: name). No markdown. Conversational tone. If results are thin or outdated,
say so rather than padding the answer."""

TEACHER_NO_SEARCH_PROMPT = """The user asked: "{question}"

This is stable knowledge — answer from memory without searching.
Be direct and confident. No markdown, no bullet points.
If something in your knowledge might be outdated, flag it briefly."""

TEACHER_JRVS_PROMPT = """The user is talking to JRVS, their personal AI assistant.
They said: "{question}"

Reply as JRVS — short, direct, one to three sentences max.
If it needs a search, say you'll look it up. If you know it, just answer."""

# ─── Helpers ──────────────────────────────────────────────────────────────────

def log(msg, color=None):
    codes = {"green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m",
             "cyan": "\033[96m", "bold": "\033[1m", "dim": "\033[2m"}
    reset = "\033[0m"
    prefix = codes.get(color, "")
    print(f"{prefix}{msg}{reset}")


def check_ollama():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        available = [m for m in models if TEACHER_MODEL.split(":")[0] in m]
        if not available:
            log(f"Teacher model '{TEACHER_MODEL}' not found in Ollama.", "red")
            log(f"Available: {models}", "dim")
            sys.exit(1)
        log(f"Teacher: {TEACHER_MODEL} — ready", "green")
        return True
    except Exception as e:
        log(f"Ollama not reachable at {OLLAMA_URL}: {e}", "red")
        log("Start it with:  sudo systemctl start ollama", "yellow")
        sys.exit(1)


def search(query, max_results=SEARCH_RESULTS):
    return _web_search(query, max_results=max_results)


def ask_teacher(prompt, system=TEACHER_SYSTEM):
    payload = {
        "model": TEACHER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": TEACHER_TEMP},
    }
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception as e:
        return None


def format_for_training(question, answer, category, used_search=False,
                        search_query=None, search_results=None):
    """Format a Q+A pair into Qwen2.5 tool-call chat format."""

    messages = []

    if used_search:
        # Training example: model decides to search, gets results, synthesizes
        messages = [
            {"role": "user", "content": question},
            {"role": "assistant", "content": None,
             "tool_calls": [{"type": "function", "function": {
                 "name": "web_search",
                 "arguments": json.dumps({"query": search_query or question})
             }}]},
            {"role": "tool", "content": json.dumps({
                "results": search_results or []
            })},
            {"role": "assistant", "content": answer},
        ]
    else:
        messages = [
            {"role": "user",      "content": question},
            {"role": "assistant", "content": answer},
        ]

    return {
        "id": f"{category}_{int(time.time())}_{random.randint(1000,9999)}",
        "category": category,
        "used_search": used_search,
        "question": question,
        "search_query": search_query,
        "teacher_model": TEACHER_MODEL,
        "generated_at": datetime.now().isoformat(),
        "messages": messages,
        # flat text format for SFTTrainer
        "text": build_chat_text(messages),
    }


def build_chat_text(messages):
    """Build Qwen2.5 chat template string from messages."""
    parts = []
    for m in messages:
        role = m["role"]
        if role == "tool":
            parts.append(f"<|im_start|>tool\n{m['content']}<|im_end|>")
        elif role == "assistant" and m.get("tool_calls"):
            tc = m["tool_calls"][0]["function"]
            call_str = json.dumps({"name": tc["name"],
                                   "arguments": json.loads(tc["arguments"])},
                                  indent=2)
            parts.append(f"<|im_start|>assistant\n<tool_call>\n{call_str}\n</tool_call><|im_end|>")
        elif m.get("content"):
            parts.append(f"<|im_start|>{role}\n{m['content']}<|im_end|>")
    return "\n".join(parts)


def save_example(example, filepath):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "a") as f:
        f.write(json.dumps(example) + "\n")


def load_jsonl(filepath):
    if not filepath.exists():
        return []
    with open(filepath) as f:
        return [json.loads(l) for l in f if l.strip()]


def count_examples():
    pending  = len(load_jsonl(PENDING_FILE))
    approved = len(load_jsonl(APPROVED_FILE))
    rejected = len(load_jsonl(REJECTED_FILE))
    return pending, approved, rejected

# ─── Generation ───────────────────────────────────────────────────────────────

def generate_search_example(question):
    log(f"\n  Searching: {question}", "dim")
    results = search(question)
    prompt  = TEACHER_SEARCH_PROMPT.format(
        question=question, search_results=results)
    answer  = ask_teacher(prompt)
    if not answer:
        return None
    # Extract a clean query from the question
    search_query = question.rstrip("?").strip()
    return format_for_training(
        question, answer,
        category="research",
        used_search=True,
        search_query=search_query,
        search_results=results,
    )


def generate_no_search_example(question):
    prompt = TEACHER_NO_SEARCH_PROMPT.format(question=question)
    answer = ask_teacher(prompt)
    if not answer:
        return None
    return format_for_training(
        question, answer,
        category="knowledge",
        used_search=False,
    )


def generate_jrvs_example(question):
    prompt = TEACHER_JRVS_PROMPT.format(question=question)
    answer = ask_teacher(prompt)
    if not answer:
        return None
    return format_for_training(
        question, answer,
        category="jrvs",
        used_search=False,
    )


def generate_batch(n=BATCH_SIZE):
    generated = []
    # Mix of all three types
    pool = (
        [("search",    q) for q in random.sample(SEARCH_SEEDS,    min(n//3+1, len(SEARCH_SEEDS)))] +
        [("knowledge", q) for q in random.sample(NO_SEARCH_SEEDS, min(n//3+1, len(NO_SEARCH_SEEDS)))] +
        [("jrvs",      q) for q in random.sample(JRVS_SEEDS,      min(n//3+1, len(JRVS_SEEDS)))]
    )
    random.shuffle(pool)
    pool = pool[:n]

    for i, (kind, question) in enumerate(pool, 1):
        log(f"\n[{i}/{len(pool)}] {kind.upper()}: {question}", "cyan")
        if kind == "search":
            ex = generate_search_example(question)
        elif kind == "knowledge":
            ex = generate_no_search_example(question)
        else:
            ex = generate_jrvs_example(question)

        if ex:
            save_example(ex, PENDING_FILE)
            log(f"  → Generated. Teacher answer preview:", "dim")
            answer_preview = (ex["messages"][-1].get("content") or "")[:200]
            for line in textwrap.wrap(answer_preview, 70):
                log(f"    {line}", "dim")
            generated.append(ex)
        else:
            log("  → Teacher returned nothing, skipping.", "yellow")

    return generated

# ─── Review ───────────────────────────────────────────────────────────────────

def review_pending():
    pending = load_jsonl(PENDING_FILE)
    if not pending:
        log("\nNo pending examples to review.", "yellow")
        return

    log(f"\n{'='*60}", "bold")
    log(f"  REVIEW MODE — {len(pending)} pending examples", "bold")
    log(f"  a=approve  r=reject  e=edit answer  s=skip  q=quit", "bold")
    log(f"{'='*60}", "bold")

    approved_in_session = 0
    remaining = []

    for i, ex in enumerate(pending, 1):
        log(f"\n[{i}/{len(pending)}] Category: {ex['category'].upper()}", "cyan")
        log(f"Question: {ex['question']}", "bold")
        if ex.get("used_search"):
            log(f"Used search: YES (query: {ex.get('search_query', '')})", "yellow")
        answer = ex["messages"][-1].get("content", "")
        log(f"\nTeacher answer:")
        for line in textwrap.wrap(answer, 72):
            log(f"  {line}")

        while True:
            choice = input("\n> ").strip().lower()
            if choice == "a":
                save_example(ex, APPROVED_FILE)
                approved_in_session += 1
                log("  Approved.", "green")
                break
            elif choice == "r":
                save_example(ex, REJECTED_FILE)
                log("  Rejected.", "red")
                break
            elif choice == "e":
                print("Enter new answer (blank line to finish):")
                lines = []
                while True:
                    line = input()
                    if line == "":
                        break
                    lines.append(line)
                ex["messages"][-1]["content"] = "\n".join(lines)
                ex["text"] = build_chat_text(ex["messages"])
                save_example(ex, APPROVED_FILE)
                approved_in_session += 1
                log("  Edited + approved.", "green")
                break
            elif choice == "s":
                remaining.append(ex)
                log("  Skipped.", "dim")
                break
            elif choice == "q":
                remaining.extend(pending[i:])
                break
            else:
                log("  a/r/e/s/q", "dim")

        if choice == "q":
            break

    # Rewrite pending with only skipped examples
    with open(PENDING_FILE, "w") as f:
        for ex in remaining:
            f.write(json.dumps(ex) + "\n")

    log(f"\nSession: approved {approved_in_session} examples.", "green")
    _, total_approved, _ = count_examples()
    log(f"Total approved dataset: {total_approved} examples.", "green")

# ─── Export for fine-tuning ───────────────────────────────────────────────────

def export_training_data():
    """Export approved data as raw Q&A for finetune_capybara.py --extra-data."""
    approved = load_jsonl(APPROVED_FILE)
    if not approved:
        log("No approved examples yet.", "yellow")
        return None

    export_path = DATA_DIR / "training_export.jsonl"
    with open(export_path, "w") as f:
        for ex in approved:
            # Store raw Q&A — training script applies correct chat template
            # for whatever base model is being trained
            entry = {
                "question": ex.get("question", ""),
                "answer": (ex["messages"][-1].get("content", "")
                           if ex.get("messages") else ex.get("answer", "")),
            }
            if entry["question"] and entry["answer"]:
                f.write(json.dumps(entry) + "\n")

    count = sum(1 for _ in open(export_path))
    log(f"Exported {count} examples to {export_path}", "green")
    return export_path


def run_training(export_path):
    """Kick off fine-tuning on the distilled dataset."""
    log("\nLaunching fine-tuning on distilled data...", "cyan")
    log(f"Extra data: {export_path}", "dim")
    subprocess.run(
        [sys.executable, "finetune_capybara.py", "--extra-data", str(export_path)]
    )

# ─── Stats ────────────────────────────────────────────────────────────────────

def show_stats():
    pending, approved, rejected = count_examples()
    approved_data = load_jsonl(APPROVED_FILE)

    log(f"\n{'='*50}", "bold")
    log(f"  DATASET STATS", "bold")
    log(f"{'='*50}", "bold")
    log(f"  Pending review : {pending}")
    log(f"  Approved       : {approved}", "green")
    log(f"  Rejected       : {rejected}", "red")

    if approved_data:
        cats = {}
        search_count = 0
        for ex in approved_data:
            c = ex.get("category", "unknown")
            cats[c] = cats.get(c, 0) + 1
            if ex.get("used_search"):
                search_count += 1
        log(f"\n  By category:")
        for cat, count in sorted(cats.items()):
            log(f"    {cat:<15} {count}")
        log(f"\n  With search    : {search_count}")
        log(f"  Without search : {approved - search_count}")
        log(f"\n  Ready to train : {'YES' if approved >= 50 else f'NO (need {50-approved} more)'}")

    log(f"{'='*50}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="JRVS Distillation Agent")
    parser.add_argument("--auto",   action="store_true", help="Auto-approve all generated examples")
    parser.add_argument("--review", action="store_true", help="Review pending only, no generation")
    parser.add_argument("--stats",  action="store_true", help="Show dataset stats")
    parser.add_argument("--train",  action="store_true", help="Export + kick off fine-tuning")
    parser.add_argument("--n",      type=int, default=BATCH_SIZE, help="Examples to generate")
    args = parser.parse_args()

    log(f"\n{'='*60}", "bold")
    log(f"  JRVS DISTILLATION AGENT", "bold")
    log(f"  Teacher: {TEACHER_MODEL}", "dim")
    log(f"{'='*60}", "bold")

    if args.stats:
        show_stats()
        return

    if args.train:
        path = export_training_data()
        if path:
            run_training(path)
        return

    if args.review:
        review_pending()
        return

    # Default: generate + review
    check_ollama()
    show_stats()

    log(f"\nGenerating {args.n} examples from teacher model...", "cyan")
    log(f"Search backend : {search_backend()}", "dim")
    log("(Ollama needs to be running — the training run should be paused or on a different GPU slot)", "yellow")

    generated = generate_batch(args.n)
    log(f"\nGenerated {len(generated)} examples.", "green")

    if args.auto:
        log("Auto-approve mode — saving all to approved dataset.", "yellow")
        for ex in generated:
            save_example(ex, APPROVED_FILE)
        # Clear pending
        open(PENDING_FILE, "w").close()
        show_stats()
    else:
        log("\nReady to review. Starting review session...", "cyan")
        review_pending()
        show_stats()

    pending, approved, _ = count_examples()
    if approved >= 50:
        log(f"\nYou have {approved} approved examples — enough to run a fine-tune.", "green")
        log("Run:  python distill_agent.py --train", "cyan")
    else:
        log(f"\n{50 - approved} more approved examples before first training run.", "dim")
        log("Add more seeds to SEARCH_SEEDS/NO_SEARCH_SEEDS/JRVS_SEEDS above,", "dim")
        log("then run again:  python distill_agent.py", "dim")


if __name__ == "__main__":
    main()
