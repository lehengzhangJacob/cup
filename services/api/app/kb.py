from __future__ import annotations

import json
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np

from .config import DOCS_DIR, KB_PATH, UPLOADS_DIR


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


@dataclass
class Chunk:
    id: str
    source: str
    title: str
    text: str
    tags: list[str]
    embedding: Optional[list[float]] = None


def _docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paras: list[str] = []
    for para in root.findall(".//w:p", NS):
        runs = [t.text or "" for t in para.findall(".//w:t", NS)]
        line = "".join(runs).strip()
        if line:
            paras.append(line)
    return paras


def _text_paragraphs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _split_chunks(paras: list[str], source: str, max_len: int = 450) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[str] = []
    title = source
    idx = 0

    def flush() -> None:
        nonlocal idx, buf
        if not buf:
            return
        text = "\n".join(buf).strip()
        if len(text) < 20:
            buf = []
            return
        tags = _guess_tags(text)
        chunks.append(
            Chunk(
                id=f"{Path(source).stem}-{idx:04d}",
                source=source,
                title=title,
                text=text,
                tags=tags,
            )
        )
        idx += 1
        buf = []

    for p in paras:
        if len(p) < 40 and not p.endswith(("。", "！", "？", ".", ":", "：")):
            # likely a heading
            flush()
            title = p
            buf = [p]
            continue
        buf.append(p)
        if sum(len(x) for x in buf) >= max_len:
            flush()
    flush()
    return chunks


def _guess_tags(text: str) -> list[str]:
    keys = [
        "灵山大佛",
        "梵宫",
        "九龙灌浴",
        "五印坛城",
        "祥符禅寺",
        "佛手广场",
        "菩提大道",
        "拈花湾",
        "历史",
        "文化",
        "亲子",
        "路线",
        "自然",
    ]
    return [k for k in keys if k in text]


# Built-in route cards from official guide
ROUTES = [
    {
        "id": "history",
        "name": "历史文化爱好者路线",
        "duration_hours": 6,
        "interest": "历史",
        "summary": "深度了解灵山佛教渊源、大佛造像与梵宫艺术。",
        "stops": [
            "南门",
            "灵山大照壁",
            "胜境广场",
            "佛手广场",
            "祥符禅寺",
            "杏坛广场",
            "佛前广场",
            "灵山大佛",
            "灵山梵宫",
            "五印坛城",
            "三圣殿",
        ],
    },
    {
        "id": "nature",
        "name": "自然风光爱好者路线",
        "duration_hours": 5,
        "interest": "自然",
        "summary": "以太湖风光与禅意园林为主，兼顾九龙灌浴与大佛登顶。",
        "stops": [
            "南门",
            "佛足坛",
            "九龙灌浴",
            "菩提大道",
            "灵山大佛",
            "曼飞龙塔",
            "灵山精舍",
            "梵宫广场",
        ],
    },
    {
        "id": "family",
        "name": "亲子家庭路线",
        "duration_hours": 4,
        "interest": "亲子",
        "summary": "轻松互动，适合亲子打卡九龙灌浴、佛手广场与百子戏弥勒。",
        "stops": [
            "南门",
            "九龙灌浴",
            "佛手广场",
            "百子戏弥勒",
            "梵宫",
            "五印坛城",
        ],
    },
]


