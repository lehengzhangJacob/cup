# RAG知识库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建灵山胜境AI数字人导游的RAG知识库模块，支持 `pipeline.query(question) → answer` 单一接口。

**Architecture:** 离线阶段解析 guideline.docx + dataset.docx + xlsx（白名单过滤）→ 按语义章节分块 + 元数据标注 → BGE-M3向量化 → FAISS索引。在线阶段对问题做景点名匹配过滤，再语义检索Top-K段落，注入Prompt调用GLM-5 API生成回答。

**Tech Stack:** `python-docx`, `pandas`, `sentence-transformers` (BGE-M3), `faiss-cpu`, `openai` (兼容GLM-5 API格式)

---

## 文件结构

```
rag/
├── data/
│   ├── guideline.docx
│   ├── dataset.docx
│   └── 景点景区旅游数据行为分析数据.xlsx
├── scripts/
│   ├── extract_names.py       # 从docx提取景点白名单 → data/whitelist.json
│   └── build_index.py         # 离线构建FAISS索引 → index/
├── rag/
│   ├── __init__.py
│   ├── config.py              # 路径、模型名、K值等常量
│   ├── chunker.py             # 三数据源解析+分块，输出 List[{text, metadata}]
│   ├── embedder.py            # BGE-M3封装：encode_batch / encode_query
│   ├── retriever.py           # 景点识别+FAISS过滤检索，输出Top-K chunks
│   ├── prompt_builder.py      # chunks → Prompt字符串
│   └── pipeline.py            # RAGPipeline：query(str) → str
├── index/                     # build_index.py生成（不提交到git）
│   ├── faiss.index
│   └── metadata.json
├── tests/
│   ├── test_chunker.py
│   ├── test_retriever.py
│   └── test_pipeline.py
└── requirements.txt
```

---

### Task 1: 项目骨架与配置

**Files:**
- Create: `rag/__init__.py`
- Create: `rag/config.py`
- Create: `requirements.txt`

- [ ] **Step 1: 创建目录结构**

```bash
cd "c:/Users/I779318/Desktop/Manning/示范景区公开资料包"
mkdir -p rag scripts index tests
touch rag/__init__.py
```

- [ ] **Step 2: 写 requirements.txt**

```
python-docx>=1.1.0
pandas>=2.0.0
openpyxl>=3.1.0
sentence-transformers>=2.6.0
faiss-cpu>=1.7.4
openai>=1.0.0
```

- [ ] **Step 3: 写 rag/config.py**

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

DATA_DIR   = BASE_DIR / "data"
INDEX_DIR  = BASE_DIR / "index"

GUIDELINE_DOCX = DATA_DIR / "guideline.docx"
DATASET_DOCX   = DATA_DIR / "dataset.docx"
XLSX_FILE      = DATA_DIR / "景点景区旅游数据行为分析数据.xlsx"
WHITELIST_JSON = DATA_DIR / "whitelist.json"

FAISS_INDEX    = INDEX_DIR / "faiss.index"
METADATA_JSON  = INDEX_DIR / "metadata.json"

EMBED_MODEL    = "BAAI/bge-m3"
LLM_BASE_URL   = "https://open.bigmodel.cn/api/paas/v4/"
LLM_MODEL      = "glm-z1-flash"
LLM_API_KEY    = os.environ.get("GLM_API_KEY", "")

TOP_K_FILTERED = 3
TOP_K_FULL     = 5
MAX_CHUNK_CHARS = 500
CHUNK_OVERLAP   = 100
```

- [ ] **Step 4: 安装依赖**

```bash
pip install -r requirements.txt
```

Expected: 所有包安装成功，无报错。

- [ ] **Step 5: Commit**

```bash
git add rag/ requirements.txt
git commit -m "feat: rag project skeleton and config"
```

---

### Task 2: 景点白名单提取

**Files:**
- Create: `scripts/extract_names.py`
- Create: `tests/test_chunker.py`（部分，仅白名单测试）

白名单从 guideline.docx 和 dataset.docx 的段落文本中用正则提取已知景点名，同时维护别名映射。

- [ ] **Step 1: 写白名单提取脚本**

```python
# scripts/extract_names.py
import json, re
from docx import Document
from rag.config import GUIDELINE_DOCX, DATASET_DOCX, WHITELIST_JSON

