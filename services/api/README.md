# 灵山胜境 AI 数字人导览 · 开放 API

本机为服务器，对外提供 HTTP 接口；问答支持云端 GLM、轻量本地 Qwen3-1.7B 与完整本地 Qwen2-7B 三条路径，视觉、ASR 和 TTS 保持原有独立链路。

## 环境（Miniconda）

```bash
source /home/anaconda/etc/profile.d/conda.sh
conda activate ccc
```

## 启动

```bash
cd /home/gmn/codes/cup
bash deploy/start_api.sh          # RAG 8020（内部）+ HTTP 8001 + HTTPS 8443
```

智谱密钥默认从项目根目录 `softcup_glmkey` 读取，也可设置
`ZHIPU_API_KEY`；云端问答模型可通过 `RAG_LLM_MODEL` 覆盖，默认使用
`glm-4-flash-250414`。

- 健康检查：`GET /health`
- Swagger：`http://<服务器IP>:8001/docs`
- 浏览器联调页：`http://<服务器IP>:8001/`
- 麦克风页面：`https://<服务器IP>:8443/`（首次访问接受自签名证书；8443 同时承载 TURN/TCP，可穿过 SSH/IDE TCP 端口转发）
- 景区管理后台：`https://<服务器IP>:8444/admin`（独立端口；默认账号 `admin`，默认密码 `123456abc`）

LiveTalking 以 CPU/RAM 待机方式常驻；建立 WebRTC 会话时从物理 GPU 0–3 中选择利用率低且至少剩余 2GB 的卡，最后一个会话关闭 2 秒后将 Wav2Lip 权重移回 CPU。可用 `LIVETALKING_GPU_CANDIDATES`、`LIVETALKING_GPU_MIN_FREE_MB` 和 `LIVETALKING_GPU_OFFLOAD_DELAY_SECONDS` 调整；后台日志位于
`deploy/livetalking/service.log`、`deploy/rag.log`、`deploy/local-llm.log`、`deploy/local-llm-lite.log` 和
`deploy/api.log`；RAG 自动恢复记录位于 `deploy/rag-watchdog.log`。

## 云端 / 轻量本地 / 完整本地问答三路径

- 网页默认选择 `GLM API`，不会加载本地 7B 权重。
- 选择 `轻量本地 Qwen3-1.7B` 后使用 `/home/datasets/EMO_GEN/EMO_GEN_model/Qwen/Qwen3-1.7B`，服务端口为 `8022`；实测加载后约占 5.6 GiB，默认要求候选 GPU 至少有 6 GiB 空闲显存。
- 选择 `本地 Qwen2-7B` 后，RAG 使用纯文本模型 `/home/huggingface/Qwen2-7B-Instruct`；冷加载实测约 15–60 秒，热请求生成很快。识景、语音和情绪分析仍由各自的多模态模型负责。
- 两个 `transformers serve` 分别在本机 `8021`、`8022` 提供 OpenAI 兼容接口；两条本地路径均在空闲 120 秒后停止独立进程并释放显存。
- 完整模型手动启停：`bash deploy/start_local_llm.sh`、`bash deploy/stop_local_llm.sh`；轻量模型手动启停：`bash deploy/start_local_lite_llm.sh`、`bash deploy/stop_local_lite_llm.sh`。
- 本地服务默认在首次使用时扫描物理 GPU 0–3，要求至少 18GB 空闲显存，并优先选择剩余显存最多、利用率更低的卡；可通过 `LOCAL_LLM_GPU_CANDIDATES`、`LOCAL_LLM_GPU_MIN_FREE_MB` 调整，或用 `LOCAL_LLM_GPU` 显式覆盖。Qwen2-7B 加载后约占 `15.7GiB`。本地路径适合离线或 API 故障备份；要求稳定 4–5 秒首答时优先使用云端路径。
- 轻量路径用对应的 `LOCAL_LITE_LLM_GPU_*` 变量独立选卡。没有满足门槛的 GPU 或发生真实 CUDA OOM 时，接口和游客页面会明确显示所需显存、失败模型及切换建议，不会返回假回答。

`POST /v1/chat` 的 `model_route` 可设为 `cloud`、`local_lite` 或 `local`；语音识别、语音合成和数字人口型链路不随该选项改变。

三种生成路径之前都使用同一套本地 BGE-M3 + FAISS 检索。`stream=true` 时接口按
`meta`（会话与引用）→ `delta`（增量文本）→ `done`（耗时）的顺序返回 SSE。首次
请求可不传 `session_id`，服务会创建并返回；后续请求回传它即可进行多轮追问。
会话默认空闲 1 小时过期、最多保留最近 6 轮，RAG 服务重启后清空。详细协议见
[`llm/README.md`](../../llm/README.md)。

## 无 sudo 的 Cloudflare 公网部署

