# rag/embedder.py
import os
import numpy as np
from sentence_transformers import SentenceTransformer
from rag.config import EMBED_MODEL


class Embedder:
    def __init__(self):
        self._model = SentenceTransformer(EMBED_MODEL)

    def encode_batch(self, texts: list) -> np.ndarray:
        return self._model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode_batch([text])[0]