# 已知灵山胜境景点名（含拈花湾），从docx段落验证后取交集
CANDIDATE_NAMES = [
    "灵山大佛", "灵山梵宫", "九龙灌浴", "五印坛城", "祥符禅寺",
    "佛手广场", "百子戏弥勒", "曼飞龙塔", "灵山精舍", "菩提大道",
    "三圣殿", "慈恩塔", "灵山佛学院", "拈花湾", "拈花湾禅意小镇",
    "梵天花海", "拈花塔", "觉路", "禅心岛",
]

ALIASES = {
    "大佛":   "灵山大佛",
    "梵宫":   "灵山梵宫",
    "坛城":   "五印坛城",
    "精舍":   "灵山精舍",
    "禅寺":   "祥符禅寺",
    "拈花湾": "拈花湾禅意小镇",
}

def extract_text(docx_path):
    doc = Document(docx_path)
    return "\n".join(p.text for p in doc.paragraphs)

def main():
    combined = extract_text(GUIDELINE_DOCX) + extract_text(DATASET_DOCX)
    confirmed = [n for n in CANDIDATE_NAMES if n in combined]
    result = {"names": confirmed, "aliases": ALIASES}
    WHITELIST_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(WHITELIST_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Extracted {len(confirmed)} attraction names: {confirmed}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行并检查输出**

```bash
python scripts/extract_names.py
cat data/whitelist.json
```

Expected: 输出至少8个景点名，包含"灵山大佛"、"灵山梵宫"、"九龙灌浴"。

- [ ] **Step 3: 写白名单测试**

```python
# tests/test_chunker.py
import json, pytest
from pathlib import Path

WHITELIST = Path("data/whitelist.json")

def test_whitelist_exists():
    assert WHITELIST.exists()

def test_whitelist_has_key_attractions():
    data = json.loads(WHITELIST.read_text(encoding="utf-8"))
    names = data["names"]
    for expected in ["灵山大佛", "灵山梵宫", "九龙灌浴"]:
        assert expected in names, f"{expected} missing from whitelist"

def test_whitelist_has_aliases():
    data = json.loads(WHITELIST.read_text(encoding="utf-8"))
    assert "大佛" in data["aliases"]
    assert data["aliases"]["大佛"] == "灵山大佛"
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_chunker.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/extract_names.py tests/test_chunker.py data/whitelist.json
git commit -m "feat: attraction name whitelist extraction"
```

---

### Task 3: 分块器（chunker.py）

**Files:**
- Create: `rag/chunker.py`
- Modify: `tests/test_chunker.py`（追加分块测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_chunker.py` 末尾追加：

```python
from rag.chunker import chunk_guideline, chunk_dataset, chunk_xlsx

def test_chunk_guideline_returns_list():
    chunks = chunk_guideline()
    assert isinstance(chunks, list)
    assert len(chunks) > 0

def test_chunk_guideline_metadata():
    chunks = chunk_guideline()
    for c in chunks:
        assert "text" in c and "metadata" in c
        assert "source" in c["metadata"]
        assert c["metadata"]["source"] == "guideline"

def test_chunk_dataset_returns_list():
    chunks = chunk_dataset()
    assert isinstance(chunks, list)
    assert len(chunks) > 0

def test_chunk_xlsx_filtered():
    chunks = chunk_xlsx()
    for c in chunks:
        meta = c["metadata"]
        assert meta.get("attraction_name") is not None
        # 只含白名单景点
        assert meta["attraction_name"] in _load_whitelist()

def _load_whitelist():
    import json
    from rag.config import WHITELIST_JSON
    return json.loads(WHITELIST_JSON.read_text(encoding="utf-8"))["names"]
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_chunker.py::test_chunk_guideline_returns_list -v
```

Expected: FAIL with `ImportError: cannot import name 'chunk_guideline'`

- [ ] **Step 3: 实现 rag/chunker.py**

```python
# rag/chunker.py
import json, re
import pandas as pd
from docx import Document
from rag.config import (
    GUIDELINE_DOCX, DATASET_DOCX, XLSX_FILE, WHITELIST_JSON,
    MAX_CHUNK_CHARS, CHUNK_OVERLAP
)

def _load_whitelist():
    data = json.loads(WHITELIST_JSON.read_text(encoding="utf-8"))
    return data["names"], data["aliases"]

def _split_long_text(text, max_chars=MAX_CHUNK_CHARS, overlap=CHUNK_OVERLAP):
    """按段落细切超长文本，保留overlap字符重叠。"""
    if len(text) <= max_chars:
        return [text]
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) > max_chars and current:
            chunks.append(current.strip())
            current = current[-overlap:] + "\n" + para
        else:
            current += "\n" + para
    if current.strip():
        chunks.append(current.strip())
    return chunks

