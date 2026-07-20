# 情绪七分类评测集采集规范

本目录用于对部署的七分类情绪模型（HumanOmni 基座 + emotion_v5_stage2 LoRA）做正式评测：
混淆矩阵、Macro-F1、每类召回、音频+文本 vs 纯文本对比、P95 时延。
评测脚本：`services/api/scripts/eval_emotion_seven_class.py`。

> 当前目录为空（样本待采集）。脚本已就绪，缺样本时跑 self-consistency 冒烟并报告 SKIP。

## 采集要求

- 七类各 ≥30 条样本（angry / disgust / fear / happy / neutral / sad / surprise）。
- 每条样本包含：
  - `audio`：短音频文件（wav/mp3/m4a，≤30s），放本目录下；
  - `transcript`：对应 ASR 文本；
  - `label`：人工标注的七类真值（小写英文）。
- 音频需为真实游客式语音（不同说话人、不同情绪强度），避免单一合成样本。
- **音频+文本评测**与**纯文本评测**用同一批样本，便于对照多模态相对纯文本的提升。

## manifest.json

```json
{
  "version": 1,
  "items": [
    {"audio": "happy_01.wav", "transcript": "这里太美了，非常开心！", "label": "happy"},
    {"audio": "sad_02.wav", "transcript": "有点累，心情低落。", "label": "sad"}
  ]
}
```

## 运行评测

```bash
# 需 emotion 推理环境就绪（services/emotion/inference_adapter.py + 模型权重）
conda activate softcup   # 或配置 EMOTION_INFERENCE_URL 指向常驻推理服务
cd services/api
python scripts/eval_emotion_seven_class.py
```

输出文本降级与音频+文本两套指标，含 Macro-F1、每类 P/R/F1、混淆矩阵、P95 时延，
并写入 `report_latest.json`。
