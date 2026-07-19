# BGE-M3 + FAISS + GLM RAG 服务

该目录提供一个独立、仅供导览网关访问的 RAG 服务。启动时加载 BGE-M3 和现有
FAISS 索引；每次提问先检索景区资料，再把检索片段、游客上下文及有限会话历史交给
GLM 生成。也可选择本地 Qwen2-7B 作为生成模型，但两条生成路径共用同一套
BGE-M3 + FAISS 检索。

## 启动与重建索引

```bash
cd /home/gmn/codes/cup
bash deploy/start_rag.sh

# 文档发生变化时可单独重建；线上管理端上传/删除文档会自动调用此逻辑
cd llm
/home/gmn/.conda/envs/softcup/bin/python scripts/build_index.py
```

生产启动脚本默认只监听 `127.0.0.1:8020`，并使用物理 GPU 3。可通过
`RAG_GPU`、`RAG_PORT`、`RAG_PYTHON` 覆盖。`RAG_HF_OFFLINE=true` 表示从本机
Hugging Face 缓存加载 BGE-M3，避免重启时访问外网。启动脚本同时安装轻量健康
看护；服务异常退出时会重新加载，记录在 `deploy/rag-watchdog.log`。

## 问答接口

非流式请求：

```bash
curl http://127.0.0.1:8020/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"灵山大佛有多高？","stream":false}'
```

流式请求：

```bash
curl -N http://127.0.0.1:8020/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"灵山大佛有多高？","session_id":"demo-1","stream":true}'
```

SSE 顺序为：

- `meta`：服务生成或沿用的 `session_id`、引用、历史轮数和检索耗时；
- `delta`：可直接展示或送入 TTS/LiveTalking 的增量文本；
- `done`：本轮总耗时；失败时返回 `error`。

不传 `session_id` 仍可完成单轮问答，响应会返回自动生成的会话 ID。客户端在后续
请求中回传该 ID，即可处理“它是什么材料”等依赖上文的追问。历史采用进程内
TTL/LRU 存储，只保存完整成功的回答；流被取消或生成失败时不会写入半段内容。默认
保留 1 小时、最多 1000 个会话、每个会话最近 6 轮，服务重启后历史会清空。

## 主要配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `RAG_EMBED_MODEL` | `BAAI/bge-m3` | 本地向量模型 |
| `RAG_LLM_MODEL` | `glm-4-flash-250414` | 云端生成模型 |
| `RAG_LLM_FALLBACK_MODELS` | `glm-4-flash` | 首 token 超时后的备用模型 |
| `RAG_LLM_FIRST_TOKEN_TIMEOUT_SECONDS` | `2` | 云端模型首 token 超时秒数 |
| `RAG_LLM_BASE_URL` | 智谱 OpenAI 兼容地址 | 云端接口地址 |
| `GLM_API_KEY` / `ZHIPU_API_KEY` | 根目录 `softcup_glmkey` | 服务端密钥 |
| `RAG_SESSION_TTL_SECONDS` | `3600` | 会话空闲过期时间 |
| `RAG_SESSION_MAX_COUNT` | `1000` | 内存会话上限 |
| `RAG_SESSION_MAX_TURNS` | `6` | 每个会话保留轮数 |
| `RAG_EXTRA_DOCS_DIR` | `data/lingshan/knowledge_uploads` | 管理员知识文档目录 |

健康状态见 `GET /health`，统计见 `GET /v1/stats`，清除指定历史使用
`DELETE /v1/sessions/{session_id}`。索引重建接口 `POST /v1/index/rebuild` 只应由
本机导览网关调用；对外网关的对应入口已限制到登录后的管理端口。