def _detect_attraction(text, names):
    for name in sorted(names, key=len, reverse=True):
        if name in text:
            return name
    return "灵山胜境"

SECTION_RE = re.compile(r"^[一二三四五六七八九十]+[、．.]")

def chunk_guideline():
    doc = Document(GUIDELINE_DOCX)
    names, _ = _load_whitelist()
    chunks, current_section, current_text = [], "概述", []

    for para in doc.paragraphs:
        t = para.text.strip()
        if not t:
            continue
        if SECTION_RE.match(t) or (len(t) < 30 and t.endswith(("：", ":"))):
            if current_text:
                full = "\n".join(current_text)
                attraction = _detect_attraction(full, names)
                for piece in _split_long_text(full):
                    chunks.append({
                        "text": piece,
                        "metadata": {
                            "source": "guideline",
                            "attraction_name": attraction,
                            "section": current_section,
                        }
                    })
            current_section = t
            current_text = []
        else:
            current_text.append(t)

    if current_text:
        full = "\n".join(current_text)
        attraction = _detect_attraction(full, names)
        for piece in _split_long_text(full):
            chunks.append({
                "text": piece,
                "metadata": {
                    "source": "guideline",
                    "attraction_name": attraction,
                    "section": current_section,
                }
            })
    return chunks


def chunk_dataset():
    doc = Document(DATASET_DOCX)
    names, _ = _load_whitelist()
    chunks, current_name, current_text = [], None, []

    for para in doc.paragraphs:
        t = para.text.strip()
        if not t:
            continue
        matched = next((n for n in names if t.startswith(n) or n in t[:20]), None)
        if matched and matched != current_name:
            if current_text and current_name:
                chunks.append({
                    "text": "\n".join(current_text),
                    "metadata": {"source": "dataset", "attraction_name": current_name}
                })
            current_name = matched
            current_text = [t]
        else:
            current_text.append(t)

    if current_text and current_name:
        chunks.append({
            "text": "\n".join(current_text),
            "metadata": {"source": "dataset", "attraction_name": current_name}
        })
    return chunks


def chunk_xlsx():
    names, _ = _load_whitelist()
    df = pd.read_excel(XLSX_FILE, dtype=str).fillna("")
    chunks = []

    for _, row in df.iterrows():
        attraction = row.get("attraction_name", "").strip()
        if attraction not in names:
            continue
        content = row.get("attraction_content", "").strip()
        if not content:
            continue
        sections = re.split(r"(?=[一二三四五六七八九十]+[、．.])", content)
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue
            section_title = sec[:20].split("\n")[0]
            for piece in _split_long_text(sec):
                chunks.append({
                    "text": piece,
                    "metadata": {
                        "source": "xlsx",
                        "attraction_name": attraction,
                        "section": section_title,
                    }
                })
    return chunks


def load_all_chunks():
    return chunk_guideline() + chunk_dataset() + chunk_xlsx()
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_chunker.py -v
```

Expected: 全部 PASS（包含Task 2的3个测试）

- [ ] **Step 5: Commit**

```bash
git add rag/chunker.py tests/test_chunker.py
git commit -m "feat: chunker for guideline.docx, dataset.docx, xlsx"
```

---

### Task 4: Embedder

**Files:**
- Create: `rag/embedder.py`
- Create: `tests/test_retriever.py`（部分）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_retriever.py
from rag.embedder import Embedder

def test_embedder_encode_query():
    emb = Embedder()
    vec = emb.encode_query("灵山大佛多高？")
    assert vec.shape == (1024,)

def test_embedder_encode_batch():
    emb = Embedder()
    vecs = emb.encode_batch(["灵山大佛", "九龙灌浴"])
    assert vecs.shape == (2, 1024)
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_retriever.py::test_embedder_encode_query -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3: 实现 rag/embedder.py**

```python
# rag/embedder.py
import numpy as np
from sentence_transformers import SentenceTransformer
from rag.config import EMBED_MODEL

