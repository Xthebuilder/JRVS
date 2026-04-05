#!/usr/bin/env python3
"""
Fine-tune Gemma-3-4B-IT on LDJnr/Capybara using QLoRA.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SETUP (do this once, ideally in a venv)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python3 -m venv ~/finetune_env
  source ~/finetune_env/bin/activate

  # PyTorch with CUDA 12.4 (matches your driver)
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

  # Unsloth (memory-efficient QLoRA engine)
  pip install "unsloth[cu124-torch260] @ git+https://github.com/unslothai/unsloth.git"
  pip install --no-deps trl peft accelerate
  pip install bitsandbytes datasets huggingface_hub

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 FREE VRAM — stop Ollama before training
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  sudo systemctl stop ollama
  # or:  pkill ollama

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  source ~/finetune_env/bin/activate
  python finetune_capybara.py

 Outputs:
  ./output/gemma-capybara-lora/   — LoRA adapter (~100-200 MB)
  ./output/gemma-capybara-gguf/   — GGUF ready for Ollama (optional, slow)
"""

import os
import sys
import time
import json

# ─── Pre-flight checks (run before heavy imports) ─────────────────────────────

print("=" * 60)
print("  GEMMA-3-4B x CAPYBARA — QLoRA Fine-Tune")
print("=" * 60)
print()
print("[1/6] Running pre-flight checks...")

errors   = []
warnings = []

# Check CUDA
try:
    import torch
    if not torch.cuda.is_available():
        errors.append("CUDA not available — PyTorch can't see your GPU.")
    else:
        gpu        = torch.cuda.get_device_properties(0)
        vram_gb    = gpu.total_memory / 1e9
        vram_free  = (gpu.total_memory - torch.cuda.memory_reserved(0)) / 1e9
        print(f"    GPU   : {gpu.name}")
        print(f"    VRAM  : {vram_gb:.1f} GB total | {vram_free:.1f} GB free")
        if vram_free < 5.0:
            errors.append(
                f"Only {vram_free:.1f} GB VRAM free — need ~5 GB for 4B model. "
                "Stop Ollama first:  sudo systemctl stop ollama"
            )
except ImportError:
    errors.append("PyTorch not installed. Run the pip install commands in the docstring.")

# Check required packages
required = {
    "unsloth":   "unsloth",
    "peft":      "peft",
    "trl":       "trl",
    "datasets":  "datasets",
    "bitsandbytes": "bitsandbytes",
    "huggingface_hub": "huggingface_hub",
}
missing = []
for pkg, import_name in required.items():
    try:
        __import__(import_name)
    except ImportError:
        missing.append(pkg)
if missing:
    errors.append(f"Missing packages: {', '.join(missing)}. See setup instructions above.")

# No HuggingFace login needed — google/gemma-3-12b-it is public
print("    HF    : no login required (public model)")

# Report
print()
if errors:
    print("PROBLEMS FOUND — fix these before training:\n")
    for i, e in enumerate(errors, 1):
        print(f"  [{i}] {e}")
    print()
    sys.exit(1)

print("    All checks passed. Starting in 3 seconds...")
print("    (Ctrl+C now if you need to fix something)")
time.sleep(3)

# ─── Parse arguments (extra training data from feedback loop / distill agent) ─

import argparse
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--extra-data", default=None,
                     help="Path to extra JSONL training data to merge with Capybara")
_args, _ = _parser.parse_known_args()
EXTRA_DATA_PATH = _args.extra_data

# ─── Now do the heavy imports ─────────────────────────────────────────────────

from datasets import load_dataset, concatenate_datasets, Dataset
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import DataCollatorForSeq2Seq
from transformers import TrainingArguments

# ─── Config ───────────────────────────────────────────────────────────────────

HF_MODEL_ID = "unsloth/gemma-3-4b-it-bnb-4bit"  # pre-quantized, skips 4-bit conversion OOM
MAX_SEQ_LEN = 2048   # 4B fits comfortably; raise if needed
LORA_RANK   = 16     # 4B on 12GB has headroom; raise to 32 if no OOM
BATCH_SIZE  = 2      # 4B allows larger batch
GRAD_ACCUM  = 4      # effective batch = 2 * 4 = 8
EPOCHS      = 2
LR          = 2e-4
OUTPUT_DIR  = "./output/gemma-capybara-lora"
EXPORT_GGUF = True   # set False to skip the slow GGUF export step

