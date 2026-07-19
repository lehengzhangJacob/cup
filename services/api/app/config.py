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
TOURISM_DATASET_PATH = Path(
    os.getenv(
        "TOURISM_DATASET_PATH",
        str(DOCS_DIR / "景点景区旅游数据行为分析数据.xlsx"),
    )
).expanduser()

# Multimodal emotion inference is deliberately isolated from the interactive
# ASR/RAG/TTS path. A deployment may either expose the model as an HTTP
# service or let the API invoke the HumanOmni inference script directly.
EMOTION_MODEL_PATH = Path(
    os.getenv(
        "EMOTION_MODEL_PATH",
        str(ROOT / "model" / "emotion_v5_stage2"),
    )
).expanduser()
EMOTION_BASE_MODEL_PATH = Path(
    os.getenv(
        "EMOTION_BASE_MODEL_PATH",
        str(ROOT / "model" / "emotion_stage1"),
    )
).expanduser()
EMOTION_BERT_PATH = Path(
    os.getenv("EMOTION_BERT_PATH", "/home/huggingface/bert-base-uncased")
).expanduser()
EMOTION_INFERENCE_URL = os.getenv("EMOTION_INFERENCE_URL", "").strip().rstrip("/")
EMOTION_INFERENCE_SCRIPT = Path(
    os.getenv(
        "EMOTION_INFERENCE_SCRIPT",
        str(ROOT / "services" / "emotion" / "inference_adapter.py"),
    )
).expanduser()
EMOTION_PYTHON = os.getenv(
    "EMOTION_PYTHON",
    "/home/gmn/.conda/envs/softcup/bin/python",
).strip()
EMOTION_GPU = os.getenv("EMOTION_GPU", "2").strip()
EMOTION_TIMEOUT_SECONDS = max(
    15,
    int(os.getenv("EMOTION_TIMEOUT_SECONDS", "180")),
)
EMOTION_MEDIA_MAX_BYTES = max(
    1,
    int(os.getenv("EMOTION_MEDIA_MAX_MB", "32")),
) * 1024 * 1024
EMOTION_KEEP_MEDIA = os.getenv("EMOTION_KEEP_MEDIA", "false").lower() in {
    "1",
    "true",
    "yes",
}

ZHIPU_BASE = os.getenv("ZHIPU_BASE", "https://open.bigmodel.cn/api/paas/v4")
ZHIPU_CHAT_MODEL = os.getenv("ZHIPU_CHAT_MODEL", "glm-4.7-flash")
VISION_MODEL = os.getenv("ZHIPU_VISION_MODEL", "glm-4v-flash")
EMBED_MODEL = os.getenv("ZHIPU_EMBED_MODEL", "embedding-3")
TTS_MODEL = os.getenv("ZHIPU_TTS_MODEL", "glm-tts")
TTS_VOICE = os.getenv("ZHIPU_TTS_VOICE", "female")
# Keep spoken output at the provider's natural rate. Accelerating generated
# speech harms phrasing and makes short syllables easier to lose downstream.
LIVETALKING_TTS_SPEED = 1.0
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
TURN_PUBLIC_HOST = os.getenv("TURN_PUBLIC_HOST", "").strip()
TURN_UDP_ENABLED = os.getenv("TURN_UDP_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
}
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
