# ============================================================
#  Gemma-3-12B x Capybara — QLoRA Fine-Tune (Kaggle T4)
#  Fixed version — uses FastModel (correct for Gemma 3 vision model)
#
#  BEFORE RUNNING:
#  1. Settings → Accelerator → GPU T4 x2
#  2. Settings → Internet → ON
#  3. Add-ons → Secrets → HF_TOKEN (attach to this notebook)
# ============================================================


# ── CELL 1: Install ──────────────────────────────────────────

import subprocess, sys

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "unsloth[colab-new]",
    "--extra-index-url", "https://download.pytorch.org/whl/cu121",
], check=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "--no-deps", "trl", "peft", "accelerate",
], check=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "bitsandbytes", "datasets", "huggingface_hub",
], check=True)
print("Done.")


# ── CELL 2: HuggingFace login ────────────────────────────────

from kaggle_secrets import UserSecretsClient
from huggingface_hub import login

login(token=UserSecretsClient().get_secret("HF_TOKEN"), add_to_git_credential=False)
print("HF login OK.")


# ── CELL 3: Load model ───────────────────────────────────────
# Uses FastModel — required for Gemma 3 (vision-language model)

import torch
from unsloth import FastModel

HF_MODEL_ID = "unsloth/gemma-3-12b-it-bnb-4bit"
MAX_SEQ_LEN = 1024
LORA_RANK   = 8
OUTPUT_DIR  = "/kaggle/working/gemma-capybara-lora"

model, tokenizer = FastModel.from_pretrained(
    model_name=HF_MODEL_ID,
    max_seq_length=MAX_SEQ_LEN,
    load_in_4bit=True,
    full_finetuning=False,
)

model = FastModel.get_peft_model(
    model,
    r=LORA_RANK,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=LORA_RANK * 2,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
)

total     = sum(p.numel() for p in model.parameters())
trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(f"Total params    : {total / 1e9:.2f} B")
print(f"Trainable (LoRA): {trainable / 1e6:.1f} M  ({100 * trainable / total:.2f}%)")
print(f"VRAM used now   : {torch.cuda.memory_reserved(0) / 1e9:.2f} GB")


# ── CELL 4: Dataset ──────────────────────────────────────────

from datasets import load_dataset

raw = load_dataset("LDJnr/Capybara", split="train")
print(f"Downloaded {len(raw)} examples.")

def format_conversation(example):
    messages = []
    for turn in example["conversation"]:
        messages.append({"role": "user",      "content": turn["input"]})
        messages.append({"role": "assistant", "content": turn["output"]})
    return {"text": tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )}

dataset = raw.map(format_conversation, remove_columns=raw.column_names)
print(f"Dataset ready: {len(dataset)} examples.")
print(dataset[0]["text"][:300])


# ── CELL 5: Train ────────────────────────────────────────────

import os, time
from trl import SFTTrainer
from transformers import TrainingArguments

os.makedirs(OUTPUT_DIR, exist_ok=True)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    formatting_func=lambda x: x["text"],
    max_seq_length=MAX_SEQ_LEN,
    args=TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=1,
        learning_rate=2e-4,
        fp16=True,
        bf16=False,
        gradient_checkpointing=True,
        logging_steps=25,
        save_strategy="epoch",
        save_total_limit=1,
        warmup_steps=50,
        lr_scheduler_type="cosine",
        optim="adamw_8bit",
        report_to="none",
        dataloader_num_workers=0,
    ),
)

t0 = time.time()
result = trainer.train()
elapsed = time.time() - t0
h, rem = divmod(int(elapsed), 3600)
m, s = divmod(rem, 60)
print(f"\nDone in {h}h {m}m {s}s  |  final loss: {result.training_loss:.4f}")


# ── CELL 6: Save ─────────────────────────────────────────────

save_path = f"{OUTPUT_DIR}/final"
model.save_pretrained(save_path)
tokenizer.save_pretrained(save_path)

size_mb = sum(
    os.path.getsize(os.path.join(dp, f))
    for dp, _, files in os.walk(save_path)
    for f in files
) / 1e6
print(f"Adapter saved: {save_path}  ({size_mb:.0f} MB)")
print("Download from the Kaggle output panel (right sidebar).")