class Embedder:
    def __init__(self):
        self._model = SentenceTransformer(EMBED_MODEL)

    def encode_batch(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode_batch([text])[0]
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_retriever.py::test_embedder_encode_query tests/test_retriever.py::test_embedder_encode_batch -v
```

Expected: 2 passed（首次运行会下载BGE-M3模型，约1-2分钟）

- [ ] **Step 5: Commit**

```bash
git add rag/embedder.py tests/test_retriever.py
git commit -m "feat: BGE-M3 embedder"
```

---

### Task 5: 离线索引构建（build_index.py）

**Files:**
- Create: `scripts/build_index.py`

- [ ] **Step 1: 写 build_index.py**

```python
# scripts/build_index.py
import json
import numpy as np
import faiss
from rag.chunker import load_all_chunks
from rag.embedder import Embedder
from rag.config import FAISS_INDEX, METADATA_JSON

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

    FAISS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(FAISS_INDEX))

    records = [{"text": t, "metadata": m} for t, m in zip(texts, metas)]
    with open(METADATA_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Index saved: {len(chunks)} vectors → {FAISS_INDEX}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行构建**

```bash
python scripts/build_index.py
```

Expected 输出示例：
```
Loading chunks...
Total chunks: 187
Encoding with BGE-M3...
Building FAISS index...
Index saved: 187 vectors → .../index/faiss.index
```

- [ ] **Step 3: 验证索引文件存在**

```bash
ls -lh index/
```

Expected: `faiss.index` 和 `metadata.json` 均存在，faiss.index > 100KB。

- [ ] **Step 4: Commit**

```bash
git add scripts/build_index.py
git commit -m "feat: offline index builder"
```

---

### Task 6: 检索器（retriever.py）

**Files:**
- Create: `rag/retriever.py`
- Modify: `tests/test_retriever.py`（追加检索测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_retriever.py` 末尾追加：

```python
from rag.retriever import Retriever

def test_retriever_returns_chunks():
    r = Retriever()
    results = r.retrieve("灵山大佛是用什么材料建造的？")
    assert isinstance(results, list)
    assert len(results) > 0

def test_retriever_attraction_filter():
    r = Retriever()
    results = r.retrieve("九龙灌浴什么时候表演？")
    for chunk in results:
        # 过滤后结果应都来自九龙灌浴相关chunk
        assert "九龙灌浴" in chunk["metadata"]["attraction_name"] or \
               "灵山" in chunk["metadata"]["attraction_name"]

def test_retriever_full_search_on_no_match():
    r = Retriever()
    results = r.retrieve("景区几点开门？")
    assert len(results) > 0
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_retriever.py::test_retriever_returns_chunks -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3: 实现 rag/retriever.py**

```python
# rag/retriever.py
import json
import numpy as np
import faiss
from rag.config import (
    FAISS_INDEX, METADATA_JSON, WHITELIST_JSON,
    TOP_K_FILTERED, TOP_K_FULL
)
from rag.embedder import Embedder

class Retriever:
    def __init__(self):
        self._index = faiss.read_index(str(FAISS_INDEX))
        with open(METADATA_JSON, encoding="utf-8") as f:
            self._records = json.load(f)
        wl = json.loads(WHITELIST_JSON.read_text(encoding="utf-8"))
        self._names = wl["names"]
        self._aliases = wl["aliases"]
        self._embedder = Embedder()

    def _resolve_names(self, question: str) -> list[str]:
        """返回问题中命中的景点名列表（含别名解析）。"""
        matched = []
        for alias, canonical in self._aliases.items():
            if alias in question and canonical not in matched:
                matched.append(canonical)
        for name in self._names:
            if name in question and name not in matched:
                matched.append(name)
        return matched

    def _filter_indices(self, attraction_names: list[str]) -> list[int] | None:
        """返回属于指定景点的record下标列表，None表示不过滤。"""
        if not attraction_names:
            return None
        return [
            i for i, r in enumerate(self._records)
            if r["metadata"].get("attraction_name") in attraction_names
        ]

    def retrieve(self, question: str) -> list[dict]:
        matched_names = self._resolve_names(question)
        # 多景点或无景点命中 → 全库搜索
        if len(matched_names) != 1:
            return self._search(question, None, TOP_K_FULL)
        return self._search(question, matched_names, TOP_K_FILTERED)

    def _search(self, question: str, attraction_names, k: int) -> list[dict]:
        q_vec = self._embedder.encode_query(question).astype(np.float32).reshape(1, -1)
        candidate_indices = self._filter_indices(attraction_names)

        if candidate_indices is None:
            _, I = self._index.search(q_vec, k)
            return [self._records[i] for i in I[0] if i < len(self._records)]

        # 子集检索：临时建小索引
        sub_vecs = np.stack([
            self._get_vector(i) for i in candidate_indices
        ]).astype(np.float32)
        sub_index = faiss.IndexFlatIP(sub_vecs.shape[1])
        sub_index.add(sub_vecs)
        actual_k = min(k, len(candidate_indices))
        _, I = sub_index.search(q_vec, actual_k)
        return [self._records[candidate_indices[i]] for i in I[0]]

    def _get_vector(self, idx: int) -> np.ndarray:
        vec = np.zeros(self._index.d, dtype=np.float32)
        self._index.reconstruct(idx, vec)
        return vec
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_retriever.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add rag/retriever.py tests/test_retriever.py
git commit -m "feat: metadata-filtered FAISS retriever"
```

---

### Task 7: Prompt构建器

**Files:**
- Create: `rag/prompt_builder.py`

- [ ] **Step 1: 实现 rag/prompt_builder.py**

```python
# rag/prompt_builder.py

SYSTEM_PROMPT = (
    "你是灵山胜境的AI导游，名叫灵灵。请只根据下方提供的景区资料回答游客问题，"
    "不要编造资料中没有的内容。回答要自然亲切，适合口语表达。"
)

def build_prompt(chunks: list[dict], question: str) -> tuple[str, str]:
    """返回 (system_prompt, user_message)。"""
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        name = chunk["metadata"].get("attraction_name", "")
        section = chunk["metadata"].get("section", "")
        label = f"[资料{i}] {name} - {section}" if section else f"[资料{i}] {name}"
        context_parts.append(f"{label}\n{chunk['text']}")

    context = "\n\n".join(context_parts)
    user_message = f"参考资料：\n{context}\n\n游客问题：{question}"
    return SYSTEM_PROMPT, user_message
```

- [ ] **Step 2: 快速验证**

```bash
python -c "
from rag.prompt_builder import build_prompt
sys_p, usr_p = build_prompt([{'text':'大佛高88米','metadata':{'attraction_name':'灵山大佛','section':'基本参数'}}], '大佛多高？')
print(sys_p[:30])
print(usr_p[:100])
"
```

Expected: 打印系统提示前30字和用户消息前100字，无报错。

- [ ] **Step 3: Commit**

```bash
git add rag/prompt_builder.py
git commit -m "feat: prompt builder"
```

---

### Task 8: RAG Pipeline

**Files:**
- Create: `rag/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pipeline.py
import pytest
from rag.pipeline import RAGPipeline

@pytest.fixture(scope="module")
def pipeline():
    return RAGPipeline()

def test_pipeline_returns_string(pipeline):
    answer = pipeline.query("灵山大佛是用什么材料建造的？")
    assert isinstance(answer, str)
    assert len(answer) > 10

def test_pipeline_factual_bronze(pipeline):
    answer = pipeline.query("灵山大佛是用什么材料建造的？")
    assert "青铜" in answer

def test_pipeline_opening_hours(pipeline):
    answer = pipeline.query("景区几点开门？")
    assert isinstance(answer, str)
    assert len(answer) > 5

def test_pipeline_route_recommendation(pipeline):
    answer = pipeline.query("我对历史文化感兴趣，推荐什么游览路线？")
    assert isinstance(answer, str)
    assert len(answer) > 20
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_pipeline.py::test_pipeline_returns_string -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3: 实现 rag/pipeline.py**

```python
# rag/pipeline.py
from openai import OpenAI
from rag.config import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY
from rag.retriever import Retriever
from rag.prompt_builder import build_prompt

class RAGPipeline:
    def __init__(self):
        self._retriever = Retriever()
        self._client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
        )

    def query(self, question: str) -> str:
        chunks = self._retriever.retrieve(question)
        system_prompt, user_message = build_prompt(chunks, question)
        response = self._client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.3,
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()
```

- [ ] **Step 4: 设置API Key并运行测试**

```bash
export GLM_API_KEY="your_glm_api_key_here"
pytest tests/test_pipeline.py -v
```

Expected: 4 passed（test_pipeline_factual_bronze 验证"青铜"在回答中）

- [ ] **Step 5: Commit**

```bash
git add rag/pipeline.py tests/test_pipeline.py
git commit -m "feat: RAG pipeline with GLM-5 integration"
```

---

### Task 9: 端到端准确率验证

**Files:**
- Create: `tests/eval_accuracy.py`

- [ ] **Step 1: 写准确率评测脚本**

```python
# tests/eval_accuracy.py
"""
手动运行：python tests/eval_accuracy.py
输出每题结果和总准确率。
"""
from rag.pipeline import RAGPipeline

