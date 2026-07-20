"""Lightweight image quality assessment for the vision-recognition pipeline.

Detects blur (Laplacian variance) and exposure problems (histogram extremes)
using only PIL + numpy so the API process keeps a small dependency footprint.
The result is advisory: the pipeline rejects only severely degraded images
and otherwise down-weights low-quality ones rather than blocking them.
"""
from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from . import config


@dataclass(frozen=True)
class QualityReport:
    flag: str  # accept | warn | reject
    sharpness: float  # Laplacian variance, higher = sharper
    brightness: float  # mean luminance 0-255
    laplacian_var: float
    advice: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _laplacian_variance(gray: np.ndarray) -> float:
    """Approximate OpenCV's Laplacian variance with a pure-numpy kernel."""
    if gray.size == 0:
        return 0.0
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    g = gray.astype(np.float32)
    # Reflect padding keeps the border stable.
    padded = np.pad(g, 1, mode="edge")
    out = (
        padded[0:-2, 0:-2] * kernel[0, 0] + padded[0:-2, 1:-1] * kernel[0, 1] + padded[0:-2, 2:] * kernel[0, 2]
        + padded[1:-1, 0:-2] * kernel[1, 0] + padded[1:-1, 1:-1] * kernel[1, 1] + padded[1:-1, 2:] * kernel[1, 2]
        + padded[2:, 0:-2] * kernel[2, 0] + padded[2:, 1:-1] * kernel[2, 1] + padded[2:, 2:] * kernel[2, 2]
    )
    return float(out.var())


def assess_scenic_quality(raw: bytes) -> QualityReport:
    """Return an advisory quality report for a raw image buffer."""
    if not raw:
        return QualityReport("reject", 0.0, 0.0, 0.0, "图片为空")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("L")
            # Downsample before the convolution; quality signal is stable at
            # this resolution and it keeps the cost bounded for large photos.
            image.thumbnail((512, 512))
            gray = np.asarray(image, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return QualityReport("reject", 0.0, 0.0, 0.0, f"无法解析图片：{exc}")

    lap = _laplacian_variance(gray)
    brightness = float(gray.mean())
    blur_thresh = config.VISION_QUALITY_BLUR_LAPLACIAN
    low_b = config.VISION_QUALITY_BRIGHT_LOW
    high_b = config.VISION_QUALITY_BRIGHT_HIGH

    too_dark = brightness < low_b
    too_bright = brightness > high_b
    too_blur = lap < blur_thresh

    if too_blur and (too_dark or too_bright):
        flag = "reject"
        advice = "图片严重模糊且曝光异常，请重新拍摄清晰的照片"
    elif too_blur:
        flag = "warn"
        advice = "图片较模糊，识别结果可能不准确，建议靠近后重拍"
    elif too_dark:
        flag = "warn"
        advice = "图片偏暗，识别结果可能不准确，建议补光后重拍"
    elif too_bright:
        flag = "warn"
        advice = "图片偏亮/过曝，识别结果可能不准确，建议调整角度后重拍"
    else:
        flag = "accept"
        advice = ""
    return QualityReport(flag, round(lap, 2), round(brightness, 2), round(lap, 2), advice)
