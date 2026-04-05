"""
Mem0-backed memory retriever for JRVS.

Drop-in replacement for RAGRetriever — identical public interface so nothing
else in the codebase needs to change.

Architecture:
  - LLM (fact extraction):  Ollama / Gemma  (local)
  - Embedder:               Ollama / nomic-embed-text (local, 768-dim)
  - Vector store:           Qdrant on-disk  (local, no server required)
  - History DB:             SQLite          (local)

All data stays on-device; no external API calls.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

# Mem0's memory.main logs ERROR for NONE-event upserts (a known library bug
# where it tries to store an empty vector when a fact hasn't changed).
# Our code already catches and handles the resulting exception — suppress the
# noisy internal log so it doesn't pollute the JRVS console.
logging.getLogger("mem0.memory.main").setLevel(logging.CRITICAL)

from config import (
    OLLAMA_BASE_URL,
    DEFAULT_MODEL,
    MEM0_EMBEDDING_MODEL,
    MEM0_DATA_DIR,
    MEM0_COLLECTION_NAME,
    MAX_CONTEXT_LENGTH,
)
from core.database import db

logger = logging.getLogger(__name__)

# Namespace that scopes document memories separately from conversation memories
_DOCS_AGENT_ID = "jrvs_docs"
_DEFAULT_USER   = "jrvs_default"

# Mem0 uses the LLM to extract facts from each message; very long content
# should be chunked so Gemma doesn't exceed its context window.
_MAX_CHUNK_CHARS = 3000


def _chunk_content(text: str) -> List[str]:
    """Split long text into ~_MAX_CHUNK_CHARS pieces on paragraph boundaries."""
    if len(text) <= _MAX_CHUNK_CHARS:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = start + _MAX_CHUNK_CHARS
        if end < len(text):
            boundary = text.rfind("\n\n", start, end)
            if boundary > start:
                end = boundary
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


class Mem0RAGRetriever:
    """
    Wraps the mem0ai ``Memory`` class with the same interface as RAGRetriever
    so every existing import — ``from rag.retriever import rag_retriever`` —
    gets Mem0 behaviour without touching any other file.
    """

    def __init__(self) -> None:
        self._mem0 = None
        self._initialized = False
        self._docs_added = 0

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        if self._initialized:
            return

        from mem0 import Memory  # lazy import — only pulled in when needed

        data_dir = Path(MEM0_DATA_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)

        # Ensure all existing files in the data dir are user-writable.
        # SQLite raises "attempt to write a readonly database" when the DB file
        # or its parent directory lacks write permission for the running user.
        import stat as _stat
        for p in data_dir.rglob("*"):
            try:
                current = p.stat().st_mode
                p.chmod(current | _stat.S_IRUSR | _stat.S_IWUSR)
            except OSError:
                pass

        # Remove a stale Qdrant lock file left by a crashed previous process.
        # Qdrant opens in read-only mode (or raises) when it sees a lock it did
        # not create, producing the "readonly database" error propagated by Mem0.
        qdrant_lock = data_dir / "qdrant" / ".lock"
        if qdrant_lock.exists():
            try:
                qdrant_lock.unlink()
                logger.info("Removed stale Qdrant lock file: %s", qdrant_lock)
            except OSError as exc:
                logger.warning("Could not remove Qdrant lock file: %s", exc)

        config = {
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": DEFAULT_MODEL,
                    "ollama_base_url": OLLAMA_BASE_URL,
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": MEM0_EMBEDDING_MODEL,
                    "ollama_base_url": OLLAMA_BASE_URL,
                    "embedding_dims": 768,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": MEM0_COLLECTION_NAME,
                    "path": str(data_dir / "qdrant"),
                    "embedding_model_dims": 768,
                },
            },
            "history_db_path": str(data_dir / "mem0_history.db"),
        }

        loop = asyncio.get_running_loop()
        self._mem0 = await loop.run_in_executor(
            None, lambda: Memory.from_config(config)
        )
        self._initialized = True
        logger.info(
            "Mem0RAGRetriever ready — llm=%s  embedder=%s  store=qdrant-local",
            DEFAULT_MODEL,
            MEM0_EMBEDDING_MODEL,
        )

        await db.initialize()

    async def cleanup(self) -> None:
        self._mem0 = None
        self._initialized = False
        logger.info("Mem0RAGRetriever shut down.")

    # ── Document ingestion ────────────────────────────────────────────────

    async def add_document(
        self,
        content: str,
        title: str = "",
        url: str = "",
        metadata: Optional[Dict] = None,
    ) -> int:
        """Ingest a document: store in JRVS SQLite + add facts to Mem0."""
        await self.initialize()
        meta = {"url": url or "", "title": title or "", **(metadata or {})}

        # Keep the existing JRVS DB record for compatibility with the CLI,
        # search results, and Google/scraper dedup checks.
        doc_url = url or f"mem0://doc/{title or id(content)}"
        doc_id = await db.add_document(
            url=doc_url,
            title=title or url or "Untitled",
            content=content,
            content_type=(metadata or {}).get("content_type", "document"),
            metadata=meta,
        )

        # Chunk large documents so Gemma can process each piece comfortably.
        loop = asyncio.get_running_loop()
        chunks = _chunk_content(content)
        failed_chunks: list[int] = []
        for i, chunk in enumerate(chunks):
            intro = (
                f"Remember this document"
                f"{f' titled \"{title}\"' if title else ''}"
                f"{f' from {url}' if url else ''}"
                f"{f' (part {i+1})' if i > 0 else ''}:\n\n{chunk}"
            )
            messages = [{"role": "user", "content": intro}]
            chunk_meta = {**meta, "doc_id": doc_id, "chunk": i}
            try:
                await loop.run_in_executor(
                    None,
                    lambda m=messages, cm=chunk_meta: self._mem0.add(
                        m,
                        agent_id=_DOCS_AGENT_ID,
                        metadata=cm,
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "add_document doc_id=%d chunk %d/%d failed: %s",
                    doc_id, i + 1, len(chunks), exc,
                )
                failed_chunks.append(i)

        if failed_chunks:
            # Partial failure — don't mark synced; startup backfill will retry
            raise RuntimeError(
                f"doc_id={doc_id}: {len(failed_chunks)}/{len(chunks)} chunks failed to ingest"
            )

        await db.mark_document_synced(doc_id)
        self._docs_added += 1
        logger.debug("add_document doc_id=%d title=%r chunks=%d", doc_id, title, len(chunks))
        return doc_id

    async def backfill_documents(self) -> int:
        """On startup, ingest any documents that exist in SQLite but not yet in Mem0."""
        await self.initialize()
        rows = await db.get_unsynced_documents(limit=100)
        if not rows:
            return 0
        count = 0
        for row in rows:
            try:
                meta = {k: v for k, v in (row.get('metadata') or {}).items()}
                meta.setdefault('content_type', row.get('content_type', 'document'))
                await self.add_document(
                    content=row['content'],
                    title=row.get('title') or '',
                    url=row.get('url') or '',
                    metadata=meta,
                )
                count += 1
            except Exception as exc:
                logger.warning("backfill_documents skip doc_id=%s: %s", row.get('id'), exc)
        if count:
            logger.info("Backfill: ingested %d document(s) into Mem0", count)
        return count

    # ── Conversation memory ───────────────────────────────────────────────

    async def embed_conversation(
        self,
        user_message: str,
        ai_response: str,
        conversation_id: int,
        session_id: str,
    ) -> None:
        """Store a conversation turn in Mem0 and mark it embedded in the DB."""
        await self.initialize()
        messages = [
            {"role": "user",      "content": user_message},
            {"role": "assistant", "content": ai_response},
        ]
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self._mem0.add(
                    messages,
                    user_id=session_id or _DEFAULT_USER,
                    metadata={"conversation_id": conversation_id},
                ),
            )
            await db.mark_conversation_embedded(conversation_id)
        except Exception as exc:
            logger.warning(
                "embed_conversation cid=%d failed: %s", conversation_id, exc
            )

    async def embed_pending_conversations(
        self, session_id: Optional[str] = None
    ) -> int:
        """Embed unembedded conversations. If session_id is given, only that session."""
        await self.initialize()
        rows = await db.get_unembedded_conversations(limit=200)
        if not rows:
            return 0
        if session_id:
            rows = [r for r in rows if r.get('session_id') == session_id]
        if not rows:
            return 0
        count = 0
        for row in rows:
            try:
                await self.embed_conversation(
                    user_message=row["user_message"],
                    ai_response=row["ai_response"],
                    conversation_id=row["id"],
                    session_id=row.get("session_id") or session_id or _DEFAULT_USER,
                )
                count += 1
            except Exception as exc:
                logger.warning("embed_pending_conversations skip cid=%s: %s", row.get("id"), exc)
        if count:
            logger.info("Catch-up: embedded %d pending conversation(s) into Mem0", count)
        return count

    # ── Retrieval ─────────────────────────────────────────────────────────

    async def retrieve_context(
        self, query: str, session_id: Optional[str] = None,
        max_length: Optional[int] = None,
    ) -> str:
        """
        Search Mem0 for relevant document facts and conversation memories,
        then format them as a context string for the LLM system prompt.
        """
        await self.initialize()
        loop = asyncio.get_running_loop()

        # Search document knowledge base (agent-scoped)
        doc_task = loop.run_in_executor(
            None,
            lambda: self._mem0.search(query, agent_id=_DOCS_AGENT_ID, limit=5),
        )
        # Search this session's conversation memories (user-scoped)
        conv_task = loop.run_in_executor(
            None,
            lambda: self._mem0.search(
                query,
                user_id=session_id or _DEFAULT_USER,
                limit=5,
            ),
        )

        try:
            doc_raw, conv_raw = await asyncio.gather(doc_task, conv_task)
        except Exception as exc:
            logger.error("retrieve_context search failed: %s", exc)
            return ""

        context = _format_context(doc_raw, conv_raw)
        limit = max_length if max_length is not None else MAX_CONTEXT_LENGTH
        if len(context) > limit:
            context = context[:limit] + "\n\n[… context truncated …]"
        return context

    async def search_documents(
        self, query: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search the document knowledge base; returns list matching existing schema."""
        await self.initialize()
        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(
                None,
                lambda: self._mem0.search(query, agent_id=_DOCS_AGENT_ID, limit=limit),
            )
        except Exception as exc:
            logger.error("search_documents failed: %s", exc)
            return []

        results = []
        for r in _results_list(raw):
            mem  = r.get("memory", "")
            meta = r.get("metadata") or {}
            results.append(
                {
                    "document_id": meta.get("doc_id", r.get("id", "")),
                    "title":       meta.get("title", ""),
                    "url":         meta.get("url", ""),
                    "similarity":  float(r.get("score", 0.0)),
                    "preview":     (mem[:200] + "…") if len(mem) > 200 else mem,
                }
            )
        return results

    async def get_stats(self) -> Dict[str, Any]:
        """Return stats in a format compatible with existing callers."""
        await self.initialize()
        loop = asyncio.get_running_loop()
        try:
            all_mems = await loop.run_in_executor(
                None,
                lambda: self._mem0.get_all(agent_id=_DOCS_AGENT_ID, limit=100000),
            )
            total = len(_results_list(all_mems))
        except Exception:
            total = -1

        return {
            # Nested under "vector_store" so mcp/health.py's
            # stats.get("vector_store", {}).get("total_vectors", 0) still works.
            "vector_store": {
                "total_vectors": total,
                "type": "qdrant-local (mem0)",
            },
            "backend":          "mem0",
            "llm":              DEFAULT_MODEL,
            "embedder":         MEM0_EMBEDDING_MODEL,
            "documents_added":  self._docs_added,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _results_list(raw) -> list:
    """Normalise Mem0 search / get_all return value to a plain list."""
    if isinstance(raw, dict):
        return raw.get("results", [])
    return raw or []


def _format_context(doc_raw, conv_raw) -> str:
    """
    Format Mem0 search results as the context string that gets injected into
    the LLM system prompt — matching the shape produced by RAGRetriever.
    """
    parts: List[str] = []

    docs  = _results_list(doc_raw)
    convs = _results_list(conv_raw)

    if docs:
        lines = ["Relevant knowledge:"]
        for r in docs:
            mem  = r.get("memory", "").strip()
            meta = r.get("metadata") or {}
            title = meta.get("title", "")
            url   = meta.get("url", "")
            label = f"[{title}]" if title else ""
            if url:
                label += f" ({url})"
            lines.append(f"{label}:\n{mem}" if label else mem)
        parts.append("\n\n".join(lines))

    if convs:
        lines = ["Relevant past conversations:"]
        for r in convs:
            mem = r.get("memory", "").strip()
            if mem:
                lines.append(mem)
        parts.append("\n\n".join(lines))

    return "\n\n".join(parts)