# ─── 2. Load model ────────────────────────────────────────────────────────────

print()
print("[2/6] Loading model in 4-bit (downloads ~2.5 GB on first run, cached after)...")
print(f"      Model: {HF_MODEL_ID}")
print()

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=HF_MODEL_ID,
    max_seq_length=MAX_SEQ_LEN,
    dtype=None,         # auto-detect (bfloat16 on Ampere+)
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_RANK,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=LORA_RANK * 2,
    lora_dropout=0.05,
    bias="none",
    use_gradient_checkpointing="unsloth",  # cuts VRAM ~30%
    random_state=42,
)

total_params     = sum(p.numel() for p in model.parameters())
trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
vram_after       = torch.cuda.memory_reserved(0) / 1e9

print(f"    Total params    : {total_params / 1e9:.2f} B")
print(f"    Trainable (LoRA): {trainable_params / 1e6:.1f} M  ({100 * trainable_params / total_params:.2f}%)")
print(f"    VRAM used now   : {vram_after:.2f} GB")
print()
print("    Model loaded successfully.")

# ─── 3. Load & format Capybara ────────────────────────────────────────────────

print()
print("[3/6] Downloading LDJnr/Capybara (16K conversations)...")

raw = load_dataset("LDJnr/Capybara", split="train")
print(f"    Downloaded {len(raw)} examples.")

# Capybara schema: {"id", "source", "conversation": [{"input": str, "output": str}, ...]}
def format_conversation(example):
    messages = []
    for turn in example["conversation"]:
        messages.append({"role": "user",      "content": turn["input"]})
        messages.append({"role": "assistant", "content": turn["output"]})
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}

print("    Formatting with Gemma chat template...")
dataset = raw.map(format_conversation, remove_columns=raw.column_names)

# Token length stats
sample_lengths = [len(tokenizer(ex["text"])["input_ids"]) for ex in dataset.select(range(200))]
avg_len = sum(sample_lengths) / len(sample_lengths)
max_len = max(sample_lengths)
print(f"    Token lengths (sample of 200): avg={avg_len:.0f}, max={max_len}")
if max_len > MAX_SEQ_LEN:
    print(f"    Note: some examples exceed MAX_SEQ_LEN={MAX_SEQ_LEN} and will be truncated.")

print()
print("    Sample formatted entry (first 400 chars):")
print("    " + "-" * 50)
for line in dataset[0]["text"][:400].splitlines():
    print(f"    {line}")
print("    ...")
print("    " + "-" * 50)
print()

# ─── Merge extra training data (feedback loop / distill agent) ────────────────

if EXTRA_DATA_PATH and os.path.exists(EXTRA_DATA_PATH):
    print(f"    Loading extra data from {EXTRA_DATA_PATH}...")
    with open(EXTRA_DATA_PATH) as f:
        raw_extra = [json.loads(l) for l in f if l.strip()]

    def format_extra(entry):
        # Support two storage formats:
        # 1. {"question": str, "answer": str}  — raw Q&A, apply template now
        # 2. {"messages": [...]}               — already structured, apply template
        if "question" in entry and "answer" in entry:
            messages = [
                {"role": "user",      "content": entry["question"]},
                {"role": "assistant", "content": entry["answer"]},
            ]
        elif "messages" in entry:
            # Extract user/assistant turns, skip tool turns for simplicity
            messages = [m for m in entry["messages"]
                        if m.get("role") in ("user", "assistant") and m.get("content")]
        else:
            return None
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
        return {"text": text}

    extra_formatted = [format_extra(e) for e in raw_extra]
    extra_formatted = [e for e in extra_formatted if e]  # drop None
    extra_dataset    = Dataset.from_list(extra_formatted)
    dataset          = concatenate_datasets([dataset, extra_dataset])
    print(f"    Added {len(extra_formatted)} extra examples. Total: {len(dataset)}")
elif EXTRA_DATA_PATH:
    print(f"    WARNING: --extra-data path not found: {EXTRA_DATA_PATH}")

print("    Dataset ready.")

# ─── 4. Train ─────────────────────────────────────────────────────────────────

