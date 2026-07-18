from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # /home/softcup/cup
KEY_FILE = ROOT / "softcup_glmkey"
DATA_DIR = ROOT / "data" / "lingshan"
DOCS_DIR = ROOT / "资料" / "示范景区公开资料包"
UPLOADS_DIR = DATA_DIR / "knowledge_uploads"
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

XMOV_BROWSER_CONFIG_ENABLED = os.getenv("XMOV_BROWSER_CONFIG_ENABLED", "false").lower() in {"1", "true", "yes"}
XMOV_APP_ID = os.getenv("XMOV_APP_ID", "").strip()
XMOV_APP_SECRET = os.getenv("XMOV_APP_SECRET", "").strip()
XMOV_SESSION_GATEWAY_URL = os.getenv(
    "XMOV_SESSION_GATEWAY_URL",
    "https://nebula-agent.xingyun3d.com/user/v1/ttsa/session",
).strip()
XMOV_AUTH_HEADER = os.getenv("XMOV_AUTH_HEADER", "").strip()
XMOV_SDK_URL = os.getenv(
    "XMOV_SDK_URL",
    "https://media.xingyun3d.com/xingyun3d/general/litesdk/xmovAvatar@latest.js",
).strip()

LIVETALKING_ENABLED = os.getenv("LIVETALKING_ENABLED", "true").lower() in {"1", "true", "yes"}
LIVETALKING_URL = os.getenv("LIVETALKING_URL", "http://127.0.0.1:8010").rstrip("/")
LIVETALKING_AVATAR_ID = os.getenv("LIVETALKING_AVATAR_ID", "wav2lip256_avatar1").strip()


def load_api_key() -> str:
    key = os.getenv("ZHIPU_API_KEY", "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    raise RuntimeError("ZHIPU_API_KEY not set and softcup_glmkey missing")
