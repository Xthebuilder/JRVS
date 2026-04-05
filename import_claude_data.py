#!/usr/bin/env python3
"""
Converts Claude's generated training examples into approved.jsonl
ready for fine-tuning.

Usage:
  1. Paste GENERATION_PROMPT.md into a Claude window
  2. Save the output to data/distill/raw_output.txt
  3. Run: python import_claude_data.py

  Optional — review before importing:
  python import_claude_data.py --review
"""

import json
import re
import sys
import argparse
from datetime import datetime
from pathlib import Path

DATA_DIR      = Path("./data/distill")
RAW_FILE      = DATA_DIR / "raw_output.txt"
APPROVED_FILE = DATA_DIR / "approved.jsonl"

def parse_raw(text):
    """Parse Claude's output into structured examples."""
    examples = []
    blocks = re.split(r"---EXAMPLE---", text)

    for block in blocks:
        if "---END---" not in block:
            continue
        block = block[:block.index("---END---")].strip()

        def field(name, content):
            pattern = rf"^{name}:\s*(.+?)(?=\n[A-Z_]+:|\Z)"
            m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
            return m.group(1).strip() if m else ""

        category    = field("CATEGORY",       block).lower()
        needs_search= field("NEEDS_SEARCH",   block).lower() == "yes"
        question    = field("QUESTION",       block)
        search_query= field("SEARCH_QUERY",   block)
        search_results = field("SEARCH_RESULTS", block)
        answer      = field("ANSWER",         block)

        if not question or not answer:
            continue

        examples.append({
            "category":       category,
            "needs_search":   needs_search,
            "question":       question,
            "search_query":   search_query if needs_search else None,
            "search_results": search_results if needs_search else None,
            "answer":         answer,
        })

    return examples


def build_text(ex):
    """Build Qwen2.5 chat format string."""
    parts = []

    # User turn
    parts.append(f"<|im_start|>user\n{ex['question']}<|im_end|>")

    if ex["needs_search"]:
        # Tool call turn
        call = json.dumps({"name": "web_search",
                           "arguments": {"query": ex["search_query"]}}, indent=2)
        parts.append(f"<|im_start|>assistant\n<tool_call>\n{call}\n</tool_call><|im_end|>")

        # Tool result turn
        parts.append(f"<|im_start|>tool\n{ex['search_results']}<|im_end|>")

    # Final answer turn
    parts.append(f"<|im_start|>assistant\n{ex['answer']}<|im_end|>")

    return "\n".join(parts)


def to_jsonl_entry(ex):
    # Store raw Q&A — training script applies the correct chat template
    # at training time so it's always right regardless of base model
    return {
        "id":            f"{ex['category']}_{int(datetime.now().timestamp())}",
        "category":      ex["category"],
        "used_search":   ex["needs_search"],
        "question":      ex["question"],
        "answer":        ex["answer"],
        "teacher_model": "claude-sonnet-4-6",
        "generated_at":  datetime.now().isoformat(),
    }


def review_and_import(examples):
    approved = 0
    skipped  = 0

    print(f"\nReviewing {len(examples)} examples.")
    print("a=approve  s=skip  q=quit\n")

    for i, ex in enumerate(examples, 1):
        print(f"[{i}/{len(examples)}] {ex['category'].upper()} | search={ex['needs_search']}")
        print(f"Q: {ex['question']}")
        print(f"\nA: {ex['answer'][:400]}{'...' if len(ex['answer']) > 400 else ''}")

        while True:
            c = input("\n> ").strip().lower()
            if c == "a":
                entry = to_jsonl_entry(ex)
                with open(APPROVED_FILE, "a") as f:
                    f.write(json.dumps(entry) + "\n")
                approved += 1
                print("  Approved.")
                break
            elif c == "s":
                skipped += 1
                print("  Skipped.")
                break
            elif c == "q":
                print(f"\nStopped early. Approved {approved}, skipped {skipped}.")
                return
            else:
                print("  a/s/q")

    print(f"\nDone. Approved {approved}, skipped {skipped}.")
    total = sum(1 for _ in open(APPROVED_FILE)) if APPROVED_FILE.exists() else 0
    print(f"Total approved dataset: {total} examples.")
    print(f"\nRun training when ready:  python distill_agent.py --train")


def auto_import(examples):
    count = 0
    for ex in examples:
        entry = to_jsonl_entry(ex)
        with open(APPROVED_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        count += 1
    print(f"Imported {count} examples to {APPROVED_FILE}")
    total = sum(1 for _ in open(APPROVED_FILE))
    print(f"Total approved dataset: {total} examples.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review",   action="store_true", help="Review each example before importing")
    parser.add_argument("--input",    default=str(RAW_FILE), help="Path to Claude's raw output file")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Raw output file not found: {input_path}")
        print(f"Save Claude's response to {RAW_FILE} then run again.")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    text     = input_path.read_text()
    examples = parse_raw(text)

    if not examples:
        print("No examples parsed. Check that Claude used the ---EXAMPLE--- format.")
        sys.exit(1)

    print(f"Parsed {len(examples)} examples from {input_path}")

    cats = {}
    for ex in examples:
        cats[ex["category"]] = cats.get(ex["category"], 0) + 1
    for cat, n in sorted(cats.items()):
        print(f"  {cat:<15} {n}")

    if args.review:
        review_and_import(examples)
    else:
        auto_import(examples)


if __name__ == "__main__":
    main()
