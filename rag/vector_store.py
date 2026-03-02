"""FAISS-based vector store with SQLite-backed map, HNSW auto-upgrade, and cosine similarity"""
import asyncio
import json
import os
import pickle
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np

from config import (
    VECTOR_INDEX_PATH,
    TIMEOUTS,
    MAX_RETRIEVED_CHUNKS,
    SIMILARITY_THRESHOLD,
    HNSW_UPGRADE_THRESHOLD,
)
from .embeddings import embedding_manager


class VectorStore:
    def __init__(self, index_path: str = str(VECTOR_INDEX_PATH)):
        self.index_path = index_path
        self.index = None
        self.dimension = 768          # updated after model loads
        self.document_map: Dict = {}  # in-memory write-through cache; persisted to SQLite
        self.is_initialized = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def initialize(self):
        async with self._lock:
            if self.is_initialized:
                return
            await self._load_or_create_index()
            self.is_initialized = True

    async def _load_or_create_index(self):
        index_file = f"{self.index_path}.index"
        map_file   = f"{self.index_path}.map"   # legacy pickle path

        if os.path.exists(index_file):
            await self._load_index(index_file, map_file)
        else:
            await self._create_new_index()

    async def _load_index(self, index_file: str, map_file: str):
        """Load FAISS index from disk, migrate pickle map → SQLite if needed."""
        try:
            loop = asyncio.get_event_loop()
            self.index = await loop.run_in_executor(
                None, faiss.read_index, index_file
            )
            self.dimension = self.index.d

            # --- Dimension compatibility check ---
            # If the stored index was built with the old embedding model (e.g. 384-dim
            # MiniLM) but the configured model produces 768-dim vectors, we must
            # rebuild the index rather than silently corrupt it.
            await embedding_manager.initialize()
            expected_dim = embedding_manager.get_embedding_dimension()
            if self.index.d != expected_dim:
                print(
                    f"[VectorStore] Dimension mismatch — stored={self.index.d}, "
                    f"model={expected_dim}. Rebuilding index with new model."
                )
                await self._create_new_index()
                await self._clear_db_map()
                return

            # --- Load document map from SQLite (with pickle migration) ---
            from core.database import db
            await db.initialize()
            self.document_map = await db.load_vector_map()

            if not self.document_map and os.path.exists(map_file):
                print("[VectorStore] Migrating document map from pickle → SQLite…")
                try:
                    with open(map_file, 'rb') as f:
                        legacy_map = pickle.load(f)

                    entries = [
                        (
                            idx,
                            info['text'],
                            json.dumps(info['metadata']),
                            info.get('added_at', time.time()),
                        )
                        for idx, info in legacy_map.items()
                    ]
                    await db.save_vector_map_batch(entries)
                    self.document_map = legacy_map

                    # Keep pickle as a backup so users can roll back
                    os.rename(map_file, map_file + '.bak')
                    print(f"[VectorStore] Migrated {len(legacy_map)} entries to SQLite "
                          f"(old pickle saved as {map_file}.bak)")
                except Exception as e:
                    print(f"[VectorStore] Pickle migration failed: {e}")

            print(f"[VectorStore] Loaded {self.index.ntotal} vectors "
                  f"({len(self.document_map)} map entries, dim={self.dimension})")

        except Exception as e:
            print(f"[VectorStore] Error loading index: {e}")
            await self._create_new_index()

    async def _create_new_index(self):
        """Create a fresh flat inner-product index (cosine sim after normalisation)."""
        await embedding_manager.initialize()
        self.dimension = embedding_manager.get_embedding_dimension()
        self.index = faiss.IndexFlatIP(self.dimension)
        self.document_map = {}
        print(f"[VectorStore] Created new IndexFlatIP (dim={self.dimension})")

    # ------------------------------------------------------------------
    # Insertion
    # ------------------------------------------------------------------

    async def add_documents(self, texts: List[str], metadata: List[Dict]):
        await self.initialize()
        if not texts:
            return

        start_time = time.time()
        from core.database import db

        try:
            # Embed + L2-normalise (converts IP → cosine similarity)
            embeddings = await embedding_manager.encode_text(texts, is_query=False)
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            embeddings = (embeddings / norms).astype(np.float32)

            start_idx = self.index.ntotal
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.index.add, embeddings)

            # Update in-memory map and persist to SQLite in one batch
            now = time.time()
            batch: List[Tuple] = []
            for i, meta in enumerate(metadata):
                faiss_idx = start_idx + i
                self.document_map[faiss_idx] = {
                    'text':     texts[i],
                    'metadata': meta,
                    'added_at': now,
                }
                batch.append((faiss_idx, texts[i], json.dumps(meta), now))

            await db.save_vector_map_batch(batch)

            # Save FAISS binary periodically
            if self.index.ntotal % 10 == 0:
                await self._save_index()

            # Auto-upgrade to HNSW when we hit the threshold
            await self._maybe_upgrade_to_hnsw()

            elapsed = time.time() - start_time
            print(f"[VectorStore] Added {len(texts)} vectors in {elapsed:.2f}s "
                  f"(total={self.index.ntotal})")

        except Exception as e:
            print(f"[VectorStore] Error adding documents: {e}")

    async def add_chunks(self, chunks: List[str], document_id: int,
                         chunk_metadata: List[Dict] = None):
        if not chunks:
            return
        if chunk_metadata is None:
            chunk_metadata = [
                {'document_id': document_id, 'chunk_index': i}
                for i in range(len(chunks))
            ]
        for meta in chunk_metadata:
            meta['document_id'] = document_id
        await self.add_documents(chunks, chunk_metadata)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        k: int = MAX_RETRIEVED_CHUNKS,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> List[Tuple[str, float, Dict]]:
        """
        Semantic similarity search.

        Parameters
        ----------
        query     : natural-language query string
        k         : maximum number of results to return
        threshold : minimum cosine similarity to include a result.
                    Pass 0.0 to disable filtering (useful for hybrid search + RRF).
        """
        await self.initialize()
        if self.index.ntotal == 0:
            return []

        start_time = time.time()
        try:
            # Embed query with the retrieval prefix (BGE etc.)
            q_emb = await embedding_manager.encode_text([query], is_query=True)
            q_emb = q_emb / np.linalg.norm(q_emb)

            loop = asyncio.get_event_loop()
            similarities, indices = await loop.run_in_executor(
                None,
                self.index.search,
                q_emb.astype(np.float32),
                min(k, self.index.ntotal),
            )

            results = []
            for sim, idx in zip(similarities[0], indices[0]):
                if sim >= threshold and idx in self.document_map:
                    doc_info = self.document_map[idx]
                    results.append((doc_info['text'], float(sim), doc_info['metadata']))

            elapsed = time.time() - start_time
            if elapsed > TIMEOUTS["vector_search"]:
                print(f"[VectorStore] Warning: search took {elapsed:.2f}s")

            return results

        except Exception as e:
            print(f"[VectorStore] Error searching: {e}")
            return []

    # ------------------------------------------------------------------
    # HNSW auto-upgrade
    # ------------------------------------------------------------------

    async def _maybe_upgrade_to_hnsw(self):
        """
        Automatically migrate from IndexFlatIP to IndexHNSWFlat when the vector
        count crosses HNSW_UPGRADE_THRESHOLD.

        HNSW (Hierarchical Navigable Small World) is an approximate nearest-
        neighbour index that stays sub-linear in search time while keeping very
        high recall (typically >98 % with the defaults chosen here).
        Vectors are already L2-normalised, so inner product == cosine similarity.
        """
        if not isinstance(self.index, faiss.IndexFlatIP):
            return  # already HNSW or some other index type
        if self.index.ntotal < HNSW_UPGRADE_THRESHOLD:
            return

        print(f"[VectorStore] Upgrading to HNSW at {self.index.ntotal} vectors…")
        try:
            # M=32: each node connected to 32 neighbours (good recall/speed tradeoff)
            # efConstruction=200: high-quality graph build
            hnsw = faiss.IndexHNSWFlat(self.dimension, 32)
            hnsw.hnsw.efConstruction = 200
            hnsw.hnsw.efSearch = 64   # raised at query time for better recall

            # Extract all vectors from the flat index
            loop = asyncio.get_event_loop()
            all_vectors = await loop.run_in_executor(
                None,
                lambda: self.index.reconstruct_n(0, self.index.ntotal),
            )
            await loop.run_in_executor(None, hnsw.add, all_vectors.astype(np.float32))

            self.index = hnsw
            await self._save_index()
            print(f"[VectorStore] HNSW upgrade complete — {hnsw.ntotal} vectors indexed.")
        except Exception as e:
            print(f"[VectorStore] HNSW upgrade failed (staying on flat): {e}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _save_index(self):
        """Save only the FAISS binary. The document map is persisted incrementally to SQLite."""
        if not self.index:
            return
        try:
            Path(self.index_path).parent.mkdir(parents=True, exist_ok=True)
            index_file = f"{self.index_path}.index"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, faiss.write_index, self.index, index_file)
            print(f"[VectorStore] Saved FAISS index ({self.index.ntotal} vectors)")
        except Exception as e:
            print(f"[VectorStore] Error saving index: {e}")

    async def _clear_db_map(self):
        """Clear SQLite vector_map (called when rebuilding the index)."""
        try:
            from core.database import db
            await db.initialize()
            await db.clear_vector_map()
        except Exception as e:
            print(f"[VectorStore] Error clearing vector map: {e}")

    # ------------------------------------------------------------------
    # Document removal
    # ------------------------------------------------------------------

    async def search_by_document_id(
        self, document_id: int, k: int = MAX_RETRIEVED_CHUNKS
    ) -> List[Tuple[str, Dict]]:
        await self.initialize()
        results = [
            (info['text'], info['metadata'])
            for info in self.document_map.values()
            if info['metadata'].get('document_id') == document_id
        ]
        results.sort(key=lambda x: x[1].get('chunk_index', 0))
        return results[:k]

    async def remove_document(self, document_id: int):
        """Remove all chunks for a document by rebuilding the index without them."""
        await self.initialize()
        from core.database import db

        indices_to_remove = [
            idx for idx, info in self.document_map.items()
            if info['metadata'].get('document_id') == document_id
        ]
        if not indices_to_remove:
            return

        remaining_texts = []
        remaining_metadata = []
        for idx, info in self.document_map.items():
            if idx not in indices_to_remove:
                remaining_texts.append(info['text'])
                remaining_metadata.append(info['metadata'])

        await self._create_new_index()
        await self._clear_db_map()
        self.document_map = {}

        if remaining_texts:
            await self.add_documents(remaining_texts, remaining_metadata)

        await self._save_index()
        print(f"[VectorStore] Removed document {document_id} and rebuilt index.")

    # ------------------------------------------------------------------
    # Stats / cleanup
    # ------------------------------------------------------------------

    async def get_stats(self) -> Dict:
        await self.initialize()
        index_file = f"{self.index_path}.index"
        return {
            'total_vectors':  self.index.ntotal if self.index else 0,
            'dimension':      self.dimension,
            'index_type':     type(self.index).__name__ if self.index else 'none',
            'index_size_mb':  (
                os.path.getsize(index_file) / 1024 / 1024
                if os.path.exists(index_file) else 0
            ),
            'documents_count': len({
                info['metadata'].get('document_id', -1)
                for info in self.document_map.values()
            }) if self.document_map else 0,
        }

    async def cleanup(self):
        if self.index:
            await self._save_index()


# Global vector store instance
vector_store = VectorStore()
