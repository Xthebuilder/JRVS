"""
Inference wrapper for the local data-prep model (jrvs-data-prep).

Replaces jrvs-teacher (20B) for generating training examples in feedback_loop.py.
Falls back to jrvs-teacher automatically if jrvs-data-prep isn't available.

Usage in feedback_loop.py:
  from data_prep.model import DataPrepModel
  data_prep = DataPrepModel()
  example = data_prep.generate(question, bad_response, search_results)
"""

import json
import requests
from typing import Optional

OLLAMA_URL       = "http://localhost:11434"
DATA_PREP_MODEL  = "jrvs-data-prep"
TEACHER_MODEL    = "jrvs-teacher"

_TASK_SYSTEM = """You are a training data generator. Given a question and a bad AI response, output a JSON object with the ideal response.

Output format — exactly this JSON, nothing else:
{"question": "<original question>", "answer": "<ideal response>"}

Ideal answer rules:
- Lead with the direct answer
- Cite factual claims inline: (Source: Publication Name)
- End with: "Confidence: [high/moderate/low] — [brief reason]"
- No markdown, no bullets — plain prose only
- Concise: answer completely then stop"""


def _available_models() -> set:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return {m["name"].split(":")[0] for m in r.json().get("models", [])}
    except Exception:
        return set()


def _call_model(model: str, question: str, bad_response: str,
                search_results: Optional[str] = None) -> Optional[dict]:
    search_block = f"\n\nWeb search results:\n{search_results}" if search_results else ""
    prompt = (
        f'Question: "{question}"\n\n'
        f'Bad response: "{bad_response}"{search_block}\n\n'
        f"Write the ideal response as JSON."
    )
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json={
            "model":   model,
            "messages": [
                {"role": "system", "content": _TASK_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            "stream":  False,
            "options": {"temperature": 0.3},
        }, timeout=120)
        r.raise_for_status()
        content = r.json()["message"]["content"].strip()

        # Strip markdown code fences if model added them
        if content.startswith("```"):
            lines   = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        parsed = json.loads(content)
        if "question" in parsed and "answer" in parsed:
            return parsed
        return None

    except json.JSONDecodeError:
        return None
    except Exception:
        return None


class DataPrepModel:
    """
    Generate ideal training examples from (question, bad_response) pairs.

    Automatically selects jrvs-data-prep (local 3B) if available,
    falls back to jrvs-teacher (20B) otherwise.
    """

    def __init__(self):
        models = _available_models()
        if DATA_PREP_MODEL in models:
            self.model  = DATA_PREP_MODEL
            self.is_local = True
        elif TEACHER_MODEL in models:
            self.model  = TEACHER_MODEL
            self.is_local = False
        else:
            self.model  = TEACHER_MODEL   # will fail gracefully at call time
            self.is_local = False

        print(f"[DataPrepModel] Using: {self.model} "
              f"({'local 3B' if self.is_local else '20B teacher fallback'})")

    def generate(self, question: str, bad_response: str,
                 search_results: Optional[str] = None) -> Optional[dict]:
        """
        Returns {question, answer} or None on failure.
        Automatically falls back to teacher if local model fails.
        """
        result = _call_model(self.model, question, bad_response, search_results)

        # If local model failed, try teacher as backup
        if result is None and self.is_local:
            print(f"  Local model failed, falling back to {TEACHER_MODEL}...")
            result = _call_model(TEACHER_MODEL, question, bad_response, search_results)

        return result

    @property
    def name(self) -> str:
        return self.model
