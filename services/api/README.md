# 灵山胜境 AI 数字人导览 · 开放 API

本机为服务器，对外提供 HTTP 接口；大模型调用智谱 GLM（服务端持有 key）。

## 环境（Miniconda）

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate softcup
```

## 启动

```bash
bash /home/softcup/cup/deploy/start_api.sh
# 或
export ZHIPU_API_KEY="$(cat /home/softcup/cup/softcup_glmkey)"
cd /home/softcup/cup/services/api
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- 健康检查：`GET /health`
- Swagger：`http://<服务器IP>:8000/docs`
- 浏览器联调页：`http://<服务器IP>:8000/`

## 主要接口（给客户端）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat` | 导览问答（`stream=true` 为 SSE） |
| POST | `/v1/tts` | 智谱 GLM-TTS，返回 wav |
| POST | `/v1/asr` | 智谱语音识别，上传音频文件 |
| POST | `/v1/recommend` | 按兴趣推荐路线 |
| POST | `/v1/locate` | 弱定位 gps/qr/manual/wifi |
| POST | `/v1/vision/guide` | 上传图片导览 |
| GET | `/v1/routes` | 路线列表 |
| GET | `/v1/kb/stats` | 知识库状态 |
| GET | `/v1/stats/overview` | 运营概览 |

浏览器首页已含 **数字人（口型同步）+ 按住说话 + TTS 播报**。

### 聊天示例

```bash
curl -X POST http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"灵山大佛有多高？","interest":"历史","stream":false}'
```

安全组需放行 **8000** 端口。Key 勿提交仓库，用环境变量 `ZHIPU_API_KEY`。
