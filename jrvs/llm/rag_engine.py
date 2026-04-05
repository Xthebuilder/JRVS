"""
JRVS Core — RAG engine (web search only).

Retrieves context from the web_search and yt_search FAISS namespaces
built up by WebSearchEngine, then builds a prompt for Ollama.
"""

from __future__ import annotations

import logging
from typing import Any

from jrvs.config import Config

log = logging.getLogger(__name__)


try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    _count_tokens = lambda t: len(_enc.encode(t, disallowed_special=()))
except Exception:
    _count_tokens = lambda t: int(len(t.split()) * 1.3)


class RAGEngine:
    """Retrieve web context and inject it into an Ollama prompt."""

    def __init__(self, db=None) -> None:
        from jrvs.storage.database import Database
        self._db = db or Database()

    # ── Context retrieval ────────────────────────────────────────────────

    def retrieve_web_context(self, query: str, top_k: int | None = None) -> str:
        """Semantic search over accumulated Brave results."""
        top_k = top_k or Config.WEB_SEARCH_TOP_K
        try:
            hits = self._semantic_search(query, "web_search", top_k)
        except Exception as exc:
            log.warning("Web context retrieval failed: %s", exc)
            return ""
        if not hits:
            return ""
        lines = [f'\n=== Prior Web Knowledge (query: "{query}") ===']
        for i, r in enumerate(hits, 1):
            lines.append(
                f"{i}. [{r.get('title','')}]({r.get('url','')})\n"
                f"   {r.get('snippet','')}\n"
                f"   (similarity: {r.get('score',0):.3f})"
            )
        return "\n".join(lines)

    def retrieve_yt_search_context(self, query: str, top_k: int | None = None) -> str:
        """Semantic search over accumulated YouTube search results."""
        top_k = top_k or Config.YT_SEARCH_TOP_K
        try:
            hits = self._semantic_search(query, "yt_search", top_k)
        except Exception as exc:
            log.warning("YT search context retrieval failed: %s", exc)
            return ""
        if not hits:
            return ""
        lines = [f'\n=== Prior YouTube Knowledge (query: "{query}") ===']
        for i, r in enumerate(hits, 1):
            lines.append(
                f"{i}. [{r.get('title','')}]({r.get('url','')}) "
                f"by {r.get('channel_title','')}\n"
                f"   {r.get('description','')}\n"
                f"   (similarity: {r.get('score',0):.3f})"
            )
        return "\n".join(lines)

    # ── Full query pipeline ───────────────────────────────────────────────

    def query(
        self,
        question: str,
        system_prompt: str = "",
        token_budget: int = 3000,
    ) -> str:
        """Retrieve context, build prompt, send to Ollama, return answer."""
        from jrvs.llm.ollama_client import OllamaClient

        context_parts = [
            self.retrieve_web_context(question),
            self.retrieve_yt_search_context(question),
        ]
        context = "\n".join(p for p in context_parts if p)

        system = system_prompt or (
            "You are JRVS, a helpful AI assistant. "
            "Use the provided search context to answer accurately. "
            "If the context is empty, answer from general knowledge."
        )

        # Truncate context to token budget
        if context:
            while _count_tokens(context) > token_budget and "\n" in context:
                context = context.rsplit("\n", 1)[0]

        user_msg = f"Context:\n{context}\n\nQuestion: {question}" if context else question

        llm = OllamaClient()
        return llm.chat(messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ])

    # ── Internal ──────────────────────────────────────────────────────────

    def _semantic_search(
        self, query: str, namespace: str, k: int
    ) -> list[dict[str, Any]]:
        from jrvs.embeddings.encoder import EmbeddingEncoder
        from jrvs.embeddings.vector_store import VectorStore
        store = VectorStore(namespace)
        if store.size == 0:
            return []
        q_vec = EmbeddingEncoder.get().encode_single(query)
        return store.search(q_vec, k=k)