TEST_CASES = [
    # (问题, 回答中必须包含的关键词列表)
    ("灵山大佛是用什么材料建造的？",          ["青铜"]),
    ("灵山大佛有多高？",                      ["88"]),
    ("九龙灌浴代表什么含义？",                ["释迦牟尼", "诞生"]),
    ("灵山梵宫被称为什么？",                  ["卢浮宫"]),
    ("五印坛城是什么风格的建筑？",            ["藏传"]),
    ("祥符禅寺有多少年历史？",                ["千年", "1008", "宋"]),
    ("亲子家庭游览路线怎么走？",              ["九龙灌浴", "百子戏弥勒"]),
    ("历史文化爱好者推荐什么路线？",          ["祥符禅寺", "灵山大佛", "梵宫"]),
    ("景区最佳游览季节是什么时候？",          ["春", "秋"]),
    ("九龙灌浴每天有几场表演？",              ["4", "5"]),
    ("灵山精舍提供什么体验？",                ["素斋", "早课"]),
    ("菩提大道有什么特色？",                  ["太湖", "菩提"]),
    ("灵山梵宫的穹顶有什么？",                ["天象", "飞天", "壁画"]),
    ("如何抱佛脚？",                          ["灵山大佛", "台阶", "祈福"]),
    ("曼飞龙塔是什么风格？",                  ["傣族"]),
]

