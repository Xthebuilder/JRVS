#!/usr/bin/env python3
"""
Fine-tune Qwen2.5-3B-Instruct on the bootstrap data to create a local
data-prep model that can replace jrvs-teacher (20B) for generating training examples.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SETUP (use the existing finetune_env)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  source ~/finetune_env/bin/activate
  # Qwen2.5-3B doesn't need HF login — it's not gated

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 RUN (after bootstrap.py has generated data)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  # Make sure Ollama is stopped first (free VRAM)
  sudo systemctl stop ollama

  source ~/finetune_env/bin/activate
  python data_prep/train.py

 Output:
  ./output/data-prep-lora/    — LoRA adapter
  ./output/data-prep-gguf/    — GGUF for Ollama (if EXPORT_GGUF=True)

 Deploy to Ollama:
  ollama create jrvs-data-prep -f data_prep/data_prep.Modelfile

 Expected runtime on RTX 3060 12GB:
  ~300 examples × 2 epochs ≈ 25-35 minutes
"""

import os
import sys
import json
import time
from pathlib import Path

print("=" * 60)
print("  DATA-PREP MODEL — QLoRA Fine-Tune")
print("  Qwen2.5-3B-Instruct on bootstrap data")
print("=" * 60)
print()

# ─── Config ──────────────────────────────────────────────────────────────────

HF_MODEL_ID    = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit"
LORA_RANK      = 16
LORA_ALPHA     = 32
LORA_DROPOUT   = 0.05
MAX_SEQ_LEN    = 2048
BATCH_SIZE     = 2
GRAD_ACCUM     = 4        # effective batch = 8
EPOCHS         = 3        # small dataset benefits from more epochs
WARMUP_RATIO   = 0.1
LEARNING_RATE  = 2e-4
EXPORT_GGUF    = True

BOOTSTRAP_FILE = Path("./data/data_prep/bootstrap.jsonl")
OUTPUT_DIR     = Path("./output/data-prep-lora")
GGUF_DIR       = Path("./output/data-prep-gguf")

# ─── Pre-flight ───────────────────────────────────────────────────────────────

errors = []

try:
    import torch
    if not torch.cuda.is_available():
        errors.append("CUDA not available.")
    else:
        gpu       = torch.cuda.get_device_properties(0)
        vram_gb   = gpu.total_memory / 1e9
        vram_free = (gpu.total_memory - torch.cuda.memory_reserved(0)) / 1e9
        print(f"GPU: {gpu.name} — {vram_free:.1f} GB free / {vram_gb:.1f} GB total")
        if vram_free < 7.0:
            errors.append(
                f"Only {vram_free:.1f} GB VRAM free. Stop Ollama first: "
                "sudo systemctl stop ollama"
            )
except ImportError:
    errors.append("PyTorch not installed.")

if not BOOTSTRAP_FILE.exists():
    errors.append(
        f"Bootstrap data not found: {BOOTSTRAP_FILE}\n"
        "  Run: python data_prep/bootstrap.py"
    )
else:
    count = sum(1 for _ in open(BOOTSTRAP_FILE))
    print(f"Bootstrap examples: {count}")
    if count < 50:
        errors.append(f"Only {count} examples — run bootstrap.py first (need ≥50).")

for pkg in ["unsloth", "trl", "peft", "bitsandbytes", "datasets"]:
    try:
        __import__(pkg)
    except ImportError:
        errors.append(f"Missing package: {pkg}  (pip install {pkg})")

if errors:
    print("\nPre-flight FAILED:")
    for e in errors:
        print(f"  ✗ {e}")
    sys.exit(1)

print("Pre-flight passed.\n")

# ─── Load data ────────────────────────────────────────────────────────────────

print("[1/5] Loading bootstrap data...")

raw_examples = []
with open(BOOTSTRAP_FILE) as f:
    for line in f:
        try:
            raw_examples.append(json.loads(line.strip()))
        except Exception:
            pass

print(f"  Loaded {len(raw_examples)} examples")

# ─── Model + tokenizer ────────────────────────────────────────────────────────

print(f"\n[2/5] Loading model: {HF_MODEL_ID}")

from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name    = HF_MODEL_ID,
    max_seq_length= MAX_SEQ_LEN,
    dtype         = None,        # auto (bfloat16 on Ampere+)
    load_in_4bit  = True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r              = LORA_RANK,
    lora_alpha     = LORA_ALPHA,
    lora_dropout   = LORA_DROPOUT,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    bias           = "none",
    use_gradient_checkpointing = "unsloth",
    random_state   = 42,
)

print(f"  LoRA rank={LORA_RANK}, alpha={LORA_ALPHA}")

