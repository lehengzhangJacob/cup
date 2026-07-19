import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
PROJECT_ROOT = BASE_DIR.parent

GUIDELINE_DOCX = Path(
    os.getenv("RAG_GUIDELINE_DOCX", str(BASE_DIR / "guideline.docx"))
).expanduser()
DATASET_DOCX = Path(
    os.getenv("RAG_DATASET_DOCX", str(BASE_DIR / "dataset.docx"))
).expanduser()
XLSX_FILE = Path(
    os.getenv("RAG_XLSX_FILE", str(BASE_DIR / "景点景区旅游数据行为分析数据.xlsx"))
).expanduser()
WHITELIST_JSON = BASE_DIR / "data" / "whitelist.json"
EXTRA_DOCS_DIR = Path(
    os.getenv(
        "RAG_EXTRA_DOCS_DIR",
        str(PROJECT_ROOT / "data" / "lingshan" / "knowledge_uploads"),
    )
).expanduser()

INDEX_DIR      = BASE_DIR / "index"
FAISS_INDEX    = INDEX_DIR / "faiss.index"
METADATA_JSON  = INDEX_DIR / "metadata.json"

EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3").strip()
EMBED_DEVICE = os.getenv("RAG_EMBED_DEVICE", "").strip() or None
LLM_BASE_URL = os.getenv(
    "RAG_LLM_BASE_URL",
    "https://open.bigmodel.cn/api/paas/v4/",
).rstrip("/")
LLM_MODEL = os.getenv("RAG_LLM_MODEL", "glm-4.7-flash").strip()
LLM_API_KEY = os.getenv("GLM_API_KEY", "").strip() or os.getenv(
    "ZHIPU_API_KEY", ""
).strip()
LLM_KEY_FILE = Path(
    os.getenv("RAG_LLM_KEY_FILE", str(PROJECT_ROOT / "softcup_glmkey"))
).expanduser()
LLM_TEMPERATURE = float(os.getenv("RAG_LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(os.getenv("RAG_LLM_MAX_TOKENS", "512"))
LOCAL_LLM_BASE_URL = os.getenv(
    "RAG_LOCAL_LLM_BASE_URL",
    "http://127.0.0.1:8021/v1",
).rstrip("/")
LOCAL_LLM_MODEL = os.getenv(
    "RAG_LOCAL_LLM_MODEL",
    "/home/huggingface/Qwen2-7B-Instruct",
).strip()
LOCAL_LLM_API_KEY = os.getenv("RAG_LOCAL_LLM_API_KEY", "local").strip() or "local"
LOCAL_LLM_START_SCRIPT = Path(
    os.getenv(
        "RAG_LOCAL_LLM_START_SCRIPT",
        str(PROJECT_ROOT / "deploy" / "start_local_llm.sh"),
    )
).expanduser()
LOCAL_LLM_LAST_USED_FILE = Path(
    os.getenv(
        "RAG_LOCAL_LLM_LAST_USED_FILE",
        str(PROJECT_ROOT / "deploy" / "local-llm.last-used"),
    )
).expanduser()

SESSION_TTL_SECONDS = int(os.getenv("RAG_SESSION_TTL_SECONDS", "3600"))
SESSION_MAX_COUNT = int(os.getenv("RAG_SESSION_MAX_COUNT", "1000"))
SESSION_MAX_TURNS = int(os.getenv("RAG_SESSION_MAX_TURNS", "6"))
SESSION_MAX_MESSAGE_CHARS = int(
    os.getenv("RAG_SESSION_MAX_MESSAGE_CHARS", "2000")
)
RETRIEVAL_HISTORY_TURNS = int(os.getenv("RAG_RETRIEVAL_HISTORY_TURNS", "2"))
QUESTION_MAX_CHARS = int(os.getenv("RAG_QUESTION_MAX_CHARS", "4000"))

TOP_K_FILTERED = 3
TOP_K_FULL     = 5
MAX_CHUNK_CHARS = 500
CHUNK_OVERLAP   = 100


def load_llm_api_key() -> str:
    """Load the GLM key without requiring secrets in source control."""
    if LLM_API_KEY:
        return LLM_API_KEY
    if LLM_KEY_FILE.exists():
        key = LLM_KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    raise RuntimeError(
        "GLM_API_KEY/ZHIPU_API_KEY is not set and the RAG key file is missing"
    )
