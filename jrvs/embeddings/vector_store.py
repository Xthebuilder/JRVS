"""
FAISS-based vector store for JRVS.

Provides GPU-accelerated (when available) approximate nearest-neighbour
search over video embeddings.  Each channel gets its own index persisted
to disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from jrvs.config import Config

# Try GPU-accelerated FAISS first, fall back to CPU
try:
    import faiss                # type: ignore
    _FAISS_GPU = hasattr(faiss, "index_cpu_to_all_gpus")
except ImportError:
    faiss = None
    _FAISS_GPU = False


class VectorStore:
    """Manage per-channel FAISS indexes for semantic search."""

    def __init__(self, namespace: str = "default") -> None:
        Config.ensure_dirs()
        self._ns = namespace
        self._index_path = Config.FAISS_INDEX_DIR / f"{namespace}.index"
        self._meta_path = Config.FAISS_INDEX_DIR / f"{namespace}.meta.json"
        self._index: Any | None = None
        self._metadata: list[dict[str, Any]] = []
        self._load()

    # ── public API ──────────────────────────────────────────────────────
    def add(
        self,
        vectors: np.ndarray,
        metadata: list[dict[str, Any]],
    ) -> None:
        """Add *vectors* (N, dim) with associated *metadata* to the index."""
        if faiss is None:
            raise RuntimeError("faiss is not installed – pip install faiss-gpu or faiss-cpu")

        dim = vectors.shape[1]
        if self._index is None:
            self._index = faiss.IndexFlatIP(dim)  # inner-product (cosine on normalised)
            if Config.DEVICE == "cuda" and _FAISS_GPU:
                self._index = faiss.index_cpu_to_all_gpus(self._index)

        self._index.add(vectors)
        self._metadata.extend(metadata)
        self._save()

    def search(
        self,
        query_vec: np.ndarray,
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """Return the *k* nearest neighbours for *query_vec* (dim,)."""
        if self._index is None or self._index.ntotal == 0:
            return []
        query_vec = query_vec.reshape(1, -1).astype(np.float32)
        distances, indices = self._index.search(query_vec, min(k, self._index.ntotal))
        results: list[dict[str, Any]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            results.append({**self._metadata[idx], "score": float(dist)})
        return results

    def rebuild(
        self,
        vectors: np.ndarray,
        metadata: list[dict[str, Any]],
    ) -> None:
        """Replace the entire index."""
        self._index = None
        self._metadata = []
        self.add(vectors, metadata)

    @property
    def size(self) -> int:
        return self._index.ntotal if self._index else 0

    # ── persistence ─────────────────────────────────────────────────────
    def _save(self) -> None:
        if self._index is None or faiss is None:
            return
        # Copy to CPU for serialisation if on GPU
        cpu_index = faiss.index_gpu_to_cpu(self._index) if (
            Config.DEVICE == "cuda" and _FAISS_GPU
        ) else self._index
        faiss.write_index(cpu_index, str(self._index_path))
        self._meta_path.write_text(json.dumps(self._metadata, default=str))

    def _load(self) -> None:
        if faiss is None:
            return
        if self._index_path.exists():
            self._index = faiss.read_index(str(self._index_path))
            if Config.DEVICE == "cuda" and _FAISS_GPU:
                self._index = faiss.index_cpu_to_all_gpus(self._index)
        if self._meta_path.exists():
            self._metadata = json.loads(self._meta_path.read_text())
