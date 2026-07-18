# RAG知识库设计文档
## 灵山胜境AI数字人导游 — 检索增强生成模块

---

## 背景与目标

本模块为AI数字人导游系统的知识库RAG组件。游客通过数字人提问，系统检索景区知识库并注入LLM生成准确回答。

**核心指标：**
- 事实性问答准确率 ≥ 90%
- 查询端到端延迟 < 5秒
- 知识范围：灵山胜境（主）+ 拈花湾禅意小镇（含）

---

## 1. 整体架构

```
知识源文件
  guideline.txt  ──┐
  dataset.txt    ──┤──► 文档解析 ──► 分块+元数据标注 ──► BGE-M3 Embedding ──► FAISS向量库
  xlsx(过滤后)   ──┘

查询流程
  游客提问
     │
     ▼
  景点名识别（白名单字符串匹配）
     │
     ▼
  元数据过滤（attraction_name）→ FAISS语义检索 → Top-K 相关段落
     │
     ▼
  Prompt组装（系统提示 + 检索段落 + 用户问题）
     │
     ▼
  GLM-5 API → 回答文本 → 返回数字人
```

**三个核心阶段：**
1. **Indexing**（离线，一次性）：解析文档 → 分块 → 向量化 → 存入FAISS
2. **Retrieval**（在线，实时）：识别景点 → 过滤 → 语义检索 → 返回Top-K段落
3. **Generation**：将检索结果注入Prompt，调用GLM-5生成最终回答

---

## 2. 知识源与分块策略

### 数据源关系

| 数据源 | 内容粒度 | 主要覆盖 |
|---|---|---|
| guideline.txt | 景区整体、游览路线、实用贴士 | 景区级别信息 |
| dataset.txt | 景点结构化目录（ID、位置、参数） | 景点级别结构化信息 |
| xlsx（白名单过滤） | 每个具体景点的长篇 attraction_content | 景点级别详细描述 |

三者互补，覆盖不同粒度，均为必须使用的数据源。

### 景点白名单

从 guideline.txt 和 dataset.txt 自动提取景点名，构建白名单，用于：
1. 过滤 xlsx，只保留灵山胜境相关景点行
2. 查询时做景点名匹配

白名单示例：
```
["灵山大佛", "灵山梵宫", "九龙灌浴", "五印坛城", "祥符禅寺",
 "佛手广场", "百子戏弥勒", "曼飞龙塔", "灵山精舍", "菩提大道", ...]
```

白名单同时维护**简称/别名映射**（如"大佛"→"灵山大佛"，"梵宫"→"灵山梵宫"），提升召回。

### 各数据源分块规则

**guideline.txt — 按语义章节分块**

沿 `一、` `二、` `三、` 等标题边界切分，每章节为一个chunk。超过600字的章节按段落细切，保留100字重叠。

```python
metadata = {
    "source": "guideline",
    "attraction_name": "灵山大佛",   # 从章节标题识别
    "section": "核心景点"
}
```

**dataset.txt — 按景点记录分块**

每个景点的所有结构化字段合并为一个chunk，保留完整性。

```python
metadata = {
    "source": "dataset",
    "attraction_name": "灵山大佛"
}
```

**xlsx — 白名单过滤 + 分节分块**

1. 过滤：`attraction_name` 在白名单中的行
2. 对每行 `attraction_content` 按 `一、二、三、` 标题切分
3. 超过500字的节再按段落细切，100字重叠
4. 关键数字所在句子前后各保留1句，防止切断关键事实

```python
metadata = {
    "source": "xlsx",
    "attraction_name": "灵山大佛",
    "section": "发展历程"
}
```

### Chunk数量估算

| 数据源 | 预计chunk数 |
|---|---|
| guideline.txt | ~30–50 |
| dataset.txt | ~20–30 |
| xlsx（灵山相关行） | ~100–200 |
| **合计** | **~150–280** |

---

## 3. Embedding与检索策略

### Embedding模型

**BGE-M3**（`BAAI/bge-m3`）：
- 专为中文优化，中文语义检索性能优秀
- 支持最长8192 token，适合较长chunk
- 完全开源，本地运行，无API费用
- 向量维度1024，存入 FAISS `IndexFlatIP`（内积相似度）

### 两步检索流程

**Step 1 — 景点识别（元数据过滤）**

对用户问题做白名单字符串匹配：

