"""Embeddings generation using sentence-transformers"""
import asyncio
import hashlib
import logging
import numpy as np
from typing import List, Union
from sentence_transformers import SentenceTransformer
import torch
import time
from config import EMBEDDING_BATCH_SIZE, TIMEOUTS, EMBEDDING_MODEL

log = logging.getLogger(__name__)


class EmbeddingManager:
    def __init__(self, model_name: str = EMBEDDING_MODEL):
        self.model_name = model_name
        self._model = None
        self._device = None
        self._embedding_cache = {}
        self._max_cache_size = 1000

        # BGE models expect a retrieval instruction prepended to *queries only*
        # (not to corpus documents). Other models leave this empty.
        if "bge" in model_name.lower():
            self._query_prefix = "Represent this sentence for searching relevant passages: "
        else:
            self._query_prefix = ""

    async def initialize(self):
        """Lazy initialization of the embedding model"""
        if self._model is None:
            await self._load_model()

    async def _load_model(self):
        """Load the sentence transformer model in a thread pool"""
        loop = asyncio.get_running_loop()

        def _load():
            import os, logging
            # Silence HuggingFace download progress bars and load-report noise
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            # Suppress the verbose BertModel LOAD REPORT printed to stdout
            logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
            logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
            logging.getLogger("transformers").setLevel(logging.ERROR)

            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            self._device = device
            # show_progress_bar=False suppresses the tqdm download/encode bars
            model = SentenceTransformer(
                self.model_name,
                device=device,
                # Disables the "Loading weights" / "BertModel LOAD REPORT" stdout dump
            )
            model.show_progress_bar = False
            return model

        self._model = await loop.run_in_executor(None, _load)
        dim = self._model.get_sentence_embedding_dimension()
        log.info("Loaded embedding model '%s' (dim=%d, device=%s)",
                 self.model_name, dim, self._device)

    # ------------------------------------------------------------------
    # Core encode method
    # ------------------------------------------------------------------

    async def encode_text(
        self,
        text: Union[str, List[str]],
        batch_size: int = EMBEDDING_BATCH_SIZE,
        is_query: bool = False,
    ) -> np.ndarray:
        """
        Generate embeddings for one or more texts.

        Parameters
        ----------
        text      : str or list of str to embed
        batch_size: mini-batch size for the model
        is_query  : if True, apply the model's retrieval query prefix (BGE etc.)
                    Set this when embedding user queries, not when embedding documents.
        """
        await self.initialize()

        if isinstance(text, str):
            text = [text]

        # Apply query prefix for models that need it
        if is_query and self._query_prefix:
            prefixed = [self._query_prefix + t for t in text]
        else:
            prefixed = text

        # --- Cache lookup ---
        # Use SHA-256 prefix as cache key to avoid Python hash() collisions
        cached_embeddings = []
        uncached_texts = []
        uncached_indices = []

        for i, t in enumerate(prefixed):
            cache_key = hashlib.sha256(t.encode()).hexdigest()[:16]
            if cache_key in self._embedding_cache:
                cached_embeddings.append((i, self._embedding_cache[cache_key]))
            else:
                uncached_texts.append((t, cache_key))
                uncached_indices.append(i)

        # --- Generate embeddings for cache misses ---
        new_embeddings = []
        if uncached_texts:
            raw_texts = [t for t, _ in uncached_texts]
            cache_keys = [k for _, k in uncached_texts]
            try:
                start_time = time.time()
                all_new = []
                for i in range(0, len(raw_texts), batch_size):
                    batch = raw_texts[i:i + batch_size]
                    loop = asyncio.get_running_loop()
                    batch_embs = await loop.run_in_executor(
                        None,
                        lambda b=batch: self._model.encode(b, convert_to_numpy=True, show_progress_bar=False),
                    )
                    all_new.extend(batch_embs)

                # Cache new results
                for key, emb in zip(cache_keys, all_new):
                    self._embedding_cache[key] = emb

                # Evict oldest entries when cache is full
                if len(self._embedding_cache) > self._max_cache_size:
                    items = list(self._embedding_cache.items())
                    for k, _ in items[: len(items) - self._max_cache_size + 100]:
                        del self._embedding_cache[k]

                new_embeddings = all_new

                elapsed = time.time() - start_time
                if elapsed > TIMEOUTS["embedding_generation"]:
                    log.warning("Embedding generation slow: %.2fs (threshold %ss)",
                                elapsed, TIMEOUTS["embedding_generation"])

            except Exception as e:
                log.error("Error generating embeddings: %s", e)
                dim = self.get_embedding_dimension()
                return np.zeros((len(text), dim))

        # --- Reassemble in original order ---
        final = [None] * len(text)
        for idx, emb in cached_embeddings:
            final[idx] = emb
        for i, idx in enumerate(uncached_indices):
            if i < len(new_embeddings):
                final[idx] = new_embeddings[i]

        return np.array(final)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def encode_chunks(self, chunks: List[str]) -> List[np.ndarray]:
        """Generate embeddings for document chunks (not queries)."""
        if not chunks:
            return []
        embeddings = await self.encode_text(chunks, is_query=False)
        return [embeddings[i] for i in range(len(chunks))]

    def get_embedding_dimension(self) -> int:
        if self._model:
            return self._model.get_sentence_embedding_dimension()
        # Rough default — will be corrected after model loads
        return 768

    async def similarity(self, text1: str, text2: str) -> float:
        """Cosine similarity between two texts."""
        embeddings = await self.encode_text([text1, text2])
        e1, e2 = embeddings[0], embeddings[1]
        n1, n2 = np.linalg.norm(e1), np.linalg.norm(e2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(np.dot(e1, e2) / (n1 * n2))

    def clear_cache(self):
        self._embedding_cache.clear()

    def get_cache_size(self) -> int:
        return len(self._embedding_cache)


# Global embedding manager
embedding_manager = EmbeddingManager()
