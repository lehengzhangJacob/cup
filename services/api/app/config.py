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
VISION_REFERENCES_DIR = DATA_DIR / "vision_references"
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
EMOTION_GPU = os.getenv("EMOTION_GPU", "3").strip()
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
# Raw visitor dialogue is not needed indefinitely for operations. Structured
# aggregates remain available after the transcript is removed.
CHAT_RETENTION_DAYS = max(1, int(os.getenv("CHAT_RETENTION_DAYS", "30")))
EMOTION_TRANSCRIPT_RETENTION_DAYS = max(1, int(os.getenv("EMOTION_TRANSCRIPT_RETENTION_DAYS", "30")))

ZHIPU_BASE = os.getenv("ZHIPU_BASE", "https://open.bigmodel.cn/api/paas/v4")
# Keep this in sync with the model the RAG service actually serves
# (llm/rag/config.py LLM_MODEL) and with /health. The API client is only used
# for the vision/TTS/ASR paths; the RAG QA path is served by the RAG service.
ZHIPU_CHAT_MODEL = os.getenv("ZHIPU_CHAT_MODEL", "glm-4-flash-250414")
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


def _build_admin_allowed_origins() -> list[str]:
    """Origins permitted for mutating admin API requests (CSRF allowlist).

    The admin listener sits behind a reverse proxy that rewrites Host, so the
    server cannot infer the browser's origin from Host. The public admin UI is
    reachable through several equivalent URLs (raw IP, sslip hostname, custom
    domain), so accept all of them: the explicit ADMIN_ALLOWED_ORIGINS env
    list, the canonical PUBLIC_ADMIN_URL, and the admin URL built from the
    public app hostname (e.g. visitor app on sslip:20443 implies admin on
    sslip:20444).
    """
    from urllib.parse import urlparse

    raw = [item.strip() for item in os.getenv("ADMIN_ALLOWED_ORIGINS", "").split(",")]
    origins = [item.rstrip("/") for item in raw if item]
    if PUBLIC_ADMIN_URL:
        origins.append(PUBLIC_ADMIN_URL)
    if PUBLIC_APP_URL:
        app_host = urlparse(PUBLIC_APP_URL).hostname
        admin_port = urlparse(PUBLIC_ADMIN_URL).port if PUBLIC_ADMIN_URL else None
        if app_host:
            origins.append(f"https://{app_host}:{admin_port or 20444}")
    seen: set[str] = set()
    unique: list[str] = []
    for item in origins:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


ADMIN_ALLOWED_ORIGINS = _build_admin_allowed_origins()

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


# === 识景 CLIP/SigLIP 视觉检索管线 ===
# CLIP 推理隔离在 softcup 环境的独立 socket 服务中（见 services/vision/clip_service.py
# 与 deploy/start_clip_embedder.sh）。API 进程只通过 Unix socket 调用，不加载 torch。
# 图集为空或服务不可用时管线自动降级为 glm-4v-flash 单阶段流程。
CLIP_MODE = os.getenv("CLIP_MODE", "socket").strip()  # socket | inproc | disabled
CLIP_MODEL = os.getenv(
    "CLIP_MODEL", str(ROOT / "model" / "siglip-base-patch16-224")
).strip()
CLIP_SOCKET = Path(
    os.getenv("CLIP_SOCKET", str(ROOT / "deploy" / "vision-clip.sock"))
).expanduser()
CLIP_STATUS_FILE = Path(
    os.getenv("CLIP_STATUS_FILE", str(ROOT / "deploy" / "vision-clip-status.json"))
).expanduser()
CLIP_DEVICE = os.getenv("CLIP_DEVICE", "cpu").strip()  # cpu | cuda | on-demand
CLIP_GPU = os.getenv("CLIP_GPU", "3").strip()
CLIP_GPU_IDLE_SECONDS = float(os.getenv("CLIP_GPU_IDLE_SECONDS", "180"))
CLIP_TOP_K = max(1, int(os.getenv("CLIP_TOP_K", "5")))
CLIP_MIN_SIM = float(os.getenv("CLIP_MIN_SIM", "0.20"))
CLIP_SOCKET_TIMEOUT_SECONDS = float(os.getenv("CLIP_SOCKET_TIMEOUT_SECONDS", "10"))
CLIP_BLEND_CLIP = float(os.getenv("CLIP_BLEND_CLIP", "0.4"))  # CLIP sim 融合权重
CLIP_BLEND_VLM = float(os.getenv("CLIP_BLEND_VLM", "0.6"))    # VLM confidence 融合权重

# 置信度阈值（替换 vision_analysis.py 原硬编码 0.82/0.75/0.15）
VISION_HIGH_CONFIDENCE = float(os.getenv("VISION_HIGH_CONFIDENCE", "0.82"))
VISION_MEDIUM_CONFIDENCE = float(os.getenv("VISION_MEDIUM_CONFIDENCE", "0.75"))
VISION_MARGIN = float(os.getenv("VISION_MARGIN", "0.15"))
VISION_LOCATION_PRIOR_BOOST = float(os.getenv("VISION_LOCATION_PRIOR_BOOST", "0.08"))
VISION_LOCATION_PRIOR_CAP = float(os.getenv("VISION_LOCATION_PRIOR_CAP", "0.95"))
VISION_REFUTATION_FACTOR = float(os.getenv("VISION_REFUTATION_FACTOR", "0.6"))   # 参考图复核反证降权
VISION_ERROR_FACTOR = float(os.getenv("VISION_ERROR_FACTOR", "0.85"))            # 复核异常降权
VISION_QUALITY_WARN_FACTOR = float(os.getenv("VISION_QUALITY_WARN_FACTOR", "0.9"))

# 图片质量检测阈值
VISION_QUALITY_BLUR_LAPLACIAN = float(os.getenv("VISION_QUALITY_BLUR_LAPLACIAN", "80"))
VISION_QUALITY_BRIGHT_LOW = int(os.getenv("VISION_QUALITY_BRIGHT_LOW", "25"))
VISION_QUALITY_BRIGHT_HIGH = int(os.getenv("VISION_QUALITY_BRIGHT_HIGH", "235"))

VISION_INDEX_PATH = VISION_REFERENCES_DIR / "index.npz"
# 低于此参考图总数时跳过 CLIP 召回、降级为单阶段流程
VISION_MIN_REFERENCE_IMAGES = max(1, int(os.getenv("VISION_MIN_REFERENCE_IMAGES", "2")))


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