```
"灵山大佛是用什么材料建造的？" → 命中"灵山大佛" → filter: attraction_name == "灵山大佛"
"景区几点开门？"               → 无命中 → 全库搜索
"梵宫和大佛有什么区别？"       → 命中多个景点 → 取消过滤，全库搜索
```

字符串精确匹配 + 别名映射覆盖90%+景点类问题，无命中时回退全库，不依赖额外LLM调用。

**Step 2 — 语义检索**

| 场景 | K值 |
|---|---|
| 有景点过滤（子集小） | K=3 |
| 无过滤（全库） | K=5 |

### Prompt结构

```
系统提示：你是灵山胜境的AI导游，只根据以下参考资料回答问题，不要编造。

参考资料：
[chunk1内容]
[chunk2内容]
[chunk3内容]

游客问题：{user_question}

请用自然亲切的中文回答。
```

---

## 4. 系统组件与代码结构

```
rag/
├── data/
│   ├── guideline.txt
│   ├── dataset.txt
│   └── 景点景区旅游数据行为分析数据.xlsx
├── scripts/
│   ├── build_index.py              # 离线：解析→分块→embedding→存FAISS
│   └── extract_attraction_names.py # 从txt提取景点白名单
├── rag/
│   ├── chunker.py                  # 三个数据源各自的分块逻辑
│   ├── embedder.py                 # BGE-M3封装
│   ├── retriever.py                # 景点识别+FAISS检索
│   ├── prompt_builder.py           # Prompt组装
│   └── pipeline.py                 # 对外唯一入口：query(question) → answer
├── index/                          # build_index.py生成
│   ├── faiss.index
│   └── metadata.json
├── config.py
└── requirements.txt
```

### 各模块职责

| 模块 | 职责 |
|---|---|
| `chunker.py` | 三种数据源的解析与分块，输出 `{text, metadata}` 列表 |
| `embedder.py` | 加载BGE-M3，批量encode，单条query encode |
| `retriever.py` | 景点名白名单匹配 → FAISS过滤检索 → 返回Top-K chunks |
| `prompt_builder.py` | 将chunks拼成Prompt字符串 |
| `pipeline.py` | 串联retriever + prompt_builder + GLM-5 API调用 |
| `build_index.py` | 调用chunker→embedder→写faiss.index+metadata.json |

### 对外接口

```python
from rag.pipeline import RAGPipeline

pipeline = RAGPipeline()  # 启动时加载一次

answer = pipeline.query("灵山大佛是用什么材料建造的？")
```

### 依赖（requirements.txt）

```
sentence-transformers>=2.6.0
faiss-cpu>=1.7.4
pandas>=2.0.0
openpyxl>=3.1.0
openai>=1.0.0   # 兼容GLM-5 API格式
```

---

## 5. LLM配置

使用智谱AI GLM-5，API兼容OpenAI格式：

```python
# config.py
LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
LLM_MODEL    = "glm-z1-flash"  # GLM-5系列，根据实际可用model ID调整
LLM_API_KEY  = "..."          # 从环境变量读取
```

---

## 6. 构建流程与测试验证

### 离线索引构建

```bash
# 1. 提取景点白名单
python scripts/extract_attraction_names.py
# 输出: data/attraction_whitelist.json

# 2. 构建索引
python scripts/build_index.py
# 输出: index/faiss.index + index/metadata.json
# 预计耗时: 2-5分钟
```

### 延迟分解

| 步骤 | 预计耗时 |
|---|---|
| 景点名匹配（字符串） | <10ms |
| BGE-M3 encode问题 | ~100ms |
| FAISS检索 | <10ms |
| GLM-5 API生成 | 2-4s |
| **总计** | **<5s ✓** |

### 准确率测试方案

手动构建30-50个问答对，覆盖四类问题：

| 问题类型 | 示例 |
|---|---|
| 事实性 | "灵山大佛高度是多少？" |
| 文化性 | "九龙灌浴代表什么含义？" |
| 路线性 | "亲子路线怎么走？" |
| 跨景点比较 | "梵宫和五印坛城有什么区别？" |

评测：运行 `pipeline.query(question)`，检查关键事实是否包含在回答中，统计命中率。

### 常见失败模式及对策

| 失败原因 | 对策 |
|---|---|
| 景点名未命中白名单（如"大佛"） | 白名单支持别名/简称映射 |
| 问题跨多景点，过滤过严 | 检测到多景点关键词时取消过滤 |
| chunk切分切断关键数字 | 数字所在句子前后各保留1句 |
