#!/usr/bin/env python3
"""
Bootstrap the local data-prep model.

Uses jrvs-teacher (gpt-oss:20b) to generate ~300 examples of the task:
  (question + bad_response) → perfect JSON training example

These examples are then used by train.py to fine-tune a local 3B model
that can replace the 20B teacher for data generation in feedback_loop.py.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  source ~/finetune_env/bin/activate
  python data_prep/bootstrap.py              # generate all 300 examples
  python data_prep/bootstrap.py --count 50   # quick test run
  python data_prep/bootstrap.py --resume     # skip already-generated examples
"""

import json
import sys
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from search_utils import search as web_search

OLLAMA_URL    = "http://localhost:11434"
TEACHER_MODEL = "jrvs-teacher"
OUTPUT_FILE   = Path("./data/data_prep/bootstrap.jsonl")
TARGET_COUNT  = 300

# ─── Seed examples — question + realistic bad response ───────────────────────
# Each entry is (question, bad_response, needs_search)
# Bad responses are intentionally representative of common failure modes:
#   verbose/padded, wrong format, missing citation, vague, outdated, off-topic

SEEDS = [
    # ── Technical / factual ───────────────────────────────────────────────────
    (
        "What is the context window size of Llama 3.1 8B?",
        "Llama 3.1 8B has a very large context window that allows it to process a lot of text. "
        "It was released by Meta and is quite capable for its size. The context window is something "
        "like 128k tokens or maybe it was 64k, I'm not entirely sure of the exact number.",
        False,
    ),
    (
        "What is LoRA fine-tuning?",
        "LoRA stands for Low-Rank Adaptation. It's a way to fine-tune language models. "
        "Basically you add some layers and train those. It's used to make models better at specific tasks. "
        "I hope this helps explain what LoRA is!",
        False,
    ),
    (
        "What's the difference between RAG and fine-tuning?",
        "RAG and fine-tuning are both techniques used in AI. Fine-tuning changes the model weights, "
        "while RAG retrieves documents. Both have pros and cons. It really depends on your use case "
        "which one you should use. There are many factors to consider.",
        False,
    ),
    (
        "How does FAISS vector search work?",
        "FAISS is a library from Facebook. It does vector search. You give it vectors and it finds "
        "similar ones. It's very fast and used in many AI applications. There are different index types "
        "you can use depending on your needs.",
        False,
    ),
    (
        "What is quantization in the context of LLMs?",
        "Quantization is when you make a model smaller. It reduces precision from float32 to int8 "
        "or similar. This makes inference faster. There is some quality loss but usually not much. "
        "QLoRA uses quantization. It's a good technique for running models on consumer hardware.",
        False,
    ),
    (
        "What does temperature do in language model inference?",
        "Temperature controls the randomness of the output. Higher temperature means more random, "
        "lower means more deterministic. Temperature of 0 is greedy. It's one of the important "
        "parameters. You should experiment with different values to find what works best for you.",
        False,
    ),
    (
        "What is the difference between GGUF and GGML?",
        "GGUF and GGML are both file formats for language models. GGML was the original and GGUF "
        "is newer. They are used with llama.cpp. GGUF has better support for metadata. Most new "
        "models use GGUF now. They are both used for running models locally.",
        False,
    ),
    (
        "What is cross-entropy loss?",
        "Cross-entropy loss is a loss function used in machine learning. It measures how different "
        "predicted probabilities are from actual labels. Lower is better during training. "
        "It's used a lot in classification. I hope that helps!",
        False,
    ),
    (
        "What are attention heads in a transformer?",
        "Attention heads are part of the transformer architecture. Multi-head attention allows "
        "the model to attend to different parts of the input at the same time. More heads "
        "generally means the model can learn more complex patterns. It's a fundamental part "
        "of how transformers work.",
        False,
    ),
    (
        "What is the difference between float16 and bfloat16?",
        "Float16 and bfloat16 are both 16-bit floating point formats. They are used to speed up "
        "training and reduce memory usage. bfloat16 has better dynamic range. float16 has more "
        "precision in the mantissa. Modern GPUs support both. They are commonly used in training.",
        False,
    ),

    # ── Market / business ─────────────────────────────────────────────────────
    (
        "What are the main differences between Anthropic and OpenAI as companies?",
        "Anthropic and OpenAI are both AI companies. OpenAI made ChatGPT. Anthropic made Claude. "
        "They have different approaches to safety. Both are working on powerful AI systems. "
        "They are competitors in the AI space. There are many differences between them.",
        False,
    ),
    (
        "What is the business model of Hugging Face?",
        "Hugging Face is a company that does AI stuff. They have a hub where people share models. "
        "They make money somehow from enterprise customers. They are quite popular in the AI "
        "community. They have raised a lot of funding. It's a successful company.",
        False,
    ),
    (
        "What is inference cost and why does it matter for AI startups?",
        "Inference cost is how much it costs to run an AI model. It matters because it affects "
        "profit margins. If inference is expensive you can't make money. It's a big deal for "
        "AI companies. They try to optimize their models to reduce cost. This is an important "
        "consideration for any AI business.",
        False,
    ),
    (
        "What does GPU memory bandwidth have to do with LLM inference speed?",
        "GPU memory bandwidth is related to how fast data can be moved. For LLMs this matters "
        "because the model weights need to be loaded. Higher bandwidth means faster inference "
        "generally. It's one of the key specs to look at when choosing hardware for AI workloads. "
        "Different GPUs have different bandwidth specs.",
        False,
    ),
    (
        "What is Ollama and what problem does it solve?",
        "Ollama is a tool for running AI models locally. It makes it easy to run models on your "
        "computer. You can pull models and run them with simple commands. It's like Docker but "
        "for AI models. It solves the problem of running local models. Many people use it.",
        False,
    ),

    # ── Content / creative ────────────────────────────────────────────────────
    (
        "How should I structure a technical blog post?",
        "A technical blog post should have good structure. Start with an introduction that "
        "explains what you'll cover. Then have the main content. End with a conclusion. "
        "Use headers to organize your content. Make sure to be clear and concise. "
        "Good luck writing your post!",
        False,
    ),
    (
        "What makes a good executive summary?",
        "An executive summary should be a summary of the main document. It should be concise "
        "and cover the key points. Executives are busy so it needs to be short. Include the "
        "main findings and recommendations. Usually 1-2 pages is appropriate. Make sure "
        "it can stand on its own.",
        False,
    ),
    (
        "How do I write a cold email that gets responses?",
        "Cold emails need to be good to get responses. Keep them short. Personalize them. "
        "Have a clear subject line. Explain what you want. Have a call to action. Follow up "
        "if you don't hear back. Don't be spammy. Make sure to proofread before sending.",
        False,
    ),
    (
        "What is the Pyramid Principle in writing?",
        "The Pyramid Principle is a writing technique. You start with the conclusion and then "
        "provide supporting evidence. It's used in consulting. McKinsey uses it a lot. "
        "It's good for business writing. The idea is to lead with your main point.",
        False,
    ),
    (
        "How do I write good commit messages?",
        "Good commit messages are important. Use present tense. Be descriptive. Keep the "
        "subject line short. You can add a body with more details. Reference issues if "
        "applicable. Don't write vague messages like 'fix stuff'. Be specific about what "
        "changed and why.",
        False,
    ),

    # ── JRVS / personal assistant specific ───────────────────────────────────
    (
        "Can you remember what I told you last week?",
        "I don't have memory between conversations. Each conversation starts fresh for me. "
        "I can't recall what we talked about previously. You would need to remind me of "
        "the context. This is a limitation of how I work. I'm sorry I can't remember.",
        False,
    ),
    (
        "Search the web for the latest Python 3.13 release notes",
        "Python 3.13 is the latest version. It has various improvements and new features. "
        "I'll look that up for you. Python releases happen regularly. You can find release "
        "notes on the official Python website at python.org. It includes many improvements.",
        True,
    ),
    (
        "What's the current price of NVIDIA stock?",
        "NVIDIA is a semiconductor company known for making GPUs. Their stock is traded on "
        "the NASDAQ under NVDA. Stock prices change throughout the day. I don't have "
        "real-time data so I cannot give you the exact current price. You should check "
        "a financial website for current prices.",
        True,
    ),
    (
        "What happened in AI news this week?",
        "There have been many developments in AI recently. Various companies have released "
        "new models and tools. The field is advancing rapidly. I don't have real-time news "
        "access so I may not have the very latest information. You can check tech news sites "
        "for the most current AI news.",
        True,
    ),
    (
        "Find me the best open source embedding model for semantic search right now",
        "There are several good embedding models for semantic search. Some popular ones include "
        "sentence-transformers. The best model depends on your specific use case. You should "
        "benchmark different models on your data. There are leaderboards that rank models. "
        "It's hard to say which is definitively best without more context.",
        True,
    ),

    # ── Reasoning / step-by-step ──────────────────────────────────────────────
    (
        "I have 8GB VRAM. What's the largest model I can run with Ollama?",
        "With 8GB VRAM you can run some models. It depends on the quantization. 7B models "
        "should work with 4-bit quantization. Larger models might not fit. You need to "
        "consider the quantization level. 4-bit uses less memory than 8-bit. Q4_K_M is "
        "a good balance of quality and size.",
        False,
    ),
    (
        "Explain gradient descent like I'm a programmer, not a mathematician",
        "Gradient descent is an optimization algorithm. It's used to minimize a loss function. "
        "You compute the gradient and move in the opposite direction. This is repeated until "
        "you reach a minimum. The learning rate controls how big each step is. It's the "
        "fundamental algorithm behind training neural networks.",
        False,
    ),
    (
        "What should I do if my fine-tuning loss isn't going down?",
        "If your loss isn't going down there could be several issues. Check your learning rate. "
        "Make sure your data is formatted correctly. The batch size might need adjusting. "
        "There could be bugs in your training code. Try a smaller learning rate first. "
        "Debugging training issues can be tricky.",
        False,
    ),
    (
        "How many parameters does a 7B model actually have?",
        "A 7B model has 7 billion parameters. These are the weights that are learned during "
        "training. Each parameter is typically stored as a floating point number. At float16 "
        "that's 2 bytes per parameter so 7B parameters would be about 14GB. With 4-bit "
        "quantization it would be around 3.5GB.",
        False,
    ),
    (
        "What is the difference between supervised and unsupervised learning?",
        "Supervised learning uses labeled data. Unsupervised learning finds patterns without "
        "labels. They are both types of machine learning. Supervised is more common for "
        "specific tasks. Unsupervised is used for clustering and discovery. There are also "
        "semi-supervised and self-supervised learning approaches.",
        False,
    ),
]