校园网出口 NAT 和本机防火墙都不需要入站放行。网页、API、SSE 和管理后台通过
Cloudflare Named Tunnel 的出站连接发布；WebRTC 媒体单独使用 Cloudflare
Realtime TURN。普通 HTTP Tunnel 不能代替 TURN。

1. 在 Cloudflare 控制台创建一个 remotely-managed Tunnel，并添加两条 Public Hostname：

   | 公网域名 | Origin service | 额外设置 |
   |---|---|---|
   | `guide.example.com` | `http://127.0.0.1:8001` | 无 |
   | `admin.example.com` | `https://127.0.0.1:8444` | 开启 `No TLS Verify` |

2. 在 Realtime → TURN 创建 TURN key，保存其 Key ID 和 API token。项目后端会生成
   1 小时短期凭据，同时发给浏览器和 LiveTalking 服务端；长期 token 不会发给浏览器。
3. 安装用户目录版 `cloudflared`，复制并填写本地配置：

   ```bash
   cd /home/gmn/codes/cup
   bash deploy/install_cloudflared.sh
   cp deploy/public.env.example deploy/public.env
   chmod 600 deploy/public.env
   # 编辑 deploy/public.env：替换域名、后台密码、会话密钥、TURN 和 Tunnel 凭据
   ```

4. 启动完整服务：

   ```bash
   bash deploy/start_api.sh
   bash deploy/start_cloudflared.sh
   ```

5. 验证 `https://guide.example.com/health`、主页数字人和
   `https://admin.example.com/admin`。建议再用 Cloudflare Access 的 Self-hosted
   application 保护后台域名，只允许比赛团队账号访问。

公网模式下后台密码不足 12 个字符会拒绝启动；若显式设置
`ADMIN_SESSION_SECRET`，至少需要 32 个字符。Cloudflare TURN 凭据最长 48 小时，
本项目默认 1 小时并提前刷新。不要把 `deploy/public.env`、Tunnel token 或 TURN
API token 提交仓库或发送到聊天中。

## LiveTalking 本地真人数字人

项目使用仓库内的 `LiveTalking/`，Wav2Lip 权重和头像分别位于：

- `LiveTalking/models/wav2lip.pth`
- `LiveTalking/data/avatars/wav2lip256_avatar1/`

运行环境为 `ccc`（Python 3.12、PyTorch 2.5.1+cu121）。Wav2Lip 使用 FP16 和
batch 4，以降低显存峰值。浏览器通过本站同源 API 完成 WebRTC 信令，
页面不直接暴露 8010 的 HTTP 接口。

问答采用按语义句流水线：ASR → 所选模型流式输出 → 完整语义段 GLM-TTS →
LiveTalking Wav2Lip。TTS 提供方的 PCM 流会先合并为完整语义段，再作为一份 WAV
上传，避免提供方分块边界被重复淡入淡出、重采样而产生停顿或吞字；服务不可用时
自动回退到 GLM-TTS + Haru Live2D。播报语速固定为自然原速 1.0。

`bash deploy/start_api.sh` 会同时启动 LiveTalking 的 CPU 待机实例，约占 1.5GB 常驻内存且首次访问前不登记 GPU 进程。收到 WebRTC offer 后动态上卡，最后一个会话关闭 2 秒后移回 CPU。当前 PyTorch 进程首次使用某张卡后会保留约 312MiB CUDA 驱动上下文，但 Wav2Lip 权重和推理显存均已释放；如需连驱动上下文也归零，可用 `bash deploy/stop_livetalking.sh` 完全停止进程。

2026-07-19 本机实测首次 CPU→GPU 3 迁移 1217ms，后续迁移 143ms；完整 offer 分别为 1566ms 和 366ms，活动时 Wav2Lip 占 756MiB。GPU 会按当时的空闲显存和利用率重新选择。

首屏会立即并行建立 WebRTC，Live2D 备用引擎及约 3MB 资源仅在真人数字人失败时加载。云端问答默认使用低延迟的 `glm-4-flash-250414`，首 token 超过 2 秒会切换 `glm-4-flash`。语音只在句末标点或足够长的自然分句处切分，不再按 12 字硬切；120 字无标点才启用安全切分。用户正常阅读或录音期间会并行完成数字人连接。

页面打开、重新可见或用户开始输入时，还会调用 `/v1/rag/warmup` 后台预热
BGE-M3。预热后的公网实测为：检索 27ms、首文本 1033ms、首个完整语义句
1490ms、文本完成 2279ms；无操作 180 秒后仍会释放 RAG GPU 工作进程。

2026-07-19 本机实测“语音输入结束 → 第一个非静音 WebRTC 音频帧”为 3373ms：
ASR 451ms、LLM 首句 1151ms、TTS/口型 1772ms。实际延迟会随外部模型接口和
所选 GPU 上其他任务的负载波动。

