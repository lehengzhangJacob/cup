# 灵山胜境 AI 数字人导览 · 开放 API

本机为服务器，对外提供 HTTP 接口；问答支持 GLM API 与本地 Qwen2-7B 双路径，视觉、ASR 和 TTS 保持智谱 GLM API。

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
`glm-4.7-flash` 的非思考模式。

- 健康检查：`GET /health`
- Swagger：`http://<服务器IP>:8001/docs`
- 浏览器联调页：`http://<服务器IP>:8001/`
- 麦克风页面：`https://<服务器IP>:8443/`（首次访问接受自签名证书；8443 同时承载 TURN/TCP，可穿过 SSH/IDE TCP 端口转发）
- 景区管理后台：`https://<服务器IP>:8444/admin`（独立端口；默认账号 `admin`，默认密码 `123456abc`）

LiveTalking 无需常驻启动：打开游客网页且网络可用时自动在物理 GPU 2 启动，网页可见期间保持热状态；关闭或隐藏网页 120 秒后自动停止。可用 `LIVETALKING_GPU=2` 和 `LIVETALKING_IDLE_SECONDS=120` 调整；后台日志位于
`deploy/livetalking/service.log`、`deploy/rag.log`、`deploy/local-llm.log` 和
`deploy/api.log`；RAG 自动恢复记录位于 `deploy/rag-watchdog.log`。

## 云端 / 本地问答双路径

- 网页默认选择 `GLM API`，不会加载本地 7B 权重。
- 选择 `本地 Qwen2-7B` 后，RAG 使用 `/home/huggingface/Qwen2-7B-Instruct`；冷加载实测约 15–60 秒，热请求生成很快。
- `transformers serve` 在本机 `8021` 提供 OpenAI 兼容接口，本地路径空闲 120 秒后会停止该进程并释放显存；下次请求自动重启。
- 手动启动或停止：`bash deploy/start_local_llm.sh`、`bash deploy/stop_local_llm.sh`。
- 本机实测服务空载时 GPU 2 保持 `781MiB`，模型加载后约 `15.7GiB`。本地路径适合离线或 API 故障备份；要求稳定 4–5 秒首答时优先使用云端路径。

`POST /v1/chat` 的 `model_route` 可设为 `cloud` 或 `local`；语音识别、语音合成和数字人口型链路不随该选项改变。

两种生成路径之前都使用同一套本地 BGE-M3 + FAISS 检索。`stream=true` 时接口按
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
batch 8，以降低 GPU 2 显存峰值。浏览器通过本站同源 API 完成 WebRTC 信令，
页面不直接暴露 8010 的 HTTP 接口。

问答采用按句流水线：ASR → 所选模型流式首句 → GLM-TTS PCM 分块 →
LiveTalking Wav2Lip。PCM 分块到达即上传，不等待整段语音合成结束；服务不可用时
自动回退到 GLM-TTS + Haru Live2D。

打开游客网页且网络可用时会启动 LiveTalking，并在网页可见期间每 30 秒刷新空闲计时；关闭或隐藏网页 120 秒后由 `deploy/watch_livetalking.sh` 自动停止并释放约 760 MiB 显存。可用 `bash deploy/start_livetalking.sh` 预热，或用 `bash deploy/stop_livetalking.sh` 立即释放显存。

2026-07-19 本机实测“语音输入结束 → 第一个非静音 WebRTC 音频帧”为 3373ms：
ASR 451ms、LLM 首句 1151ms、TTS/口型 1772ms。实际延迟会随外部模型接口和
GPU 2 上其他任务的负载波动。

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

## 主要接口（给客户端）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat` | 导览问答（`model_route=cloud|local`，`stream=true` 为 SSE） |
| GET | `/v1/model-routes` | 查询云端与本地问答路径状态 |
| POST | `/v1/tts` | 智谱 GLM-TTS，返回 wav |
| POST | `/v1/tts/stream` | 流式 PCM/SSE（Live2D 回退使用） |
| GET | `/v1/livetalking/status` | LiveTalking 本地服务状态 |
| POST | `/v1/livetalking/start` | 按需启动 LiveTalking 并刷新空闲计时 |
| POST | `/v1/livetalking/offer` | WebRTC 信令代理 |
| POST | `/v1/livetalking/speak` | 按句流式 PCM 合成并送入口型 |
| POST | `/v1/livetalking/interrupt` | 打断当前播报 |
| POST | `/v1/livetalking/is-speaking` | 查询播报状态 |
| GET | `/v1/xmov/config` | XMOV 浏览器配置状态（显式开启才返回凭据） |
| POST | `/v1/asr` | 智谱语音识别，上传音频文件 |
| POST | `/v1/recommend` | 按兴趣推荐路线 |
| POST | `/v1/locate` | 多源定位 gps/qr/wifi/manual，含精度、时效、置信度与降级提示 |
| POST | `/v1/vision/guide` | 上传图片导览 |
| GET | `/v1/routes` | 路线列表 |
| GET | `/v1/kb/stats` | 知识库状态 |
| POST | `/v1/kb/rebuild` | 重建 BGE-M3/FAISS 索引（仅登录后的管理端口） |
| GET | `/v1/stats/overview` | 运营概览 |
| POST | `/v1/feedback` | 游客满意度与意见反馈 |
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
