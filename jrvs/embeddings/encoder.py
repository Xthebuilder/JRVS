"""
Lean sentence-transformer encoder for JRVS core.

torch and sentence_transformers are imported lazily — this module is
safe to import even if neither package is installed (FAISS-only code
paths will still work; embed calls will raise a clear error).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


class EmbeddingEncoder:
    """Encode text → dense float32 vectors using sentence-transformers."""

    _instance: "EmbeddingEncoder | None" = None

    def __init__(self) -> None:
        from jrvs.config import Config
        Config.ensure_dirs()

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed.\n"
                "Run: pip install sentence-transformers"
            ) from exc

        device = Config.DEVICE
        self.model = SentenceTransformer(
            Config.EMBEDDING_MODEL,
            device=device,
            cache_folder=str(Config.MODEL_CACHE),
        )
        # fp16 on CUDA to save VRAM
        if device == "cuda" and Config.HALF_PRECISION:
            try:
                self.model.half()
            except Exception:
                pass

    @classmethod
    def get(cls) -> "EmbeddingEncoder":
        """Singleton — load once, reuse."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def encode(
        self,
        texts: Sequence[str],
        batch_size: int | None = None,
        show_progress: bool = False,
    ) -> np.ndarray:
        from jrvs.config import Config
        batch_size = batch_size or Config.EMBEDDING_BATCH_SIZE
        vecs = self.model.encode(
            list(texts),
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vecs.astype(np.float32)

    def encode_single(self, text: str) -> np.ndarray:
        return self.encode([text])[0]

    @property
    def dim(self) -> int:
        from jrvs.config import Config
        return Config.EMBEDDING_DIM
