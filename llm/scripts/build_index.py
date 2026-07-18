# scripts/build_index.py
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import faiss
from rag.chunker import load_all_chunks
from rag.embedder import Embedder
from rag.config import FAISS_INDEX, METADATA_JSON


def _write_index_unicode_safe(index, dest: Path):
    """faiss 的 C++ 文件写入在 Windows 下无法处理含非 ASCII 字符的路径
    （本项目根目录名为“示范景区公开资料包”）。先写入 ASCII 临时文件，
    再用 Python 移动到目标位置。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".index")
    os.close(fd)
    try:
        faiss.write_index(index, tmp_path)
        shutil.move(tmp_path, str(dest))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def main():
    print("Loading chunks...")
    chunks = load_all_chunks()
    print(f"Total chunks: {len(chunks)}")

    texts = [c["text"] for c in chunks]
    metas = [c["metadata"] for c in chunks]

    print("Encoding with BGE-M3...")
    emb = Embedder()
    vectors = emb.encode_batch(texts).astype(np.float32)

    print("Building FAISS index...")
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)

    _write_index_unicode_safe(index, FAISS_INDEX)

    records = [{"text": t, "metadata": m} for t, m in zip(texts, metas)]
    with open(METADATA_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Index saved: {len(chunks)} vectors -> {FAISS_INDEX}")


if __name__ == "__main__":
    main()
