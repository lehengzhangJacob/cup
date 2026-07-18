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
    def __init__(self):
        self._index = _read_index_unicode_safe(FAISS_INDEX)
        with open(METADATA_JSON, encoding="utf-8") as f:
            self._records = json.load(f)
        wl = json.loads(WHITELIST_JSON.read_text(encoding="utf-8"))
        self._names = wl["names"]
        self._aliases = wl["aliases"]
        self._scenic_areas = set(wl.get("scenic_areas", []))
        self._sub_to_area = wl.get("sub_to_area", {})
        self._embedder = Embedder()

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
        """把命中的景点名展开为“允许的 attraction_name 集合”。

        - 命中景区（灵山胜境/拈花湾禅意小镇）：纳入该景区全部子景点 + 景区本身。
        - 命中子景点（灵山大佛）：纳入该子景点 + 其父景区（父景区的导览叙述常含关键细节）。
        """
        targets = set()
        for name in matched_names:
            if name in self._scenic_areas:
                targets.add(name)
                for sub, area in self._sub_to_area.items():
                    if area == name:
                        targets.add(sub)
            else:
                targets.add(name)
                area = self._sub_to_area.get(name)
                if area:
                    targets.add(area)
        return targets

    def _filter_indices(self, targets):
        """返回 attraction_name 或 scenic_area 命中 targets 的 record 下标；空则 None。"""
        if not targets:
            return None
        return [
            i for i, r in enumerate(self._records)
            if r["metadata"].get("attraction_name") in targets
            or r["metadata"].get("scenic_area") in targets
        ]

    def retrieve(self, question: str) -> list:
        matched_names = self._resolve_names(question)
        if not matched_names:
            # 无景点命中 → 全库搜索
            return self._search(question, None, TOP_K_FULL)
        targets = self._expand_targets(matched_names)
        return self._search(question, targets, TOP_K_FILTERED)

    def _search(self, question: str, targets, k: int) -> list:
        q_vec = self._embedder.encode_query(question).astype(np.float32).reshape(1, -1)
        candidate_indices = self._filter_indices(targets)

        if candidate_indices is None or not candidate_indices:
            # 不过滤或命中景点但无对应chunk → 全库搜索
            _, I = self._index.search(q_vec, k)
            return [self._records[i] for i in I[0] if 0 <= i < len(self._records)]

        # 子集检索：临时建小索引
        sub_vecs = np.stack([
            self._get_vector(i) for i in candidate_indices
        ]).astype(np.float32)
        sub_index = faiss.IndexFlatIP(sub_vecs.shape[1])
        sub_index.add(sub_vecs)
        actual_k = min(k, len(candidate_indices))
        _, I = sub_index.search(q_vec, actual_k)
        return [self._records[candidate_indices[i]] for i in I[0] if 0 <= i < len(candidate_indices)]

    def _get_vector(self, idx: int) -> np.ndarray:
        vec = np.zeros(self._index.d, dtype=np.float32)
        self._index.reconstruct(idx, vec)
        return vec
