# 灵山胜境 AI 数字人导览

第十五届中国软件杯 A5「景区导览服务 AI 数字人」参赛项目。系统包含游客交互端、
LiveTalking Wav2Lip 本地数字人、本地景区 RAG 知识库、云端/本地双模型问答和景区运营后台。

## 已实现功能

- 游客端：文字/语音问答、按句流式播报、实时口型同步（LiveTalking/Wav2Lip）、Live2D 表情模式（按情绪切换）、拍照识景、弱定位导览、个性化路线和满意度反馈。游客侧情绪分析为音频—文本多模态（不采集人脸视频）。
- 管理端：运营数据大屏、热门问题、情感趋势、满意度报告、服务建议、知识文档上传/更新/删除和数字人形象配置。
- AI 能力：BGE-M3 在本地生成向量、FAISS 检索景区资料，问答可在部署环境配置的 GLM API 与本地 Qwen2-7B-Instruct 间切换；GLM-4V、GLM-ASR、GLM-TTS 继续负责视觉和语音。
- 数字人：打开游客网页后按需启动 LiveTalking + Wav2Lip FP16；网页关闭或隐藏后空闲自动释放 GPU。

## 快速访问

- 游客文字端：`http://<服务器IP>:8001/`
- 游客麦克风端：`https://<服务器IP>:8443/`
- 景区管理后台：`https://<服务器IP>:8444/admin`
- OpenAPI 文档：`http://<服务器IP>:8001/docs`
- 安卓 APK：`http://139.159.150.134:20080/static/downloads/lingshan-guide-v1.0.2.apk`

当前服务器局域网 IP 为 `192.168.200.27`。浏览器不在服务器本机时，不要使用
`localhost`。

## 启动

```bash
source /home/anaconda/etc/profile.d/conda.sh
conda activate ccc
cd /home/gmn/codes/cup

# 智谱 API 密钥保存在项目根目录 softcup_glmkey，也可设置 ZHIPU_API_KEY

bash deploy/start_api.sh

# 可选：启动 CPU 待机实例或完全停止 LiveTalking
bash deploy/start_livetalking.sh
bash deploy/stop_livetalking.sh
```

`start_api.sh` 会先启动仅监听本机 8020 的 BGE-M3/FAISS RAG 服务和本地模型网关，
但不会预载 7B 权重。只有网页选择“本地
Qwen2-7B”后才占用约 15GB 显存，空闲 120 秒会自动卸载；默认 GLM API 路径不加载
本地权重。也可用 `bash deploy/stop_local_llm.sh` 立即停止并释放显存。

LiveTalking 权重和头像常驻 CPU/RAM，不访问时不把模型放在 GPU。建立 WebRTC
会话时会在物理 GPU 0–3 中选择利用率低且至少剩余 2GB 的卡，关闭最后一个会话
2 秒后把模型移回 CPU；活动时本机实测约占 756MiB 显存。

RAG 的接口、流式事件和会话边界见 [llm/README.md](llm/README.md)。详细说明见
[部署与使用手册](docs/部署与使用手册.md) 和
[总体设计文档](docs/总体设计文档.md)。

## 验证

```bash
curl http://127.0.0.1:8001/health
cd services/api
python scripts/eval_accuracy.py
```

当前 15 题事实冒烟基线为 `15/15`；它不是赛题 90% 准确率的最终证明。赛前应使用不少于 80 道专家复核题并保留引用与人工评分报告。已建立 85 题冻结评测集 `llm/tests/fixtures/rag_fact_benchmark_frozen.json`（覆盖事实/路线、同义问法、模糊问法、跨景区混淆、无资料拒答、知识冲突、提示注入），用 `llm/scripts/evaluate_fact_benchmark.py` 评测并输出分类报告；关键词命中仅为自动化预检，事实正确性需人工复核。已完成一次“语音输入结束至首个非静音
数字人音频帧”实测，延迟为 `3373ms`。

2026-07-19 热链路三次复测中，“发送文字 → 首个非静音音频”中位数为
`2987ms`，“发送文字 → 最后非静音音频”为 `9387ms`；优化前分别为
`3459ms` 和 `12189ms`。测试方法、分阶段数据和复测命令见
[文字到语音端到端延迟测试与优化](docs/文字到语音端到端延迟测试与优化.md)。