# ─── Format examples ──────────────────────────────────────────────────────────

print("\n[3/5] Formatting examples...")

TASK_SYSTEM = """You are a training data generator. Given a question and a bad AI response, output a JSON object with the ideal response.

Output format — exactly this JSON, nothing else:
{"question": "<original question>", "answer": "<ideal response>"}

Ideal answer rules:
- Lead with the direct answer
- Cite factual claims inline: (Source: Publication Name)
- End with: "Confidence: [high/moderate/low] — [brief reason]"
- No markdown, no bullets — plain prose only
- Concise: answer completely then stop"""


def format_example(ex: dict) -> str:
    inp    = ex["input"]
    out    = ex["output"]
    q      = inp["question"]
    bad    = inp["bad_response"]
    ideal  = json.dumps({"question": out["question"], "answer": out["answer"]},
                         ensure_ascii=False)

    messages = [
        {"role": "system",    "content": TASK_SYSTEM},
        {"role": "user",      "content": f'Question: "{q}"\n\nBad response: "{bad}"\n\nWrite the ideal response as JSON.'},
        {"role": "assistant", "content": ideal},
    ]
    return tokenizer.apply_chat_template(
        messages,
        tokenize        = False,
        add_generation_prompt = False,
    )


texts = [format_example(ex) for ex in raw_examples]

from datasets import Dataset
dataset = Dataset.from_dict({"text": texts})
print(f"  {len(dataset)} training examples formatted")

# ─── Training ─────────────────────────────────────────────────────────────────

print("\n[4/5] Starting training...")
print(f"  Epochs: {EPOCHS}  |  Batch: {BATCH_SIZE}  |  Grad accum: {GRAD_ACCUM}")
print(f"  Effective batch size: {BATCH_SIZE * GRAD_ACCUM}")
print(f"  Learning rate: {LEARNING_RATE}")
print()

from trl import SFTTrainer
from transformers import TrainingArguments, DataCollatorForSeq2Seq

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

trainer = SFTTrainer(
    model           = model,
    tokenizer       = tokenizer,
    train_dataset   = dataset,
    dataset_text_field = "text",
    max_seq_length  = MAX_SEQ_LEN,
    data_collator   = DataCollatorForSeq2Seq(tokenizer=tokenizer, padding=True),
    args            = TrainingArguments(
        per_device_train_batch_size  = BATCH_SIZE,
        gradient_accumulation_steps  = GRAD_ACCUM,
        num_train_epochs             = EPOCHS,
        warmup_ratio                 = WARMUP_RATIO,
        learning_rate                = LEARNING_RATE,
        fp16                         = not torch.cuda.is_bf16_supported(),
        bf16                         = torch.cuda.is_bf16_supported(),
        logging_steps                = 10,
        save_strategy                = "epoch",
        output_dir                   = str(OUTPUT_DIR),
        dataloader_num_workers       = 0,
        report_to                    = "none",
        seed                         = 42,
    ),
    dataset_num_proc = 1,
)

t0     = time.time()
result = trainer.train()
elapsed = time.time() - t0

print(f"\nTraining complete in {elapsed/60:.1f} minutes")
if hasattr(result, "training_loss"):
    print(f"Final loss: {result.training_loss:.4f}")

model.save_pretrained(str(OUTPUT_DIR / "final"))
tokenizer.save_pretrained(str(OUTPUT_DIR / "final"))
print(f"LoRA adapter saved: {OUTPUT_DIR / 'final'}")

# ─── GGUF export ──────────────────────────────────────────────────────────────

if EXPORT_GGUF:
    print("\n[5/5] Exporting to GGUF (Q4_K_M)...")
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained_gguf(
        str(GGUF_DIR),
        tokenizer,
        quantization_method = "q4_k_m",
    )
    gguf_files = list(GGUF_DIR.glob("*.gguf"))
    if gguf_files:
        print(f"  GGUF saved: {gguf_files[0]}")
        print(f"\nDeploy to Ollama:")
        print(f"  ollama create jrvs-data-prep -f data_prep/data_prep.Modelfile")
    else:
        print("  GGUF export may have failed — check output directory.")
else:
    print("\n[5/5] Skipping GGUF export (EXPORT_GGUF=False)")

print("\n" + "=" * 60)
print("  DONE")
print("=" * 60)
print(f"\nLoRA:  {OUTPUT_DIR / 'final'}")
if EXPORT_GGUF:
    print(f"GGUF:  {GGUF_DIR}")
    print(f"\nNext: ollama create jrvs-data-prep -f data_prep/data_prep.Modelfile")
