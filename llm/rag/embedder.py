# rag/embedder.py
import threading

import numpy as np
from sentence_transformers import SentenceTransformer
from rag.config import EMBED_DEVICE, EMBED_MODEL


class Embedder:
    def __init__(self, model=None):
        self._model = model or SentenceTransformer(
            EMBED_MODEL,
            device=EMBED_DEVICE,
        )
        self._lock = threading.Lock()

    def encode_batch(self, texts: list) -> np.ndarray:
        if not texts:
            raise ValueError("texts must not be empty")
        with self._lock:
            vectors = self._model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return np.asarray(vectors, dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode_batch([text])[0]
