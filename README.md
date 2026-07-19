# 灵山胜境 AI 数字人导览

第十五届中国软件杯 A5「景区导览服务 AI 数字人」参赛项目。系统包含游客交互端、
LiveTalking Wav2Lip 本地数字人、本地景区 RAG 知识库、云端/本地双模型问答和景区运营后台。

## 已实现功能

- 游客端：文字/语音问答、按句流式播报、口型同步、情绪驱动、拍照识景、弱定位导览、个性化路线和满意度反馈。
- 管理端：运营数据大屏、热门问题、情感趋势、满意度报告、服务建议、知识文档上传/更新/删除和数字人形象配置。
- AI 能力：BGE-M3 在本地生成向量、FAISS 检索景区资料，问答可在 GLM-4.7-Flash API 与本地 Qwen2-7B-Instruct 间切换；GLM-4V、GLM-ASR、GLM-TTS 继续负责视觉和语音。
- 数字人：空闲时使用不占 GPU 的 Haru Live2D；首次互动按需启动 LiveTalking + Wav2Lip FP16。

## 快速访问

- 游客文字端：`http://<服务器IP>:8001/`
- 游客麦克风端：`https://<服务器IP>:8443/`
- 景区管理后台：`https://<服务器IP>:8444/admin`
- OpenAPI 文档：`http://<服务器IP>:8001/docs`

当前服务器局域网 IP 为 `192.168.200.27`。浏览器不在服务器本机时，不要使用
`localhost`。

## 启动

```bash
source /home/anaconda/etc/profile.d/conda.sh
conda activate ccc
cd /home/gmn/codes/cup

# 智谱 API 密钥保存在项目根目录 softcup_glmkey，也可设置 ZHIPU_API_KEY

bash deploy/start_api.sh

# 可选：预热或立即停止 LiveTalking（默认物理 GPU 2）
bash deploy/start_livetalking.sh
bash deploy/stop_livetalking.sh
```

`start_api.sh` 会先启动仅监听本机 8020 的 BGE-M3/FAISS RAG 服务和本地模型网关，
但不会预载 7B 权重。只有网页选择“本地
Qwen2-7B”后才占用约 15GB 显存，空闲 120 秒会自动卸载；默认 GLM API 路径不加载
本地权重。也可用 `bash deploy/stop_local_llm.sh` 立即停止并释放显存。

LiveTalking 同样按需使用显存：页面打开时只运行 Live2D，首次互动自动启动
LiveTalking，最后一次使用 120 秒后自动停止。活动时本机实测约占 760 MiB 显存。

RAG 的接口、流式事件和会话边界见 [llm/README.md](llm/README.md)。详细说明见
[部署与使用手册](docs/部署与使用手册.md) 和
[总体设计文档](docs/总体设计文档.md)。

## 验证

```bash
curl http://127.0.0.1:8001/health
cd services/api
python scripts/eval_accuracy.py
```

当前标准事实题评测结果为 `15/15 = 100%`；已完成一次“语音输入结束至首个非静音
数字人音频帧”实测，延迟为 `3373ms`。