print()
print("[4/6] Training...")
print(f"    Epochs          : {EPOCHS}")
print(f"    Effective batch : {BATCH_SIZE * GRAD_ACCUM}  (batch={BATCH_SIZE} x accum={GRAD_ACCUM})")
print(f"    Learning rate   : {LR}")
print(f"    LoRA rank       : {LORA_RANK}")
print(f"    Seq length      : {MAX_SEQ_LEN}")
total_steps = (len(dataset) // (BATCH_SIZE * GRAD_ACCUM)) * EPOCHS
print(f"    Est. steps      : ~{total_steps}")
print()
print("    Progress is logged every 25 steps.")
print("    Loss should decrease over time — if it stays flat or spikes, something is wrong.")
print()

os.makedirs(OUTPUT_DIR, exist_ok=True)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=MAX_SEQ_LEN,
    data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, padding=True),
    args=TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        num_train_epochs=EPOCHS,
        learning_rate=LR,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        gradient_checkpointing=True,
        logging_steps=25,
        save_strategy="epoch",
        save_total_limit=2,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        optim="adamw_8bit",      # 8-bit optimizer saves ~1 GB VRAM
        report_to="none",
        dataloader_num_workers=0,
    ),
)

train_start = time.time()
train_result = trainer.train()
elapsed = time.time() - train_start

hours, rem   = divmod(int(elapsed), 3600)
minutes, sec = divmod(rem, 60)
final_loss   = train_result.training_loss

print()
print(f"    Training complete in {hours}h {minutes}m {sec}s")
print(f"    Final training loss: {final_loss:.4f}")
if final_loss > 2.5:
    print("    WARNING: loss is high — the model may not have learned much.")
    print("             Consider increasing EPOCHS or checking the data format.")
elif final_loss < 0.5:
    print("    Note: very low loss — might be overfitting on 16K examples.")
    print("          This is usually fine for instruction tuning.")
else:
    print("    Loss looks healthy.")

# ─── 5. Save LoRA adapter ─────────────────────────────────────────────────────

print()
print("[5/6] Saving LoRA adapter...")
save_path = f"{OUTPUT_DIR}/final"
model.save_pretrained(save_path)
tokenizer.save_pretrained(save_path)

adapter_size_mb = sum(
    os.path.getsize(os.path.join(dp, f))
    for dp, _, files in os.walk(save_path)
    for f in files
) / 1e6
print(f"    Saved to: {save_path}")
print(f"    Adapter size: {adapter_size_mb:.0f} MB")
print()
print("    Adapter saved successfully.")

# ─── 6. Export to GGUF for Ollama ─────────────────────────────────────────────

print()
if EXPORT_GGUF:
    GGUF_DIR = "./output/gemma-capybara-gguf"
    print("[6/6] Exporting merged GGUF for Ollama...")
    print("      This merges the LoRA back into the base weights, then quantizes.")
    print("      Uses ~28 GB of system RAM (not VRAM). Takes 10-20 min.")
    print()
    os.makedirs(GGUF_DIR, exist_ok=True)
    model.save_pretrained_gguf(
        GGUF_DIR,
        tokenizer,
        quantization_method="q4_k_m",
    )
    gguf_files = [f for f in os.listdir(GGUF_DIR) if f.endswith(".gguf")]
    if gguf_files:
        gguf_path  = os.path.join(GGUF_DIR, gguf_files[0])
        gguf_size  = os.path.getsize(gguf_path) / 1e9
        print(f"    GGUF file : {gguf_path}  ({gguf_size:.1f} GB)")
    else:
        print("    WARNING: no .gguf file found in output dir — export may have failed.")
else:
    print("[6/6] Skipped GGUF export (EXPORT_GGUF=False).")

# ─── Done ─────────────────────────────────────────────────────────────────────

print()
print("=" * 60)
print("  ALL DONE")
print("=" * 60)
print()
print(f"  LoRA adapter : {OUTPUT_DIR}/final/")
if EXPORT_GGUF and gguf_files:
    print(f"  GGUF model   : {gguf_path}")
    print()
    print("  To load into Ollama:")
    print()
    print(f"    cat > /tmp/Modelfile <<'EOF'")
    print(f"    FROM {os.path.abspath(gguf_path)}")
    print(f"    SYSTEM \"You are a helpful AI assistant.\"")
    print(f"    EOF")
    print()
    print(f"    ollama create gemma-capybara -f /tmp/Modelfile")
    print(f"    ollama run gemma-capybara")
print()
print("  Training summary:")
print(f"    Duration    : {hours}h {minutes}m {sec}s")
print(f"    Final loss  : {final_loss:.4f}")
print(f"    Adapter     : {adapter_size_mb:.0f} MB")
print()