# ─── System prompt for teacher ────────────────────────────────────────────────

TASK_SYSTEM = """You are generating training data for a small 3B language model that will learn to transform bad AI responses into ideal training examples.

Your output must be a JSON object with exactly these fields:
{
  "question": "<the original question, unchanged>",
  "answer": "<the ideal response — direct, cited if factual, with Confidence sentence>"
}

The ideal answer rules:
- Lead with the direct answer — no preamble, no "According to...", no "Great question!"
- For factual claims: cite inline as (Source: Publication Name) — no URLs, no brackets
- End with exactly: "Confidence: [high/moderate/low] — [one brief reason]"
- No markdown, no bullet points, no headers — plain prose only
- Be concise: answer completely then stop

Output ONLY the JSON object. No explanation, no markdown code blocks."""


def ask_teacher(question: str, bad_response: str, needs_search: bool) -> dict | None:
    """Ask jrvs-teacher to fix a bad response. Returns {question, answer} dict."""
    search_context = ""
    if needs_search:
        try:
            results = web_search(question, max_results=3)
            search_context = f"\n\nWeb search results:\n{results}"
        except Exception as e:
            print(f"  Search failed: {e}")

    prompt = f"""Question: "{question}"

Bad response given: "{bad_response}"{search_context}

Write the ideal response as a JSON object with "question" and "answer" fields."""

    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json={
            "model": TEACHER_MODEL,
            "messages": [
                {"role": "system", "content": TASK_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.3},
        }, timeout=120)
        r.raise_for_status()
        content = r.json()["message"]["content"].strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        parsed = json.loads(content)
        if "question" in parsed and "answer" in parsed:
            return parsed
        print(f"  Missing fields in response: {list(parsed.keys())}")
        return None

    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        return None
    except Exception as e:
        print(f"  Teacher error: {e}")
        return None