同日早期延迟优先配置的中位数为：首响 2987ms、最后音频 9387ms；该配置使用
1.12 倍速和提供方 PCM 小块逐个上传，现已因自然度问题停用。完整口径、阶段数据见
[`docs/文字到语音端到端延迟测试与优化.md`](../../docs/文字到语音端到端延迟测试与优化.md)。

## XMOV 3D 真人数字人（可选）

XMOV 代码保留作方案对照，但当前页面只初始化本地 LiveTalking；如需切回 XMOV，需同时恢复前端 `bootXmov()` 初始化并配置以下变量：

```bash
export XMOV_APP_ID="your_app_id"
export XMOV_APP_SECRET="your_app_secret"
export XMOV_SESSION_GATEWAY_URL="https://nebula-agent.xingyun3d.com/user/v1/ttsa/session"
export XMOV_BROWSER_CONFIG_ENABLED=true
# 可选：
# export XMOV_AUTH_HEADER="..."
# export XMOV_SDK_URL="https://media.xingyun3d.com/xingyun3d/general/litesdk/xmovAvatar@latest.js"
```

XMOV 官方 Web SDK 初始化需要浏览器取得 App Secret，因此本项目默认关闭凭据下发。只应在 localhost、HTTPS 或受控演示环境开启；公网生产环境应改用 XMOV 提供的后端签名或临时会话方案。XMOV 缺少配置或初始化失败时，页面会自动回退到 GLM-TTS + Live2D。

## 管理后台洞察与多模态情感

管理后台同时使用两类数据：SQLite 中持续产生的问答、反馈和情感任务用于实时运营
大屏；赛题 XLSX 用于历史游客分层分析。当前资料包可生成访问记录数、游客数、景点
数、满意度分布/月度趋势、景点类型/年龄/消费区间对比和消费相关性。启动脚本会按源
文件指纹将 XLSX 的 17 列、140447 行明细幂等写入 `tourism_visits`，同时保留聚合缓存；
DOCX 中的灵山胜境、拈花湾及其子景点写入 `attractions`，作为游客评分对象。

多模态情绪来自游客与数字人的真实对话，不由管理员上传样本。文字问题即时写入文本
情感事件；语音问题先 ASR，游客明确授权时再将原声、转写和最近会话上下文异步送入
HumanOmni，问答本身不等待情绪推理。默认分析完成后删除原始音频，只保留匿名化的
七类情绪、置信度、正/中/负倾向、方面、模型与降级状态。游客另行对景区或子景点提交
1–5 分和意见，显式满意度与推断情绪分开保存。

模型可使用 HTTP 服务或本地推理脚本，HTTP 优先。示例配置：

```bash
# 方案一：已有独立推理服务，接收 multipart 的 file/transcript/prompt
export EMOTION_INFERENCE_URL="http://127.0.0.1:8030/infer"

# 方案二：本地 HumanOmni 推理脚本
export EMOTION_MODEL_PATH="/home/gmn/codes/cup/model/emotion_v5_stage2"
export EMOTION_BASE_MODEL_PATH="/home/gmn/codes/cup/model/emotion_stage1"
export EMOTION_BERT_PATH="/home/huggingface/bert-base-uncased"
export EMOTION_INFERENCE_SCRIPT="/home/gmn/codes/cup/services/emotion/inference_adapter.py"
export EMOTION_PYTHON="/home/gmn/.conda/envs/softcup/bin/python"
export EMOTION_GPU="2"

# 可选：历史数据位置、超时与是否保留原始文件
export TOURISM_DATASET_PATH="/path/to/景点景区旅游数据行为分析数据.xlsx"
export EMOTION_TIMEOUT_SECONDS="180"
export EMOTION_KEEP_MEDIA="false"
```

LoRA 权重不是完整模型。还需要训练脚本默认使用且包含音频塔/投影层的
`emotion_stage1` 基座；当前 `HumanOmni-7B-Video` 配置只有视觉塔，不能替代语音
情绪基座。`EMOTION_PYTHON` 必须能导入训练时修改过的 `humanomni`
（包括 `model_init`、返回三元组的 `mm_infer` 和
`emotion_probs_from_logits`）、`peft` 和 `torch`。官方 HumanOmni 只返回生成文本，
无法从该 Stage2 任务取得七分类结果，状态接口会将其判定为不可用并执行文本降级。
若模型、基础模型、脚本或 Python 环境缺失，`/v1/admin/emotion/status` 会返回具体原因；
语音事件会生成 ASR 文本降级结果，而不会把规则结果标记为真实多模态推理。七类情绪与
XLSX 的 `satisfaction` 含义不同，后者仅用于历史统计和融合校准，不能直接充当七分类标签。

配置完成后重启并检查：