def main():
    pipeline = RAGPipeline()
    passed = 0
    for question, keywords in TEST_CASES:
        answer = pipeline.query(question)
        hit = any(kw in answer for kw in keywords)
        status = "PASS" if hit else "FAIL"
        if hit:
            passed += 1
        print(f"[{status}] {question}")
        if not hit:
            print(f"       期望包含: {keywords}")
            print(f"       实际回答: {answer[:100]}")
    total = len(TEST_CASES)
    accuracy = passed / total * 100
    print(f"\n准确率: {passed}/{total} = {accuracy:.1f}%")
    assert accuracy >= 90, f"准确率 {accuracy:.1f}% 低于90%要求"

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行评测**

```bash
python tests/eval_accuracy.py
```

Expected: 准确率 ≥ 90%（13/15以上PASS）

- [ ] **Step 3: 若准确率不足90%，检查以下项**

常见原因与调整：
- FAIL集中在某景点 → 检查该景点在whitelist中是否存在，检查xlsx是否有对应行
- 回答"不知道" → 说明检索未命中，检查chunk中是否含关键词（`grep -r "青铜" index/metadata.json`）
- 回答内容正确但关键词不同 → 放宽TEST_CASES的关键词列表

- [ ] **Step 4: Commit**

```bash
git add tests/eval_accuracy.py
git commit -m "test: end-to-end accuracy evaluation (>=90% target)"
```

---

## 自检结果

- **Spec覆盖**：所有5节spec要求均有对应Task（白名单→Task2，分块→Task3，Embedding→Task4，检索→Task6，Pipeline→Task8，评测→Task9）✓
- **Placeholder扫描**：无TBD/TODO ✓
- **类型一致性**：`Retriever.retrieve()` 返回 `list[dict]`，`build_prompt()` 接受 `list[dict]`，`RAGPipeline.query()` 调用链一致 ✓
- **数据源**：全部使用 `.docx` 文件，无 `.txt` 引用 ✓
