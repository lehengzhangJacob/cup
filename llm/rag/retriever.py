# rag/retriever.py
import json
import os
import shutil
import tempfile

import numpy as np
import faiss
from rag.config import (
    FAISS_INDEX, METADATA_JSON, WHITELIST_JSON,
    TOP_K_FILTERED, TOP_K_FULL
)
from rag.embedder import Embedder


def _read_index_unicode_safe(src):
    """faiss 的 C++ 文件读取在 Windows 下无法处理含非 ASCII 字符的路径。
    先把索引拷到 ASCII 临时文件再读取。"""
    src = str(src)
    try:
        return faiss.read_index(src)
    except RuntimeError:
        fd, tmp_path = tempfile.mkstemp(suffix=".index")
        os.close(fd)
        try:
            shutil.copyfile(src, tmp_path)
            return faiss.read_index(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class Retriever:
    def __init__(self, *, embedder=None, index_path=FAISS_INDEX, metadata_path=METADATA_JSON):
        if not index_path.exists() or not metadata_path.exists():
            raise FileNotFoundError(
                "RAG index is missing; run `python scripts/build_index.py` first"
            )
        self._index = _read_index_unicode_safe(index_path)
        with open(metadata_path, encoding="utf-8") as f:
            self._records = json.load(f)
        if self._index.ntotal != len(self._records):
            raise ValueError(
                "FAISS vector count does not match metadata record count: "
                f"{self._index.ntotal} != {len(self._records)}"
            )
        if not self._records:
            raise ValueError("RAG index contains no records")
        wl = json.loads(WHITELIST_JSON.read_text(encoding="utf-8"))
        self._names = wl["names"]
        self._aliases = wl["aliases"]
        self._scenic_areas = set(wl.get("scenic_areas", []))
        self._sub_to_area = wl.get("sub_to_area", {})
        self._embedder = embedder or Embedder()
        # The corpus is small. Keeping normalized vectors in memory avoids
        # rebuilding a temporary FAISS index for every metadata-filtered query.
        self._vectors = np.stack(
            [self._get_vector(i) for i in range(self._index.ntotal)]
        ).astype(np.float32)

    def _resolve_names(self, question: str) -> list:
        """返回问题中命中的景点名列表（含别名解析），长名优先避免部分匹配。"""
        matched = []
        # 别名（如“大佛”→“灵山大佛”）
        for alias, canonical in self._aliases.items():
            if alias in question and canonical not in matched:
                matched.append(canonical)
        # 白名单景点名，长名优先（先匹配“拈花湾禅意小镇”再“拈花湾”/“灵山胜境”）
        for name in sorted(self._names, key=len, reverse=True):
            if name in question and name not in matched:
                # 若已命中更长且包含它的名字，跳过（避免“灵山胜境”被“灵山大佛”问题误触）
                if any(name in m and name != m for m in matched):
                    continue
                matched.append(name)
        return matched

    def _expand_targets(self, matched_names):
        """把命中名称展开为景点级与景区级两类过滤条件。

        命中整个景区时允许其全部子景点；命中单个子景点时只允许该景点以及
        attraction_name 为父景区的概述，不能因为 scenic_area 相同而把所有兄弟
        景点都混入候选集。
        """
        attraction_targets = set()
        area_targets = set()
        for name in matched_names:
            if name in self._scenic_areas:
                area_targets.add(name)
            else:
                attraction_targets.add(name)
                area = self._sub_to_area.get(name)
                if area:
                    attraction_targets.add(area)
        return attraction_targets, area_targets

    def _filter_indices(self, attraction_targets, area_targets):
        """返回景点精确命中或景区范围命中的记录下标；无条件时返回 None。"""
        if not attraction_targets and not area_targets:
            return None
        return [
            i for i, r in enumerate(self._records)
            if r["metadata"].get("attraction_name") in attraction_targets
            or r["metadata"].get("scenic_area") in area_targets
        ]

    def retrieve(self, question: str) -> list:
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        matched_names = self._resolve_names(question)
        if not matched_names:
            # 无景点命中 → 全库搜索
            return self._search(question, None, TOP_K_FULL)
        targets = self._expand_targets(matched_names)
        return self._search(question, targets, TOP_K_FILTERED)

    def _search(self, question: str, targets, k: int) -> list:
        q_vec = self._embedder.encode_query(question).astype(np.float32).reshape(1, -1)
        if q_vec.shape[1] != self._index.d:
            raise ValueError(
                f"embedding dimension mismatch: {q_vec.shape[1]} != {self._index.d}"
            )
        if targets is None:
            candidate_indices = None
        else:
            candidate_indices = self._filter_indices(*targets)

        if candidate_indices is None or not candidate_indices:
            # 不过滤或命中景点但无对应chunk → 全库搜索
            actual_k = min(k, len(self._records))
            scores, indices = self._index.search(q_vec, actual_k)
            return [
                self._result(i, float(score))
                for score, i in zip(scores[0], indices[0])
                if 0 <= i < len(self._records)
            ]

        # 子集检索：直接对缓存矩阵计算内积。
        sub_vecs = self._vectors[candidate_indices]
        scores = sub_vecs @ q_vec[0]
        actual_k = min(k, len(candidate_indices))
        ranked = np.argsort(-scores)[:actual_k]
        return [
            self._result(candidate_indices[i], float(scores[i]))
            for i in ranked
        ]

    def _result(self, index: int, score: float) -> dict:
        record = self._records[index]
        return {
            "text": record["text"],
            "metadata": dict(record.get("metadata") or {}),
            "score": score,
        }

    def stats(self) -> dict:
        return {
            "chunk_count": len(self._records),
            "embedding_dimension": int(self._index.d),
            "sources": sorted(
                {
                    str(record.get("metadata", {}).get("source", "unknown"))
                    for record in self._records
                }
            ),
        }

    @property
    def embedder(self):
        return self._embedder

    def _get_vector(self, idx: int) -> np.ndarray:
        vec = np.zeros(self._index.d, dtype=np.float32)
        self._index.reconstruct(idx, vec)
        return vec
