"""Embeddings generation using BERT models"""
import asyncio
import numpy as np
from typing import List, Optional, Union
from sentence_transformers import SentenceTransformer
import torch
from functools import lru_cache
import time
from config import EMBEDDING_BATCH_SIZE, TIMEOUTS

class EmbeddingManager:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._device = None
        self._embedding_cache = {}
        self._max_cache_size = 1000

    async def initialize(self):
        """Lazy initialization of the embedding model"""
        if self._model is None:
            await self._load_model()

    async def _load_model(self):
        """Load the sentence transformer model"""
        loop = asyncio.get_event_loop()
        
        def _load():
            # Determine device
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            self._device = device
            
            # Load model
            model = SentenceTransformer(self.model_name, device=device)
            return model
        
        # Run in thread pool to avoid blocking
        self._model = await loop.run_in_executor(None, _load)

    async def encode_text(self, text: Union[str, List[str]], 
                         batch_size: int = EMBEDDING_BATCH_SIZE) -> np.ndarray:
        """
        Generate embeddings for text(s)
        Returns numpy array of embeddings
        """
        await self.initialize()
        
        if isinstance(text, str):
            text = [text]
        
        # Check cache first
        cached_embeddings = []
        uncached_texts = []
        uncached_indices = []
        
        for i, t in enumerate(text):
            cache_key = hash(t)
            if cache_key in self._embedding_cache:
                cached_embeddings.append((i, self._embedding_cache[cache_key]))
            else:
                uncached_texts.append(t)
                uncached_indices.append(i)
        
        # Generate embeddings for uncached texts
        new_embeddings = []
        if uncached_texts:
            try:
                start_time = time.time()
                
                # Process in batches
                all_new_embeddings = []
                for i in range(0, len(uncached_texts), batch_size):
                    batch = uncached_texts[i:i + batch_size]
                    
                    # Run encoding in thread pool
                    loop = asyncio.get_event_loop()
                    batch_embeddings = await loop.run_in_executor(
                        None, 
                        lambda: self._model.encode(batch, convert_to_numpy=True)
                    )
                    all_new_embeddings.extend(batch_embeddings)
                
                # Cache new embeddings
                for i, emb in enumerate(all_new_embeddings):
                    cache_key = hash(uncached_texts[i])
                    self._embedding_cache[cache_key] = emb
                
                # Manage cache size
                if len(self._embedding_cache) > self._max_cache_size:
                    # Remove oldest entries (simple LRU approximation)
                    items = list(self._embedding_cache.items())
                    for key, _ in items[:len(items) - self._max_cache_size + 100]:
                        del self._embedding_cache[key]
                
                new_embeddings = all_new_embeddings
                
                elapsed = time.time() - start_time
                if elapsed > TIMEOUTS["embedding_generation"]:
                    print(f"Warning: Embedding generation took {elapsed:.2f}s")
                    
            except Exception as e:
                print(f"Error generating embeddings: {e}")
                # Return zero embeddings as fallback
                embedding_dim = 384  # Default for all-MiniLM-L6-v2
                return np.zeros((len(text), embedding_dim))
        
        # Combine cached and new embeddings in correct order
        final_embeddings = [None] * len(text)
        
        # Place cached embeddings
        for idx, emb in cached_embeddings:
            final_embeddings[idx] = emb
        
        # Place new embeddings
        for i, idx in enumerate(uncached_indices):
            if i < len(new_embeddings):
                final_embeddings[idx] = new_embeddings[i]
        
        return np.array(final_embeddings)

    async def encode_chunks(self, chunks: List[str]) -> List[np.ndarray]:
        """Generate embeddings for document chunks"""
        if not chunks:
            return []
        
        embeddings = await self.encode_text(chunks)
        return [embeddings[i] for i in range(len(chunks))]

    def get_embedding_dimension(self) -> int:
        """Get the dimension of embeddings"""
        if self._model:
            return self._model.get_sentence_embedding_dimension()
        return 384  # Default for all-MiniLM-L6-v2

    async def similarity(self, text1: str, text2: str) -> float:
        """Calculate cosine similarity between two texts"""
        embeddings = await self.encode_text([text1, text2])
        
        # Calculate cosine similarity
        emb1, emb2 = embeddings[0], embeddings[1]
        dot_product = np.dot(emb1, emb2)
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(dot_product / (norm1 * norm2))

    def clear_cache(self):
        """Clear embedding cache"""
        self._embedding_cache.clear()

    def get_cache_size(self) -> int:
        """Get current cache size"""
        return len(self._embedding_cache)

# Global embedding manager
embedding_manager = EmbeddingManager()