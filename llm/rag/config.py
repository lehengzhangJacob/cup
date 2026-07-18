import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

GUIDELINE_DOCX = BASE_DIR / "guideline.docx"
DATASET_DOCX   = BASE_DIR / "dataset.docx"
XLSX_FILE      = BASE_DIR / "景点景区旅游数据行为分析数据.xlsx"
WHITELIST_JSON = BASE_DIR / "data" / "whitelist.json"

INDEX_DIR      = BASE_DIR / "index"
FAISS_INDEX    = INDEX_DIR / "faiss.index"
METADATA_JSON  = INDEX_DIR / "metadata.json"

EMBED_MODEL    = "BAAI/bge-m3"
LLM_BASE_URL   = "https://open.bigmodel.cn/api/paas/v4/"
LLM_MODEL      = "glm-4-flash"
LLM_API_KEY    = os.environ.get("GLM_API_KEY", "")

TOP_K_FILTERED = 3
TOP_K_FULL     = 5
MAX_CHUNK_CHARS = 500
CHUNK_OVERLAP   = 100
