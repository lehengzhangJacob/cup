# 灵山胜境 AI 数字人导览 · 开放 API

本机为服务器，对外提供 HTTP 接口；大模型调用智谱 GLM（服务端持有 key）。

## 环境（Miniconda）

```bash
source /home/anaconda/etc/profile.d/conda.sh
conda activate ccc
```

## 启动

```bash
cd /home/gmn/codes/cup
bash deploy/start_livetalking.sh  # 默认物理 GPU 1、端口 8010
bash deploy/start_api.sh          # HTTP 8001 + HTTPS 8443
```

- 健康检查：`GET /health`
- Swagger：`http://<服务器IP>:8001/docs`
- 浏览器联调页：`http://<服务器IP>:8001/`
- 麦克风页面：`https://<服务器IP>:8443/`（首次访问接受自签名证书）

可用 `LIVETALKING_GPU=1` 显式选择物理显卡；后台日志位于
`deploy/livetalking/service.log`、`deploy/api.log` 和 `deploy/api-ssl.log`。

## LiveTalking 本地真人数字人

项目使用仓库内的 `LiveTalking/`，Wav2Lip 权重和头像分别位于：

- `LiveTalking/models/wav2lip.pth`
- `LiveTalking/data/avatars/wav2lip256_avatar1/`

运行环境为 `ccc`（Python 3.12、PyTorch 2.5.1+cu121）。Wav2Lip 使用 FP16 和
batch 8，以降低 GPU 1 显存峰值。浏览器通过本站同源 API 完成 WebRTC 信令，
页面不直接暴露 8010 的 HTTP 接口。

问答采用按句流水线：ASR → GLM 流式首句 → GLM-TTS PCM 分块 →
LiveTalking Wav2Lip。PCM 分块到达即上传，不等待整段语音合成结束；服务不可用时
自动回退到 GLM-TTS + Haru Live2D，并每 10 秒自动重连。

2026-07-19 本机实测“语音输入结束 → 第一个非静音 WebRTC 音频帧”为 3373ms：
ASR 451ms、LLM 首句 1151ms、TTS/口型 1772ms。实际延迟会随外部模型接口和
GPU 1 上其他任务的负载波动。

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
| POST | `/v1/chat` | 导览问答（`stream=true` 为 SSE） |
| POST | `/v1/tts` | 智谱 GLM-TTS，返回 wav |
| POST | `/v1/tts/stream` | 流式 PCM/SSE（Live2D 回退使用） |
| GET | `/v1/livetalking/status` | LiveTalking 本地服务状态 |
| POST | `/v1/livetalking/offer` | WebRTC 信令代理 |
| POST | `/v1/livetalking/speak` | 按句流式 PCM 合成并送入口型 |
| POST | `/v1/livetalking/interrupt` | 打断当前播报 |
| POST | `/v1/livetalking/is-speaking` | 查询播报状态 |
| GET | `/v1/xmov/config` | XMOV 浏览器配置状态（显式开启才返回凭据） |
| POST | `/v1/asr` | 智谱语音识别，上传音频文件 |
| POST | `/v1/recommend` | 按兴趣推荐路线 |
| POST | `/v1/locate` | 弱定位 gps/qr/manual/wifi |
| POST | `/v1/vision/guide` | 上传图片导览 |
| GET | `/v1/routes` | 路线列表 |
| GET | `/v1/kb/stats` | 知识库状态 |
| GET | `/v1/stats/overview` | 运营概览 |

浏览器首页已含 **LiveTalking Wav2Lip 本地真人口型（Live2D 自动回退）+ 按句流式问答 + 语音输入**。

### 聊天示例

```bash
curl -X POST http://127.0.0.1:8001/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"灵山大佛有多高？","interest":"历史","stream":false}'
```

对外文字访问放行 **8001**；麦克风访问放行 **8443**。8010 仅供本机 API 代理使用。
Key 勿提交仓库，用环境变量 `ZHIPU_API_KEY` 或根目录现有密钥文件。
