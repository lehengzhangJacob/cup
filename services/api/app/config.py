from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # /home/softcup/cup
KEY_FILE = ROOT / "softcup_glmkey"
DEEPSEEK_KEY_FILE = Path(
    os.getenv("DEEPSEEK_KEY_FILE", str(ROOT / "deepseek_key"))
).expanduser()
DATA_DIR = ROOT / "data" / "lingshan"
DOCS_DIR = ROOT / "资料" / "示范景区公开资料包"
UPLOADS_DIR = DATA_DIR / "knowledge_uploads"
KB_PATH = DATA_DIR / "kb_chunks.json"
LOG_DB = DATA_DIR / "server.db"

ZHIPU_BASE = os.getenv("ZHIPU_BASE", "https://open.bigmodel.cn/api/paas/v4")
ZHIPU_CHAT_MODEL = os.getenv("ZHIPU_CHAT_MODEL", "glm-4.7-flash")
VISION_MODEL = os.getenv("ZHIPU_VISION_MODEL", "glm-4v-flash")
EMBED_MODEL = os.getenv("ZHIPU_EMBED_MODEL", "embedding-3")
TTS_MODEL = os.getenv("ZHIPU_TTS_MODEL", "glm-tts")
TTS_VOICE = os.getenv("ZHIPU_TTS_VOICE", "female")
LIVETALKING_TTS_SPEED = max(
    0.5,
    min(2.0, float(os.getenv("LIVETALKING_TTS_SPEED", "1.12"))),
)
ASR_MODEL = os.getenv("ZHIPU_ASR_MODEL", "glm-asr")

DEEPSEEK_BASE = os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
RAG_URL = os.getenv("RAG_URL", "http://127.0.0.1:8020").rstrip("/")
RAG_CONNECT_TIMEOUT_SECONDS = float(os.getenv("RAG_CONNECT_TIMEOUT_SECONDS", "5"))
RAG_READ_TIMEOUT_SECONDS = float(os.getenv("RAG_READ_TIMEOUT_SECONDS", "180"))

HOST = os.getenv("API_HOST", "0.0.0.0")
PORT = int(os.getenv("API_PORT", "8000"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

ADMIN_PORT = int(os.getenv("ADMIN_PORT", "8444"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "123456abc")
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "").strip()
ADMIN_SESSION_TTL_SECONDS = int(os.getenv("ADMIN_SESSION_TTL_SECONDS", str(8 * 60 * 60)))
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
PUBLIC_ADMIN_URL = os.getenv("PUBLIC_ADMIN_URL", "").strip().rstrip("/")

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
TURN_ENABLED = os.getenv("TURN_ENABLED", "true").lower() in {"1", "true", "yes"}
TURN_PORT = int(os.getenv("TURN_PORT", "8443"))
TURN_USERNAME = os.getenv("TURN_USERNAME", "lingshan").strip()
TURN_CREDENTIAL = os.getenv("TURN_CREDENTIAL", "lingshan-a5-2026-7e91c").strip()
CLOUDFLARE_TURN_KEY_ID = os.getenv("CLOUDFLARE_TURN_KEY_ID", "").strip()
CLOUDFLARE_TURN_API_TOKEN = os.getenv("CLOUDFLARE_TURN_API_TOKEN", "").strip()
CLOUDFLARE_TURN_TTL_SECONDS = max(
    300,
    min(172800, int(os.getenv("CLOUDFLARE_TURN_TTL_SECONDS", "3600"))),
)


def load_api_key() -> str:
    key = os.getenv("ZHIPU_API_KEY", "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    raise RuntimeError("ZHIPU_API_KEY not set and softcup_glmkey missing")


def load_deepseek_api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    if DEEPSEEK_KEY_FILE.exists():
        return DEEPSEEK_KEY_FILE.read_text(encoding="utf-8").strip()
    raise RuntimeError(
        f"DEEPSEEK_API_KEY not set and key file missing: {DEEPSEEK_KEY_FILE}"
    )