def generate_variation(base_seed: tuple, variation_index: int) -> tuple:
    """
    Produce variations of seed examples by transforming the bad response style.
    Different variation_index values produce different failure modes.
    """
    question, bad_response, needs_search = base_seed

    # Cycle through additional failure modes
    failure_modes = [
        # 0: original
        bad_response,
        # 1: over-hedged / uncertain
        f"I'm not entirely sure about this, but I think {bad_response.lower()[:120]} "
        f"However, you should verify this information as I may be wrong.",
        # 2: too long / padded
        f"That's a great question! Let me think about this carefully. "
        f"{bad_response} "
        f"I hope this comprehensive answer has been helpful to you today!",
        # 3: wrong format (uses markdown)
        f"**Answer:** {bad_response[:100]}\n\n"
        f"- Point one\n- Point two\n- Point three\n\n"
        f"*Note: This may vary depending on your specific situation.*",
        # 4: no confidence / wishy-washy
        f"It's hard to say definitively. {bad_response[:100]} "
        f"But it really depends on the context and your specific needs.",
        # 5: leads with disclaimer
        f"I should note that I'm an AI and my knowledge has a cutoff date. "
        f"That said, {bad_response.lower()[:120]}",
        # 6: repeat/summarize at end
        f"{bad_response} "
        f"So to summarize what I just said: {bad_response[:80].lower()}",
        # 7: vague with jargon
        f"This is a multifaceted topic. {bad_response[:80]} "
        f"The implications are significant for various stakeholders in the ecosystem.",
        # 8: answers different question
        f"That's related to a broader topic. Generally speaking, AI systems have many "
        f"capabilities. {bad_response[:80]} There are many factors to consider.",
        # 9: missing citation
        bad_response + " (no source cited for these claims)",
    ]

    mode = variation_index % len(failure_modes)
    return (question, failure_modes[mode], needs_search)


