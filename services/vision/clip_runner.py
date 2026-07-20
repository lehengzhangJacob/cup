"""SigLIP/CLIP model loading and image encoding (runs in the softcup env).

Kept dependency-heavy (torch + transformers) on purpose: this module is only
imported by the softcup-side socket service and the offline index builder, never
by the API process. The API talks to it over a Unix socket.
"""
from __future__ import annotations

import io
import os
from typing import Any

os.environ.setdefault("PYTORCH_NVML_BASED_CUDA_CHECK", "1")

import numpy as np
import torch
from PIL import Image, UnidentifiedImageError


_MODEL_CACHE: dict[str, Any] = {}


def load_model(model_path: str, device: str = "cpu"):
    """Lazy-load a SigLIP/CLIP vision model+processor once per process."""
    key = f"{model_path}|{device}"
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    from transformers import AutoModel, AutoProcessor  # local import: heavy

    processor = AutoProcessor.from_pretrained(model_path)
    model = AutoModel.from_pretrained(model_path).eval()
    target = torch.device(device)
    model.to(target)
    if device.startswith("cuda"):
        model = model.half()
    _MODEL_CACHE[key] = (model, processor, target)
    return _MODEL_CACHE[key]


def _to_tensor(jpeg_bytes: bytes):
    with Image.open(io.BytesIO(jpeg_bytes)) as image:
        image = image.convert("RGB")
        return image


def encode_pil(model, processor, device, images: list, *, batch: int = 8) -> np.ndarray:
    target = torch.device(device)
    out: list[np.ndarray] = []
    for start in range(0, len(images), batch):
        chunk = images[start : start + batch]
        inputs = processor(images=chunk, return_tensors="pt")
        inputs = {k: v.to(target) for k, v in inputs.items()}
        if device.startswith("cuda"):
            inputs = {k: v.half() if v.dtype == torch.float32 else v for k, v in inputs.items()}
        with torch.inference_mode():
            feats = model.get_image_features(**inputs)
        feats = feats / feats.norm(dim=-1, keepdim=True).clamp(min=1e-8)
        out.append(feats.float().cpu().numpy())
    if not out:
        return np.zeros((0, 768), dtype=np.float32)
    return np.concatenate(out, axis=0).astype(np.float32)


def encode_bytes(model, processor, device, jpeg_bytes_list: list[bytes]) -> np.ndarray:
    images = []
    for raw in jpeg_bytes_list:
        try:
            images.append(_to_tensor(raw))
        except (UnidentifiedImageError, OSError, ValueError):
            images.append(Image.new("RGB", (224, 224)))  # placeholder keeps indexing aligned
    return encode_pil(model, processor, device, images)
