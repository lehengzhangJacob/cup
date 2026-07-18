from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # /home/softcup/cup
KEY_FILE = ROOT / "softcup_glmkey"
DATA_DIR = ROOT / "data" / "lingshan"
DOCS_DIR = ROOT / "资料" / "示范景区公开资料包"
KB_PATH = DATA_DIR / "kb_chunks.json"
LOG_DB = DATA_DIR / "server.db"

ZHIPU_BASE = os.getenv("ZHIPU_BASE", "https://open.bigmodel.cn/api/paas/v4")
CHAT_MODEL = os.getenv("ZHIPU_CHAT_MODEL", "glm-4-flash")
VISION_MODEL = os.getenv("ZHIPU_VISION_MODEL", "glm-4v-flash")
EMBED_MODEL = os.getenv("ZHIPU_EMBED_MODEL", "embedding-3")
TTS_MODEL = os.getenv("ZHIPU_TTS_MODEL", "glm-tts")
TTS_VOICE = os.getenv("ZHIPU_TTS_VOICE", "female")
ASR_MODEL = os.getenv("ZHIPU_ASR_MODEL", "glm-asr")

HOST = os.getenv("API_HOST", "0.0.0.0")
PORT = int(os.getenv("API_PORT", "8000"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


def load_api_key() -> str:
    key = os.getenv("ZHIPU_API_KEY", "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    raise RuntimeError("ZHIPU_API_KEY not set and softcup_glmkey missing")