def load_existing(output_file: Path) -> set:
    """Load already-generated questions to enable --resume."""
    if not output_file.exists():
        return set()
    seen = set()
    with open(output_file) as f:
        for line in f:
            try:
                obj = json.loads(line)
                seen.add(obj["input"]["question"][:60])
            except Exception:
                pass
    return seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count",  type=int, default=TARGET_COUNT,
                        help=f"Number of examples to generate (default: {TARGET_COUNT})")
    parser.add_argument("--resume", action="store_true",
                        help="Skip questions already in output file")
    args = parser.parse_args()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Check teacher is available
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    except Exception:
        print("Ollama not running. Start it and try again.")
        sys.exit(1)

    existing = load_existing(OUTPUT_FILE) if args.resume else set()
    if existing:
        print(f"Resuming — {len(existing)} examples already generated.")

    # Build full seed list with variations
    all_seeds = []
    # First pass: all originals
    for seed in SEEDS:
        all_seeds.append((seed, 0))
    # Additional variations until we have enough
    variation = 1
    while len(all_seeds) < args.count:
        for seed in SEEDS:
            all_seeds.append((seed, variation))
            if len(all_seeds) >= args.count:
                break
        variation += 1

    all_seeds = all_seeds[:args.count]

    print(f"\nGenerating {len(all_seeds)} bootstrap examples using {TEACHER_MODEL}...")
    print(f"Output: {OUTPUT_FILE}\n")

    generated = 0
    skipped   = 0
    failed    = 0

    for i, (seed, var_idx) in enumerate(all_seeds, 1):
        question, bad_response, needs_search = generate_variation(seed, var_idx)
        short_q = question[:60]

        if short_q in existing:
            skipped += 1
            continue

        print(f"[{i}/{len(all_seeds)}] {short_q}...")

        result = ask_teacher(question, bad_response, needs_search)
        if not result:
            failed += 1
            print(f"  FAILED")
            continue

        # Store as input/output pair for training the data-prep model
        entry = {
            "input": {
                "question":     question,
                "bad_response": bad_response,
                "needs_search": needs_search,
            },
            "output": {
                "question": result["question"],
                "answer":   result["answer"],
            },
            "generated_at": datetime.now().isoformat(),
            "teacher_model": TEACHER_MODEL,
            "variation":    var_idx,
        }

        with open(OUTPUT_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

        generated += 1
        print(f"  OK — answer preview: {result['answer'][:80]}...")

        # Brief pause to avoid hammering Ollama
        time.sleep(0.5)

    total = sum(1 for _ in open(OUTPUT_FILE)) if OUTPUT_FILE.exists() else 0
    print(f"\nDone. Generated: {generated}, Skipped: {skipped}, Failed: {failed}")
    print(f"Total in file: {total}")
    print(f"\nNext step: python data_prep/train.py")


if __name__ == "__main__":
    main()
