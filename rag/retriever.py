"""
RAG retriever — full pipeline:
  Hybrid search (FAISS + FTS5 via RRF)
  → Cross-encoder re-ranking
  → Maximal Marginal Relevance (MMR) diversity selection
  → Context formatting + smart truncation
"""
import asyncio
import re
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import (
    MAX_CONTEXT_LENGTH,
    MAX_RETRIEVED_CHUNKS,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    TIMEOUTS,
    MMR_LAMBDA,
    RERANK_CANDIDATES,
    SIMILARITY_THRESHOLD,
)
from .vector_store import vector_store
from .embeddings import embedding_manager
from .reranker import reranker
from core.database import db


class RAGRetriever:
    def __init__(self):
        self.initialized = False

    async def initialize(self):
        if self.initialized:
            return
        await db.initialize()
        await vector_store.initialize()
        await embedding_manager.initialize()
        self.initialized = True

    # ------------------------------------------------------------------
    # Document ingestion (unchanged API)
    # ------------------------------------------------------------------

    async def add_document(self, content: str, title: str = "", url: str = "",
                           metadata: Dict = None) -> int:
        await self.initialize()
        if metadata is None:
            metadata = {}

        document_id = await db.add_document(
            url=url, title=title, content=content,
            content_type='text', metadata=metadata,
        )
        chunks = self._chunk_text(content)

        chunk_ids = []
        for i, chunk in enumerate(chunks):
            chunk_id = await db.add_document_chunk(document_id, chunk, i)
            chunk_ids.append(chunk_id)

        chunk_metadata = [
            {
                'type': 'document',
                'document_id': document_id,
                'chunk_index': i,
                'chunk_id': chunk_ids[i],
                'title': title,
                'url': url,
            }
            for i in range(len(chunks))
        ]
        await vector_store.add_chunks(chunks, document_id, chunk_metadata)
        print(f"Added document '{title}' with {len(chunks)} chunks")
        return document_id

    # ------------------------------------------------------------------
    # Conversation embedding
    # ------------------------------------------------------------------

    async def embed_conversation(self, user_message: str, ai_response: str,
                                 conversation_id: int, session_id: str) -> None:
        await self.initialize()
        try:
            conversation_text = f"User: {user_message}\nJRVS: {ai_response}"
            metadata = {
                'type': 'conversation',
                'conversation_id': conversation_id,
                'session_id': session_id,
                'document_id': -1,
                'title': 'Past conversation',
                'url': '',
            }
            await vector_store.add_documents([conversation_text], [metadata])
            await db.mark_conversation_embedded(conversation_id)
        except Exception as e:
            print(f"[RAG] Failed to embed conversation {conversation_id}: {e}")

    async def embed_pending_conversations(self, session_id: str = None) -> int:
        await self.initialize()
        unembedded = await db.get_unembedded_conversations(limit=200)
        count = 0
        for conv in unembedded:
            await self.embed_conversation(
                user_message=conv['user_message'],
                ai_response=conv['ai_response'],
                conversation_id=conv['id'],
                session_id=conv['session_id'],
            )
            count += 1
        if count:
            print(f"[RAG] Catch-up: embedded {count} pending conversation(s) into FAISS")
        return count

    # ------------------------------------------------------------------
    # Main retrieval pipeline
    # ------------------------------------------------------------------

    async def retrieve_context(self, query: str, session_id: str = None) -> str:
        """
        Full retrieval pipeline:
          1. Hybrid search  — FAISS (semantic) + FTS5 (keyword) fused via RRF
          2. Cross-encoder  — re-rank top candidates for genuine relevance
          3. MMR            — select diverse final set (no redundant chunks)
          4. Format + truncate

        Returns a context string ready to inject into the LLM prompt.
        """
        await self.initialize()
        start_time = time.time()

        try:
            # ── 1. Broad hybrid candidate retrieval ──────────────────────────
            candidates = await self._hybrid_search(query, k=RERANK_CANDIDATES)
            if not candidates:
                return ""

            # ── 2. Split by type ─────────────────────────────────────────────
            conv_candidates = [c for c in candidates if c[2].get('type') == 'conversation']
            doc_candidates  = [c for c in candidates if c[2].get('type') != 'conversation']

            # ── 3. Cross-encoder re-rank documents ───────────────────────────
            if doc_candidates:
                doc_candidates = await reranker.rerank(
                    query, doc_candidates,
                    top_k=min(len(doc_candidates), MAX_RETRIEVED_CHUNKS * 2),
                )

            # ── 4. MMR — balance relevance vs diversity ───────────────────────
            if doc_candidates:
                doc_candidates = await self._apply_mmr(
                    query, doc_candidates, k=MAX_RETRIEVED_CHUNKS
                )
            if conv_candidates:
                conv_candidates = await self._apply_mmr(
                    query, conv_candidates, k=MAX_RETRIEVED_CHUNKS
                )

            # ── 5. Format ────────────────────────────────────────────────────
            context_parts = []
            if conv_candidates:
                formatted = self._format_conversation_context_semantic(conv_candidates)
                if formatted:
                    context_parts.append(f"Relevant past conversations:\n{formatted}")
            if doc_candidates:
                formatted = self._format_document_context(doc_candidates)
                if formatted:
                    context_parts.append(f"Relevant knowledge:\n{formatted}")

            full_context = "\n\n".join(context_parts)
            if len(full_context) > MAX_CONTEXT_LENGTH:
                full_context = self._smart_truncate(full_context, MAX_CONTEXT_LENGTH)

            elapsed = time.time() - start_time
            if elapsed > TIMEOUTS["context_building"]:
                print(f"[RAG] Warning: context building took {elapsed:.2f}s")

            return full_context

        except Exception as e:
            print(f"[RAG] Error retrieving context: {e}")
            return ""

    # ------------------------------------------------------------------
    # Hybrid search — FAISS + FTS5 via Reciprocal Rank Fusion
    # ------------------------------------------------------------------

    async def _hybrid_search(
        self, query: str, k: int
    ) -> List[Tuple[str, float, Dict]]:
        """
        Run FAISS semantic search and SQLite FTS5 keyword search in parallel,
        then merge their ranked lists using Reciprocal Rank Fusion (RRF).

        RRF score = Σ  1 / (K + rank_i)
        where K=60 is the standard smoothing constant that prevents very
        high-ranked results from dominating too much.

        This handles two failure modes in isolation:
          - FAISS: struggles with exact token matches (model hasn't seen the term)
          - FTS5:  struggles with semantic equivalences ('repair' vs 'fix')
        Together they cover both.
        """
        K_RRF = 60

        # Threshold=0.0 — we want full candidate pool; cross-encoder handles quality
        faiss_task = asyncio.create_task(
            vector_store.search(query, k=k, threshold=0.0)
        )
        fts_task = asyncio.create_task(
            db.fts_search_chunks(query, limit=k)
        )
        faiss_results, fts_results = await asyncio.gather(faiss_task, fts_task)

        scores: Dict[Tuple, float] = {}
        result_map: Dict[Tuple, Tuple[str, float, Dict]] = {}

        # Score FAISS results
        for rank, (text, sim, meta) in enumerate(faiss_results):
            doc_id    = meta.get('document_id', -1)
            chunk_idx = meta.get('chunk_index', hash(text) % 999_999)
            key = (doc_id, chunk_idx)
            scores[key]     = scores.get(key, 0.0) + 1.0 / (K_RRF + rank + 1)
            result_map[key] = (text, sim, meta)

        # Score FTS5 results
        for rank, row in enumerate(fts_results):
            key = (row['document_id'], row['chunk_index'])
            scores[key] = scores.get(key, 0.0) + 1.0 / (K_RRF + rank + 1)
            if key not in result_map:
                result_map[key] = (
                    row['chunk_text'],
                    0.0,
                    {
                        'type':       'document',
                        'document_id': row['document_id'],
                        'chunk_index': row['chunk_index'],
                        'title':      row.get('title', ''),
                        'url':        row.get('url', ''),
                    },
                )

        # Sort by combined RRF score (descending)
        sorted_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
        return [
            (result_map[k][0], scores[k], result_map[k][2])
            for k in sorted_keys[:k]
        ]

    # ------------------------------------------------------------------
    # MMR — Maximal Marginal Relevance
    # ------------------------------------------------------------------

    async def _apply_mmr(
        self,
        query: str,
        candidates: List[Tuple[str, float, Dict]],
        k: int,
    ) -> List[Tuple[str, float, Dict]]:
        """
        Select k results that are both relevant *and* diverse.

        At each step, MMR picks the candidate that maximises:
            λ * relevance(d, query)  −  (1−λ) * max_sim(d, already_selected)

        λ = MMR_LAMBDA (default 0.7) tilts toward relevance; lower values
        prioritise diversity.  This prevents the LLM from seeing five chunks
        that all say the same thing.
        """
        if len(candidates) <= k:
            return candidates

        # Embed query + all candidate texts (cached, so fast for repeat queries)
        texts = [c[0] for c in candidates]
        q_emb_arr  = await embedding_manager.encode_text([query], is_query=True)
        doc_embs   = await embedding_manager.encode_text(texts, is_query=False)

        # L2-normalise so dot product == cosine similarity
        def _norm(v: np.ndarray) -> np.ndarray:
            n = np.linalg.norm(v)
            return v / n if n > 0 else v

        q_emb    = _norm(q_emb_arr[0])
        doc_embs = np.array([_norm(e) for e in doc_embs])

        selected: List[int] = []
        remaining = list(range(len(candidates)))

        while len(selected) < k and remaining:
            if not selected:
                # Bootstrap: pick the highest-scored candidate
                best = max(remaining, key=lambda i: candidates[i][1])
            else:
                best_score = float('-inf')
                best = remaining[0]
                for i in remaining:
                    relevance = candidates[i][1]
                    max_sim_to_selected = max(
                        float(np.dot(doc_embs[i], doc_embs[j]))
                        for j in selected
                    )
                    score = MMR_LAMBDA * relevance - (1 - MMR_LAMBDA) * max_sim_to_selected
                    if score > best_score:
                        best_score = score
                        best = i

            selected.append(best)
            remaining.remove(best)

        return [candidates[i] for i in selected]

    # ------------------------------------------------------------------
    # Document / stats search (unchanged API)
    # ------------------------------------------------------------------

    async def search_documents(self, query: str, limit: int = 5) -> List[Dict]:
        """Search for documents by content (uses SIMILARITY_THRESHOLD)."""
        await self.initialize()
        search_results = await vector_store.search(query, k=limit)

        if search_results:
            doc_results = {}
            for text, similarity, metadata in search_results:
                if metadata.get('type') == 'conversation':
                    continue
                doc_id = metadata.get('document_id')
                if doc_id and doc_id not in doc_results:
                    doc_results[doc_id] = {
                        'document_id': doc_id,
                        'title':       metadata.get('title', 'Untitled'),
                        'url':         metadata.get('url', ''),
                        'similarity':  similarity,
                        'preview':     text[:200] + "..." if len(text) > 200 else text,
                    }
            if doc_results:
                return list(doc_results.values())

        db_results = await db.get_documents_by_query(query, limit)
        return [
            {
                'document_id': doc['id'],
                'title':       doc['title'],
                'url':         doc['url'],
                'similarity':  0.0,
                'preview':     doc['content'][:200] + "..." if len(doc['content']) > 200 else doc['content'],
            }
            for doc in db_results
        ]

    async def get_stats(self) -> Dict:
        await self.initialize()
        vector_stats = await vector_store.get_stats()
        return {
            'vector_store':        vector_stats,
            'embedding_cache_size': embedding_manager.get_cache_size(),
            'embedding_dimension': embedding_manager.get_embedding_dimension(),
        }

    async def cleanup(self):
        await vector_store.cleanup()

    # ------------------------------------------------------------------
    # Context formatters
    # ------------------------------------------------------------------

    def _smart_truncate(self, text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        truncated = text[:max_len]
        boundary  = truncated.rfind('\n\n')
        if boundary > max_len // 2:
            return truncated[:boundary] + "\n\n[… context truncated …]"
        return truncated + "…"

    def _format_conversation_context_semantic(
        self, results: List[Tuple[str, float, Dict]]
    ) -> str:
        if not results:
            return ""
        seen = set()
        parts = []
        for text, _, metadata in results:
            conv_id = metadata.get('conversation_id', id(text))
            if conv_id in seen:
                continue
            seen.add(conv_id)
            parts.append(text.strip())
        return "\n\n---\n\n".join(parts)

    def _format_document_context(self, results: List[Tuple[str, float, Dict]]) -> str:
        if not results:
            return ""
        parts = []
        seen  = set()
        for text, _, metadata in results:
            doc_key = (metadata.get('document_id'), metadata.get('chunk_index', 0))
            if doc_key in seen:
                continue
            seen.add(doc_key)

            title = metadata.get('title', 'Document')
            url   = metadata.get('url', '')
            piece = f"[{title}]"
            if url:
                piece += f" ({url})"
            piece += f":\n{text.strip()}"
            parts.append(piece)

        return '\n\n'.join(parts)

    # ------------------------------------------------------------------
    # Chunking — character-based with sentence-boundary splits
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str) -> List[str]:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks: List[str] = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(current_chunk) + len(sentence) + 1 > CHUNK_SIZE:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    if len(current_chunk) > CHUNK_OVERLAP:
                        overlap = current_chunk[-CHUNK_OVERLAP:]
                        sp = overlap.find(' ')
                        if sp > 0:
                            overlap = overlap[sp + 1:]
                        current_chunk = overlap + ' ' + sentence
                    else:
                        current_chunk = sentence
                else:
                    for i in range(0, len(sentence), CHUNK_SIZE - CHUNK_OVERLAP):
                        chunks.append(sentence[i:i + CHUNK_SIZE])
                    current_chunk = ""
            else:
                current_chunk += (' ' + sentence) if current_chunk else sentence

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return [c for c in chunks if c.strip()]


# Global RAG retriever instance
rag_retriever = RAGRetriever()
