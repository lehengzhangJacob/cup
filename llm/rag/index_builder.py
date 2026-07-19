from __future__ import annotations

import json
import os
import tempfile
from typing import Optional

import faiss
import numpy as np

from rag.chunker import load_all_chunks
from rag.config import FAISS_INDEX, METADATA_JSON
from rag.embedder import Embedder


def build_index(*, embedder: Optional[Embedder] = None) -> dict:
    """Build a complete index and atomically publish its two output files."""
    chunks = load_all_chunks()
    if not chunks:
        raise ValueError("no knowledge chunks were produced")
    texts = [chunk["text"] for chunk in chunks]
    vectors = (embedder or Embedder()).encode_batch(texts).astype(np.float32)
    if len(vectors) != len(chunks):
        raise ValueError("embedding count does not match chunk count")

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    records = [
        {"text": chunk["text"], "metadata": chunk["metadata"]}
        for chunk in chunks
    ]

    FAISS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    index_fd, index_tmp = tempfile.mkstemp(
        prefix="rag-index-", suffix=".faiss", dir=FAISS_INDEX.parent
    )
    metadata_fd, metadata_tmp = tempfile.mkstemp(
        prefix="rag-metadata-", suffix=".json", dir=METADATA_JSON.parent
    )
    os.close(index_fd)
    try:
        faiss.write_index(index, index_tmp)
        with os.fdopen(metadata_fd, "w", encoding="utf-8") as output:
            json.dump(records, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        # Publish only after both temporary files are complete.
        os.replace(metadata_tmp, METADATA_JSON)
        os.replace(index_tmp, FAISS_INDEX)
    finally:
        for path in (index_tmp, metadata_tmp):
            if os.path.exists(path):
                os.unlink(path)

    return {
        "chunk_count": len(chunks),
        "embedding_dimension": int(vectors.shape[1]),
        "sources": sorted(
            {str(chunk["metadata"].get("source", "unknown")) for chunk in chunks}
        ),
    }
