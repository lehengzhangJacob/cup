# 游客对话多模态情绪推理

本目录只服务于游客与数字人对话产生的情绪分析，不提供管理员上传音频或视频的入口。
游客语音经明确授权后，API 将原声、ASR 转写和最近对话上下文交给
`inference_adapter.py`；推理完成后默认删除原始媒体，只把七分类结果和降级状态写入
SQLite。

## 模型组成

- 多模态基座：`model/emotion_stage1`
- 情绪 LoRA：`model/emotion_v5_stage2`
- 文本编码器：`/home/huggingface/bert-base-uncased`
- HumanOmni 源码：`services/emotion/humanomni`

当前内置源码来自官方 HumanOmni 仓库，基线提交为
`26fa491492d39a66eef0d9e805c7bf33bf2cb0ee`，用于复现环境和模型加载。它不是最终
七分类运行时：该 Stage2 的原始 `inference.py` 依赖训练分支新增的
`emotion_probs_from_logits`，并要求 `mm_infer` 返回输出、logits 和七分类分数。
部署前必须将训练时实际导入的 `humanomni` 包同步到本目录；状态接口在扩展缺失时会
明确显示文本降级，避免把模型生成的 `positive/neutral/negative` 误当成七分类。

## softcup 环境

先保留与服务器 CUDA 匹配的 PyTorch，再安装兼容依赖：

```bash
/home/gmn/.conda/envs/softcup/bin/python -m pip install \
  -r /home/gmn/codes/cup/services/emotion/requirements-softcup.txt
```

预检不会加载完整权重：

```bash
cd /home/gmn/codes/cup/services/emotion
/home/gmn/.conda/envs/softcup/bin/python -c \
  "from humanomni import model_init, mm_infer, emotion_probs_from_logits; import peft, torch; print(torch.cuda.is_available())"
```

真实烟测会加载 Stage1、视觉塔、音频塔、BERT 和 Stage2 LoRA，建议使用至少约 20 GB
空闲显存且没有训练任务的 GPU。API 默认使用 `EMOTION_GPU=3`，单个 API 进程内会串行
执行本地情绪任务；游客问答不会等待后台情绪任务完成。

本地模式当前每个任务都会启动推理子进程并加载模型，适合比赛演示和低并发验证。若要
持续运营，建议把同一适配器改造成常驻单模型 HTTP 服务，并配置
`EMOTION_INFERENCE_URL`，避免重复加载。