class KnowledgeBase:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._matrix: Optional[np.ndarray] = None

    def load(self) -> None:
        if KB_PATH.exists():
            raw = json.loads(KB_PATH.read_text(encoding="utf-8"))
            self.chunks = [Chunk(**c) for c in raw]
            self._rebuild_matrix()
            return
        self.rebuild_from_docs()

    def rebuild_from_docs(self) -> int:
        KB_PATH.parent.mkdir(parents=True, exist_ok=True)
        all_chunks: list[Chunk] = []
        if not DOCS_DIR.exists():
            raise FileNotFoundError(f"docs dir missing: {DOCS_DIR}")
        source_dirs = [(DOCS_DIR, "官方资料"), (UPLOADS_DIR, "管理员上传")]
        for source_dir, source_label in source_dirs:
            if not source_dir.exists():
                continue
            # The official package contains DOCX and exported TXT copies with
            # the same stem. Index only one representation to avoid duplicate
            # retrieval results; prefer DOCX, then Markdown, then plain text.
            priority = {".docx": 0, ".md": 1, ".txt": 2}
            candidates = sorted(
                (
                    path
                    for path in source_dir.iterdir()
                    if path.is_file() and path.suffix.lower() in priority
                ),
                key=lambda path: (path.stem, priority[path.suffix.lower()]),
            )
            unique_paths: dict[str, Path] = {}
            for path in candidates:
                unique_paths.setdefault(path.stem, path)
            paths = list(unique_paths.values())
            for path in paths:
                paras = (
                    _docx_paragraphs(path)
                    if path.suffix.lower() == ".docx"
                    else _text_paragraphs(path)
                )
                all_chunks.extend(
                    _split_chunks(paras, f"{source_label}/{path.name}")
                )
        # append route cards as chunks
        for r in ROUTES:
            text = (
                f"{r['name']}（约{r['duration_hours']}小时）\n"
                f"适合兴趣：{r['interest']}\n"
                f"{r['summary']}\n"
                f"途经：{' → '.join(r['stops'])}"
            )
            all_chunks.append(
                Chunk(
                    id=f"route-{r['id']}",
                    source="builtin-routes",
                    title=r["name"],
                    text=text,
                    tags=["路线", r["interest"]],
                )
            )
        self.chunks = all_chunks
        self._matrix = None
        self.save()
        return len(self.chunks)

    def save(self) -> None:
        KB_PATH.parent.mkdir(parents=True, exist_ok=True)
        KB_PATH.write_text(
            json.dumps([asdict(c) for c in self.chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _rebuild_matrix(self) -> None:
        vectors = [c.embedding for c in self.chunks if c.embedding]
        if len(vectors) == len(self.chunks) and vectors:
            self._matrix = np.array(vectors, dtype=np.float32)
        else:
            self._matrix = None

    def set_embeddings(self, embeddings: list[list[float]]) -> None:
        if len(embeddings) != len(self.chunks):
            raise ValueError("embedding count mismatch")
        for c, e in zip(self.chunks, embeddings):
            c.embedding = e
        self._rebuild_matrix()
        self.save()

    def keyword_search(self, query: str, top_k: int = 6) -> list[tuple[Chunk, float]]:
        tokens = [t for t in re.split(r"\s+|，|。|？|！|,|\.|、", query) if t]
        scored: list[tuple[Chunk, float]] = []
        for c in self.chunks:
            score = 0.0
            for t in tokens:
                if t and t in c.text:
                    score += c.text.count(t) * (1.0 + 0.2 * len(t))
            for tag in c.tags:
                if tag in query:
                    score += 3.0
            if score > 0:
                scored.append((c, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def vector_search(self, query_vec: list[float], top_k: int = 6) -> list[tuple[Chunk, float]]:
        if self._matrix is None:
            return []
        q = np.array(query_vec, dtype=np.float32)
        qn = np.linalg.norm(q) + 1e-9
        mats = self._matrix
        norms = np.linalg.norm(mats, axis=1) + 1e-9
        sims = (mats @ q) / (norms * qn)
        idx = np.argsort(-sims)[:top_k]
        return [(self.chunks[i], float(sims[i])) for i in idx]

    def hybrid_search(
        self,
        query: str,
        query_vec: Optional[list[float]] = None,
        top_k: int = 6,
    ) -> list[Chunk]:
        kw = {c.id: s for c, s in self.keyword_search(query, top_k=top_k * 2)}
        vec: dict[str, float] = {}
        if query_vec is not None and self._matrix is not None:
            vec = {c.id: s for c, s in self.vector_search(query_vec, top_k=top_k * 2)}
        ids = set(kw) | set(vec)
        merged: list[tuple[str, float]] = []
        for i in ids:
            # normalize-ish merge
            score = kw.get(i, 0.0)
            if i in vec:
                score += vec[i] * 8.0
            merged.append((i, score))
        merged.sort(key=lambda x: x[1], reverse=True)
        by_id = {c.id: c for c in self.chunks}
        return [by_id[i] for i, _ in merged[:top_k] if i in by_id]


kb = KnowledgeBase()