```bash
cd /home/gmn/codes/cup
bash deploy/start_api.sh
curl -ksS https://127.0.0.1:8444/v1/admin/emotion/status  # 该接口需先登录，亦可在后台查看
```

## 主要接口（给客户端）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat` | 导览问答（`model_route=cloud|local`，`stream=true` 为 SSE） |
| GET | `/v1/model-routes` | 查询云端与本地问答路径状态 |
| POST | `/v1/tts` | 智谱 GLM-TTS，返回 wav |
| POST | `/v1/tts/stream` | 流式 PCM/SSE（Live2D 回退使用） |
| GET | `/v1/livetalking/status` | LiveTalking 本地服务状态 |
| POST | `/v1/livetalking/start` | 确保 LiveTalking CPU 待机实例可用 |
| POST | `/v1/livetalking/offer` | WebRTC 信令代理 |
| POST | `/v1/livetalking/speak` | 按句流式 PCM 合成并送入口型 |
| POST | `/v1/livetalking/interrupt` | 打断当前播报 |
| POST | `/v1/livetalking/is-speaking` | 查询播报状态 |
| GET | `/v1/xmov/config` | XMOV 浏览器配置状态（显式开启才返回凭据） |
| POST | `/v1/asr` | 智谱语音识别，上传音频文件 |
| GET | `/v1/attractions` | DOCX 来源的景区与子景点评分目录 |
| POST | `/v1/recommend` | 按兴趣推荐路线 |
| POST | `/v1/locate` | 多源定位 gps/qr/wifi/manual，含精度、时效、置信度与降级提示 |
| POST | `/v1/vision/guide` | 上传图片导览 |
| GET | `/v1/routes` | 路线列表 |
| GET | `/v1/kb/stats` | 知识库状态 |
| POST | `/v1/kb/rebuild` | 重建 BGE-M3/FAISS 索引（仅登录后的管理端口） |
| GET | `/v1/stats/overview` | 运营概览 |
| POST | `/v1/feedback` | 游客对指定景区/子景点的满意度与意见反馈 |
| GET | `/v1/admin/analytics/overview` | 管理端实时运营、情感、方面和建议聚合 |
| GET | `/v1/admin/analytics/historical` | XLSX 历史游客行为聚合结果 |
| POST | `/v1/admin/analytics/historical/rebuild` | 强制重建 XLSX 聚合缓存 |
| GET | `/v1/admin/emotion/status` | 查询多模态模型和推理适配器状态 |
| GET | `/v1/admin/emotion/events/{job_id}` | 查询情感任务状态与结构化结果 |
| GET/POST | `/v1/admin/kb/documents` | 查询或上传/更新知识文档 |
| DELETE | `/v1/admin/kb/documents/{filename}` | 删除管理员上传的知识文档 |
| GET/PUT | `/v1/admin/avatar` | 查询或更新数字人形象与声音配置（后台提供真人预览卡片） |

浏览器首页已含 **LiveTalking Wav2Lip 本地真人口型（Live2D 自动回退）+ 按句流式问答 + 语音/图片输入 + 游客反馈**；独立管理端口 `8444` 提供知识库、数字人和游客洞察管理。后台使用服务端签名的 HttpOnly/Secure 会话 Cookie；游客端口不能直接调用管理接口。

正式部署前应通过环境变量修改默认凭据，并使用固定的随机会话密钥：

```bash
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="请替换为强密码"
export ADMIN_SESSION_SECRET="请替换为至少 32 字节的随机值"
```

## GPS 弱信号与难定位方案

首页“智能定位 / 弱信号”采用可解释的四级降级链：

1. GPS：联合校验浏览器上报的精度、位置时效、最近景点距离；低精度、过期或超出标定范围时只给候选点，不自动认定位置。
2. 景点二维码：二维码携带固定点位码（例如 `/?spot=LS-006`），适合室内和建筑遮挡区域。
3. 景区 Wi-Fi：由网关把接入点编号映射到景区区域，只提供区域级定位，并要求游客确认。
4. 手动选择：作为始终可用的最终兜底，不依赖定位权限和无线信号。

接口会返回 `confidence`、`requires_confirmation`、`reason` 和 `fallbacks`，前端据此决定直接讲解、请求确认或显示降级入口。`app/location.py` 内坐标为演示标定点，生产部署应替换为景区审核的 WGS-84 点位，并由锐捷网关传入真实 AP 编号。

### 聊天示例

```bash
curl -X POST http://127.0.0.1:8001/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"灵山大佛有多高？","interest":"历史","stream":false}'
```

对外文字访问放行 **8001**；麦克风访问放行 **8443**；管理后台单独放行 **8444**。8010 仅供本机 API 代理使用。
Key 勿提交仓库，用环境变量 `ZHIPU_API_KEY` 或根目录现有密钥文件。
