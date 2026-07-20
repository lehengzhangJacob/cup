# 识景测试集采集规范

本目录用于评估 CLIP/SigLIP 景点图集召回的 Top-K 准确率。`scripts/eval_vision_recall.py`
会读取 `manifest.json`，对每张图编码后在参考图索引中召回，输出 Recall@1/3/5、按景点/
天气/角度分桶与混淆矩阵。

> 当前目录为空（图片待采集）。代码与评测脚本已就绪，补齐图片后即可运行。

## 采集要求

- **每个子景点 20–50 张**照片，覆盖：
  - 天气：晴天 / 阴天 / 雨天 / 雾天 / 夜景
  - 角度：正面 / 侧面 / 背面 / 俯拍 / 特写
  - 季节：春夏秋冬（如条件允许）
  - 时段：白天 / 黄昏 / 夜间
- 子景点目录与 `attraction_id` 一致（见 `services/api/app/attractions.py`），例如：
  ```
  vision_eval/
    LS-011/  灵山大佛
      sunny_front_01.jpg
      cloudy_side_02.jpg
      night_03.jpg
    NH-003/  香月花街
      evening_01.jpg
    ...
  ```
- 图片为 JPG，单张 ≤8MB，分辨率不限（管线会统一缩放到 1600 边长）。
- **测试集图片必须与参考图集（`data/lingshan/vision_references/`）分开采集**，不得复用，
  否则召回评测会虚高。

## manifest.json

按 `manifest.schema.json` 填写，每张图一条记录，至少包含 `file` 与 `attraction_id`（真值）。
`weather`/`angle`/`season` 用于分桶评测（阴天召回率、夜景召回率等）。

## 运行评测

```bash
# 1. 先建参考图索引（需 softcup 环境的 CLIP 服务）
conda activate softcup
bash deploy/start_clip_embedder.sh
python services/api/scripts/build_vision_index.py --force

# 2. 跑召回评测
python services/api/scripts/eval_vision_recall.py --top-k 5 --bucket weather
```

图集为空或 CLIP 服务未启动时，脚本会 skip 并给出提示，不会报错。
