"""Safe, deterministic preparation of visitor and reference scenic images."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_INPUT_PIXELS = 32_000_000
MAX_EDGE = 1600


class ImageValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    mime_type: str
    width: int
    height: int
    original_format: str
    sha256: str


def normalize_scenic_image(raw: bytes, *, max_bytes: int = MAX_INPUT_BYTES) -> PreparedImage:
    """Decode, orient and compress a scenic image to a model-safe JPEG.

    The vision provider must receive the actual encoded MIME type. Normalizing
    PNG/HEIC-compatible browser uploads to JPEG also avoids the former
    hard-coded ``data:image/jpeg`` mismatch.
    """
    if not raw:
        raise ImageValidationError("图片为空")
    if len(raw) > max_bytes:
        raise ImageValidationError(f"图片不能超过 {max_bytes // 1024 // 1024}MB")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            original_format = str(probe.format or "unknown").upper()
            width, height = probe.size
            if width <= 0 or height <= 0 or width * height > MAX_INPUT_PIXELS:
                raise ImageValidationError("图片分辨率异常或过大")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            elif image.mode == "L":
                image = image.convert("RGB")
            image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            normalized = output.getvalue()
            width, height = image.size
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageValidationError("无法解析图片，请使用清晰的 JPG、PNG 或已转换的 HEIC 图片") from exc
    return PreparedImage(
        data=normalized,
        mime_type="image/jpeg",
        width=width,
        height=height,
        original_format=original_format,
        sha256=hashlib.sha256(normalized).hexdigest(),
    )
