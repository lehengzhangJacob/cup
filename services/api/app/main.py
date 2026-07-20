from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import secrets
import sqlite3
import subprocess
import uuid
import logging
from contextlib import asynccontextmanager

log = logging.getLogger(__name__)
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import quote, urlparse

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import (
    ADMIN_PASSWORD,
    ADMIN_PORT,
    CHAT_RETENTION_DAYS,
    CLIP_TOP_K,
    EMOTION_TRANSCRIPT_RETENTION_DAYS,
    ADMIN_SESSION_SECRET,
    ADMIN_SESSION_TTL_SECONDS,
    ADMIN_USERNAME,
    ADMIN_ALLOWED_ORIGINS,
    CORS_ORIGINS,
    DATA_DIR,
    DOCS_DIR,
    EMOTION_KEEP_MEDIA,
    EMOTION_TIMEOUT_SECONDS,
    LOG_DB,
    PUBLIC_ADMIN_URL,
    PUBLIC_APP_URL,
    LIVETALKING_AVATAR_ID,
    LIVETALKING_ENABLED,
    LIVETALKING_TTS_SPEED,
    LIVETALKING_URL,
    TTS_VOICE,
    TURN_CREDENTIAL,
    TURN_ENABLED,
    TURN_PORT,
    TURN_PUBLIC_HOST,
    TURN_UDP_ENABLED,
    TURN_USERNAME,
    ROOT,
    UPLOADS_DIR,
    VISION_REFERENCES_DIR,
    XMOV_APP_ID,
    XMOV_APP_SECRET,
    XMOV_AUTH_HEADER,
    XMOV_BROWSER_CONFIG_ENABLED,
    XMOV_SDK_URL,
    XMOV_SESSION_GATEWAY_URL,
    load_api_key,
)
from .ice import cloudflare_ice_servers, cloudflare_turn_config_error, cloudflare_turn_configured
from .admin_analytics import build_overview
from .admin_auth import ADMIN_COOKIE_NAME, create_admin_token, verify_admin_token
from .attractions import attraction_by_id, attraction_catalog, ensure_attraction_schema
from .avatar_reaction import avatar_reaction
from .avatar_catalog import find_avatar_preview, list_avatar_ids
from .demo_data import clear_demo_data, demo_data_status, seed_demo_data
from .emotion_analysis import analyze_text, emotion_analyzer
from .kb import ROUTES
from .location import (
    location_configuration,
    location_options,
    resolve_location,
    update_location_configuration,
)
from .rag_client import RAGClientError, rag
from .speech_segments import SpeechSegmenter
from .tourism_analytics import compact_tourism_database, ensure_tourism_schema, tourism_analytics
from .vision_analysis import (
    decide_confidence,
    demote_after_error,
    demote_after_refutation,
    merge_candidates,
    parse_vision_observation,
    vision_prompt,
)
from .vision_gallery import (
    add_reference,
    gallery_summary,
    list_references,
    list_vision_corrections,
    record_vision_correction,
    references_for,
    remove_reference,
)
from . import vision_clip_client, vision_index, vision_quality
from .image_processing import ImageValidationError, normalize_scenic_image
from .zhipu import zhipu

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
AVATAR_DIR = ROOT / "LiveTalking" / "data" / "avatars"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = Field(None, min_length=1, max_length=128)
    interest: Optional[str] = Field(None, description="历史/自然/亲子")
    stream: bool = True
    spot_id: Optional[str] = Field(None, max_length=100)
    livetalking_session_id: Optional[str] = Field(None, min_length=1)
    model_route: Literal["cloud", "local", "local_lite"] = "cloud"
    input_mode: Literal["text", "voice"] = "text"
    emotion_event_id: Optional[str] = Field(None, max_length=128)


class RecommendRequest(BaseModel):
    interest: str = Field(..., description="历史/自然/亲子 或 history/nature/family")


class LocateRequest(BaseModel):
    mode: str = Field(..., description="gps|qr|manual|wifi")
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy_m: Optional[float] = Field(None, ge=0, description="浏览器报告的 GPS 精度（米）")
    timestamp_ms: Optional[float] = Field(None, ge=0, description="浏览器定位时间戳（毫秒）")
    code: Optional[str] = None
    spot_name: Optional[str] = None


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: Optional[str] = None
    speed: float = 1.0


class LiveTalkingOfferRequest(BaseModel):
    sdp: str = Field(..., min_length=1)
    type: str = "offer"
    avatar: Optional[str] = None


class LiveTalkingSpeakRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=2000)
    interrupt: bool = False
    speed: float = Field(1.0, ge=0.8, le=1.2)


class LiveTalkingSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = None
    attraction_id: str = Field(..., min_length=1, max_length=30)
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field("", max_length=1000)


class AvatarSettingsRequest(BaseModel):
    display_name: str = Field("灵山小向导", min_length=1, max_length=30)
    avatar_id: str = Field(LIVETALKING_AVATAR_ID, min_length=1, max_length=100)
    voice: str = Field(TTS_VOICE, min_length=1, max_length=50)


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class VisionReferenceUpload(BaseModel):
    attraction_id: str = Field(..., min_length=1, max_length=30)
    source_url: str = Field("", max_length=500)
    note: str = Field("", max_length=300)


class LocationConfigurationRequest(BaseModel):
    gps_anchors: dict[str, dict[str, Any]]
    wifi_anchors: dict[str, dict[str, str]]


class VisionConfirmRequest(BaseModel):
    """游客确认识景结果并启动讲解的请求。"""
    attraction_id: str = Field(..., min_length=1, max_length=30, description="确认的景点 ID")
    session_id: str = Field(..., min_length=1, max_length=128, description="视觉识别会话 ID")
    question: str = Field("请为我讲解这个景点", max_length=2000, description="后续讲解问题")
    model_candidates: list[str] = Field(default_factory=list, description="首轮视觉模型的候选景点名")
    image_sha256: str = Field("", max_length=100, description="用于纠错记录的图片 SHA256")


class VisionCorrectionRequest(BaseModel):
    """记录视觉识别的纠错案例，用于质量评估。"""
    model_candidates: list[str] = Field(..., description="视觉模型给出的候选景点")
    user_confirmed: str = Field(..., min_length=1, max_length=100, description="游客最终确认的景点")
    image_sha256: str = Field("", max_length=100, description="对应的图片哈希值（前20位）")


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    existing = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LOG_DB, timeout=15)
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_logs (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            meta TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            attraction_id TEXT,
            scenic_area TEXT,
            attraction_name TEXT,
            rating INTEGER NOT NULL,
            comment TEXT,
            sentiment TEXT,
            source TEXT NOT NULL DEFAULT 'live',
            emotion_event_id TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS avatar_settings (
            -- costume/expression are legacy compatibility columns. They are
            -- intentionally not exposed by the API because no runtime consumes
            -- them; keep them only to avoid a destructive SQLite migration.
            id INTEGER PRIMARY KEY CHECK (id = 1),
            display_name TEXT NOT NULL,
            avatar_id TEXT NOT NULL,
            voice TEXT NOT NULL,
            costume TEXT NOT NULL,
            expression TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    # Migrate deployments created before attraction-level satisfaction was
    # introduced. SQLite's ADD COLUMN preserves all existing rows.
    _ensure_column(conn, "feedback", "attraction_id", "TEXT")
    _ensure_column(conn, "feedback", "scenic_area", "TEXT")
    _ensure_column(conn, "feedback", "attraction_name", "TEXT")
    _ensure_column(conn, "feedback", "source", "TEXT NOT NULL DEFAULT 'live'")
    _ensure_column(conn, "feedback", "emotion_event_id", "TEXT")
    ensure_attraction_schema(conn)
    ensure_tourism_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS emotion_events (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            source TEXT NOT NULL,
            transcript TEXT,
            rating INTEGER,
            media_kind TEXT,
            emotion_label TEXT,
            emotion_scores TEXT,
            sentiment TEXT,
            valence REAL,
            confidence REAL,
            aspects TEXT,
            status TEXT NOT NULL,
            model_name TEXT,
            analysis_mode TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_logs_role_created "
        "ON chat_logs(role, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_attraction_created "
        "ON feedback(attraction_id, created_at)"
    )
    _ensure_column(conn, "emotion_events", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "emotion_events", "processing_started_at", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_emotion_events_created "
        "ON emotion_events(created_at)"
    )
    conn.commit()
    return conn


def _infer_sentiment(text: str, rating: Optional[int] = None) -> str:
    return str(analyze_text(text, rating).get("sentiment") or "neutral")


def _avatar_settings() -> dict[str, str]:
    conn = _db()
    row = conn.execute(
        "SELECT display_name, avatar_id, voice, updated_at "
        "FROM avatar_settings WHERE id=1"
    ).fetchone()
    conn.close()
    if row:
        return {
            "display_name": row[0],
            "avatar_id": row[1],
            "voice": row[2],
            "updated_at": row[3],
        }
    return {
        "display_name": "灵山小向导",
        "avatar_id": LIVETALKING_AVATAR_ID,
        "voice": TTS_VOICE,
        "updated_at": "",
    }


def _guide_context(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Attach the admin-configured guide name to every RAG request."""
    context = {"数字人称呼": _avatar_settings()["display_name"]}
    context.update(extra or {})
    return context


def _available_avatars() -> list[str]:
    return list_avatar_ids(AVATAR_DIR, LIVETALKING_AVATAR_ID)


def _avatar_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": avatar_id,
            "preview_url": f"/v1/admin/avatar/{quote(avatar_id, safe='')}/preview"
            if find_avatar_preview(AVATAR_DIR, avatar_id)
            else None,
        }
        for avatar_id in _available_avatars()
    ]


def _log(session_id: str, role: str, content: str, meta: Optional[dict] = None) -> None:
    stored_meta = dict(meta or {})
    if role == "user" and "sentiment" not in stored_meta:
        stored_meta["sentiment"] = _infer_sentiment(content)
    conn = _db()
    conn.execute(
        "INSERT INTO chat_logs VALUES (?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            session_id,
            role,
            content,
            json.dumps(stored_meta, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def _conversation_context(session_id: str, limit: int = 6) -> list[dict[str, str]]:
    conn = _db()
    rows = conn.execute(
        "SELECT role, content FROM chat_logs WHERE session_id=? "
        "ORDER BY created_at DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    conn.close()
    return [
        {
            "speaker": "tourist" if role == "user" else "guide",
            "text": str(content or "")[:1000],
        }
        for role, content in reversed(rows)
    ]


def _linked_emotion_event(event_id: Optional[str], session_id: str) -> bool:
    if not event_id:
        return False
    conn = _db()
    row = conn.execute(
        "SELECT 1 FROM emotion_events WHERE id=? AND session_id=? AND source LIKE 'dialogue-%'",
        (event_id, session_id),
    ).fetchone()
    conn.close()
    return bool(row)


def _avatar_reaction_for_event(event_id: Optional[str], message: str) -> dict[str, Any]:
    """Use completed multimodal results when available, otherwise text now.

    Audio inference is deliberately asynchronous so ASR stays responsive.  A
    text-based provisional reaction lets the avatar respond immediately; the
    completed audio+text result remains available to the next dialogue turn
    and to the management report.
    """
    text_signal = analyze_text(message)
    emotion = None
    sentiment = text_signal.get("sentiment")
    confidence = text_signal.get("confidence")
    if event_id:
        conn = _db()
        row = conn.execute(
            "SELECT emotion_label, sentiment, confidence, status FROM emotion_events WHERE id=?",
            (event_id,),
        ).fetchone()
        conn.close()
        if row and row[3] == "completed":
            emotion = row[0]
            sentiment = row[1] or sentiment
            confidence = row[2] if row[2] is not None else confidence
    return avatar_reaction(
        emotion=emotion,
        sentiment=sentiment,
        confidence=confidence,
    )


async def _record_text_emotion(
    session_id: str,
    transcript: str,
    source: str = "dialogue-text",
) -> str:
    event_id = str(uuid.uuid4())
    result = await emotion_analyzer.analyze(None, transcript)
    now = datetime.now(timezone.utc).isoformat()
    conn = _db()
    conn.execute(
        """
        INSERT INTO emotion_events
            (id, session_id, source, transcript, rating, media_kind,
             emotion_label, emotion_scores, sentiment, valence, confidence,
             aspects, status, model_name, analysis_mode, error,
             created_at, completed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event_id,
            session_id,
            source,
            transcript[:4000],
            None,
            "text",
            result.get("emotion"),
            json.dumps(result.get("scores") or {}, ensure_ascii=False),
            result.get("sentiment"),
            result.get("valence"),
            result.get("confidence"),
            json.dumps(result.get("aspects") or [], ensure_ascii=False),
            "completed",
            result.get("model"),
            result.get("analysis_mode") or "text",
            result.get("model_error") or None,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return event_id


def _spoken_integer(value: int) -> str:
    digits = "零一二三四五六七八九"
    if value < 10:
        return digits[value]
    tens, ones = divmod(value, 10)
    prefix = "十" if tens == 1 else f"{digits[tens]}十"
    return prefix if ones == 0 else f"{prefix}{digits[ones]}"


def _spoken_clock(hour: str, minute: str) -> str:
    spoken_hour = _spoken_integer(int(hour))
    minute_value = int(minute)
    if minute_value == 0:
        return f"{spoken_hour}点"
    if minute_value == 30:
        return f"{spoken_hour}点半"
    if minute_value < 10:
        spoken_minute = f"零{_spoken_integer(minute_value)}"
    else:
        spoken_minute = _spoken_integer(minute_value)
    return f"{spoken_hour}点{spoken_minute}分"


_CLOCK_PATTERN = re.compile(
    r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)"
)
_CLOCK_RANGE_PATTERN = re.compile(
    r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)"
    r"\s*(?:-|–|—|~|～|至)\s*"
    r"([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)"
)


def _normalize_spoken_clocks(text: str) -> str:
    text = _CLOCK_RANGE_PATTERN.sub(
        lambda match: (
            f"{_spoken_clock(match.group(1), match.group(2))}到"
            f"{_spoken_clock(match.group(3), match.group(4))}"
        ),
        text,
    )
    return _CLOCK_PATTERN.sub(
        lambda match: _spoken_clock(match.group(1), match.group(2)),
        text,
    )


def _speech_text(text: str) -> str:
    """Remove metadata and normalize symbols that Chinese TTS mispronounces."""
    spoken_lines: list[str] = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith(("{", "```json", "```JSON")):
            break
        spoken_lines.append(line)
    spoken = "\n".join(spoken_lines)
    spoken = _normalize_spoken_clocks(spoken)
    # Route arrows are visual separators, not words. Render them as natural
    # navigation transitions before sending text to any TTS provider.
    spoken = re.sub(r"\s*(?:→|⇒|⟶|➜|➡|--?>)\s*", "，接着前往", spoken)
    spoken = re.sub(r"\s*(?:←|⇐|⬅)\s*", "，返回", spoken)
    spoken = re.sub(r"\s*(?:↔|⇄|⇆)\s*", "，往返于", spoken)
    return spoken.lstrip("，、 \t\n").strip()


def _purge_expired_visitor_data() -> dict[str, int]:
    """Remove stale raw dialogue while retaining anonymised aggregates."""
    now = datetime.now(timezone.utc)
    chat_cutoff = (now - timedelta(days=CHAT_RETENTION_DAYS)).isoformat()
    emotion_cutoff = (now - timedelta(days=EMOTION_TRANSCRIPT_RETENTION_DAYS)).isoformat()
    conn = _db()
    try:
        chat_deleted = conn.execute(
            "DELETE FROM chat_logs WHERE created_at < ?", (chat_cutoff,)
        ).rowcount
        # Text-only dialogue events carry no 7-class signal and accumulate one
        # per turn, so delete their rows once they age out of retention instead
        # of keeping them redacted. Voice (dialogue-voice) events are kept with
        # redacted transcripts because their 7-class label feeds long-term
        # aggregate emotion statistics.
        text_events_deleted = conn.execute(
            """DELETE FROM emotion_events
               WHERE created_at < ?
                 AND media_kind = 'text'
                 AND source LIKE 'dialogue-%'""",
            (emotion_cutoff,),
        ).rowcount
        transcript_redacted = conn.execute(
            """UPDATE emotion_events SET transcript='[已按保留策略删除]'
               WHERE created_at < ? AND transcript IS NOT NULL
                 AND transcript != '[已按保留策略删除]'""",
            (emotion_cutoff,),
        ).rowcount
        conn.commit()
        return {
            "chat_deleted": int(chat_deleted or 0),
            "text_events_deleted": int(text_events_deleted or 0),
            "transcript_redacted": int(transcript_redacted or 0),
        }
    finally:
        conn.close()


async def _resume_pending_emotion_jobs() -> int:
    """Requeue interrupted audio jobs when their temporary media still exists."""
    conn = _db()
    rows = conn.execute(
        """SELECT id, transcript, rating FROM emotion_events
             WHERE source='dialogue-voice' AND status IN ('queued','processing')"""
    ).fetchall()
    conn.execute(
        """UPDATE emotion_events SET status='queued', error=NULL
             WHERE source='dialogue-voice' AND status='processing'"""
    )
    conn.commit()
    conn.close()
    resumed = 0
    for job_id, transcript, rating in rows:
        media_path = DATA_DIR / "emotion_media" / f"{job_id}.wav"
        if not media_path.exists():
            conn = _db()
            conn.execute(
                "UPDATE emotion_events SET status='failed', error='服务重启后原音频已不存在，无法恢复分析' WHERE id=?",
                (job_id,),
            )
            conn.commit()
            conn.close()
            continue
        asyncio.create_task(_process_emotion_job(str(job_id), media_path, str(transcript or ""), rating))
        resumed += 1
    return resumed


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_api_key()
    conn = _db()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.commit()
    conn.close()
    await asyncio.to_thread(_purge_expired_visitor_data)
    # A restart no longer discards queued audio analysis; jobs whose temporary
    # audio survived are safely resumed, while missing media is explicit.
    await _resume_pending_emotion_jobs()
    turn_config_error = cloudflare_turn_config_error()
    if turn_config_error:
        raise RuntimeError(turn_config_error)
    if PUBLIC_ADMIN_URL and len(ADMIN_PASSWORD) < 12:
        raise RuntimeError("公网管理后台密码至少需要 12 个字符")
    if PUBLIC_ADMIN_URL and ADMIN_SESSION_SECRET and len(ADMIN_SESSION_SECRET) < 32:
        raise RuntimeError("ADMIN_SESSION_SECRET 至少需要 32 个字符")
    try:
        yield
    finally:
        await zhipu.aclose()


app = FastAPI(
    title="灵山胜境 AI 数字人导览 API",
    description="软件杯 A5 开放接口：问答、视觉与语音统一调用智谱 GLM。",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _request_port(request: Request) -> Optional[int]:
    if request.url.port:
        return request.url.port
    server = request.scope.get("server")
    return int(server[1]) if server and len(server) > 1 else None


def _is_admin_listener(request: Request) -> bool:
    return _request_port(request) == ADMIN_PORT


def _admin_authenticated(request: Request) -> bool:
    return verify_admin_token(request.cookies.get(ADMIN_COOKIE_NAME))


def _admin_origin_allowed(request: Request) -> bool:
    origin = (request.headers.get("origin") or "").rstrip("/")
    if not origin:
        return True
    return origin in ADMIN_ALLOWED_ORIGINS


@app.middleware("http")
async def separate_admin_boundary(request: Request, call_next):
    """Keep management UI and sensitive APIs on the dedicated admin listener."""
    path = request.url.path
    admin_api = (
        path.startswith("/v1/admin/")
        or path in {"/v1/stats/overview", "/v1/kb/rebuild"}
    )
    admin_page = path in {"/admin", "/admin/"}
    auth_free = path in {"/v1/admin/auth/login", "/v1/admin/auth/logout"}

    if not _is_admin_listener(request):
        if admin_page or path == "/login" or admin_api:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return await call_next(request)

    allowed = (
        path in {"/", "/login", "/health", "/favicon.ico", "/v1/attractions"}
        or admin_page
        or admin_api
    )
    if not allowed:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if path == "/":
        return RedirectResponse("/admin", status_code=307)

    if (admin_page or admin_api) and not auth_free and not _admin_authenticated(request):
        if admin_page:
            return RedirectResponse("/login", status_code=303)
        return JSONResponse({"detail": "请先登录管理后台"}, status_code=401)

    if admin_api and request.method not in {"GET", "HEAD", "OPTIONS"} and not _admin_origin_allowed(request):
        return JSONResponse({"detail": "管理请求来源校验失败"}, status_code=403)

    response = await call_next(request)
    if admin_page or admin_api or path == "/login":
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health")
async def health():
    try:
        rag_status = await rag.health()
    except RAGClientError as exc:
        rag_status = {"ok": False, "detail": str(exc)}
    return {
        "ok": bool(rag_status.get("ok")),
        "rag": rag_status,
        "chunks": rag_status.get("chunk_count", 0),
        "has_embeddings": bool(rag_status.get("chunk_count")),
        "chat_model": rag_status.get("model"),
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/model-routes")
async def model_routes():
    try:
        return await rag.model_routes()
    except RAGClientError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/v1/rag/warmup")
async def rag_warmup():
    try:
        return await rag.warmup()
    except RAGClientError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/v1/admin/auth/login")
async def admin_login(req: AdminLoginRequest):
    username_ok = secrets.compare_digest(req.username, ADMIN_USERNAME)
    password_ok = secrets.compare_digest(req.password, ADMIN_PASSWORD)
    if not (username_ok and password_ok):
        raise HTTPException(401, "账号或密码错误")
    response = JSONResponse(
        {
            "ok": True,
            "username": ADMIN_USERNAME,
            "expires_in": ADMIN_SESSION_TTL_SECONDS,
        }
    )
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        create_admin_token(),
        max_age=ADMIN_SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/v1/admin/auth/logout")
async def admin_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(
        ADMIN_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


@app.get("/v1/admin/auth/session")
async def admin_session():
    return {"authenticated": True, "username": ADMIN_USERNAME}



@app.get("/v1/xmov/config")
async def xmov_config():
    """Return browser SDK config only after an explicit secret-exposure opt-in."""
    configured = bool(XMOV_APP_ID and XMOV_APP_SECRET and XMOV_SESSION_GATEWAY_URL)
    enabled = XMOV_BROWSER_CONFIG_ENABLED and configured
    result = {
        "enabled": enabled,
        "configured": configured,
        "requires_browser_secret_opt_in": configured and not XMOV_BROWSER_CONFIG_ENABLED,
    }
    if enabled:
        result.update(
            {
                "app_id": XMOV_APP_ID,
                "app_secret": XMOV_APP_SECRET,
                "gateway_server": XMOV_SESSION_GATEWAY_URL,
                "auth_header": XMOV_AUTH_HEADER,
                "sdk_url": XMOV_SDK_URL,
            }
        )
    return result


async def _livetalking_post(path: str, payload: dict, timeout: float = 10.0) -> dict:
    if not LIVETALKING_ENABLED:
        raise HTTPException(503, "LiveTalking is disabled")
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(f"{LIVETALKING_URL}{path}", json=payload)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, f"LiveTalking unavailable: {exc}") from exc
    if isinstance(data, dict) and data.get("code") not in (None, 0):
        raise HTTPException(502, data.get("msg") or "LiveTalking request failed")
    _mark_livetalking_used()
    return data


def _direct_turn_server(fallback_hostname: str | None = None) -> dict[str, Any]:
    public_app_hostname = urlparse(PUBLIC_APP_URL).hostname if PUBLIC_APP_URL else None
    hostname = TURN_PUBLIC_HOST or fallback_hostname or public_app_hostname or "localhost"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    urls = [f"turn:{hostname}:{TURN_PORT}?transport=tcp"]
    if TURN_UDP_ENABLED:
        urls.insert(0, f"turn:{hostname}:{TURN_PORT}?transport=udp")
    return {
        "urls": urls,
        "username": TURN_USERNAME,
        "credential": TURN_CREDENTIAL,
    }


_livetalking_start_lock = asyncio.Lock()
_livetalking_last_used_file = ROOT / "deploy" / "livetalking" / "last-used"


def _mark_livetalking_used() -> None:
    _livetalking_last_used_file.parent.mkdir(parents=True, exist_ok=True)
    _livetalking_last_used_file.touch()


async def _ensure_livetalking_started() -> bool:
    if not LIVETALKING_ENABLED:
        raise HTTPException(503, "LiveTalking is disabled")
    async with _livetalking_start_lock:
        try:
            async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
                response = await client.get(f"{LIVETALKING_URL}/api/admin/config")
            response.raise_for_status()
        except httpx.HTTPError:
            pass
        else:
            _mark_livetalking_used()
            return False

        def start_service() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["bash", str(ROOT / "deploy" / "start_livetalking.sh")],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=90,
            )

        try:
            completed = await asyncio.to_thread(start_service)
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(503, "LiveTalking start timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise HTTPException(503, f"LiveTalking start failed: {detail}")
        _mark_livetalking_used()
    return True


_livetalking_warm_task: asyncio.Task[None] | None = None


def _schedule_livetalking_warmup() -> None:
    global _livetalking_warm_task
    if not LIVETALKING_ENABLED:
        return
    if _livetalking_warm_task and not _livetalking_warm_task.done():
        return

    async def warmup() -> None:
        global _livetalking_warm_task
        try:
            await _ensure_livetalking_started()
        except Exception as exc:
            print(f"[warn] LiveTalking background warmup failed: {exc}")
        finally:
            _livetalking_warm_task = None

    _livetalking_warm_task = asyncio.create_task(warmup())


@app.get("/v1/livetalking/status")
async def livetalking_status(request: Request):
    avatar_id = _avatar_settings()["avatar_id"]
    turn = None
    ice_servers: list[dict[str, Any]] = []
    ice_detail = None
    if cloudflare_turn_configured():
        try:
            ice_servers = await cloudflare_ice_servers()
        except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
            print(f"[warn] Cloudflare TURN credentials unavailable: {exc}")
            ice_detail = "公网 WebRTC 中继凭据获取失败"
    elif TURN_ENABLED:
        turn = _direct_turn_server(request.url.hostname)
        ice_servers = [turn]
    elif PUBLIC_APP_URL:
        ice_detail = "公网模式需要配置 Cloudflare TURN"

    status = {
        "enabled": LIVETALKING_ENABLED,
        "ready": False,
        "on_demand": True,
        "avatar_id": avatar_id,
        "turn": turn,
        "ice_servers": ice_servers,
    }
    if not LIVETALKING_ENABLED:
        return status
    if PUBLIC_APP_URL and not ice_servers:
        status["detail"] = ice_detail
        return status
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            response = await client.get(f"{LIVETALKING_URL}/api/admin/config")
        response.raise_for_status()
        status["ready"] = True
        return status
    except httpx.HTTPError as exc:
        status["detail"] = str(exc)
        return status


@app.post("/v1/livetalking/start")
async def livetalking_start():
    started = await _ensure_livetalking_started()
    return {"ok": True, "ready": True, "on_demand": True, "started": started}


@app.post("/v1/livetalking/offer")
async def livetalking_offer(req: LiveTalkingOfferRequest):
    payload = req.model_dump(exclude_none=True)
    payload["avatar"] = payload.get("avatar") or _avatar_settings()["avatar_id"]
    if cloudflare_turn_configured():
        try:
            payload["ice_servers"] = await cloudflare_ice_servers()
        except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
            print(f"[warn] Cloudflare TURN credentials unavailable: {exc}")
            raise HTTPException(503, "公网 WebRTC 中继凭据获取失败") from exc
    elif TURN_ENABLED:
        payload["ice_servers"] = [_direct_turn_server()]
    elif PUBLIC_APP_URL and not TURN_ENABLED:
        raise HTTPException(503, "公网模式需要配置 Cloudflare TURN")
    return await _livetalking_post("/offer", payload, timeout=20.0)


async def _stream_tts_to_livetalking(
    session_id: str,
    text: str,
    *,
    interrupt: bool,
    speed: float = 1.0,
    finalize: bool = True,
) -> Optional[int]:
    if interrupt:
        await _livetalking_post(
            "/interrupt_talk",
            {"sessionid": session_id},
        )

    speech_text = _speech_text(text)
    if not speech_text:
        return None

    sample_rate: Optional[int] = None
    chunk_count = 0
    sample_count = 0
    first_chunk_ms: Optional[int] = None
    tts_started_at = asyncio.get_running_loop().time()
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        async for event in zhipu.tts_stream(
            speech_text,
            voice=_avatar_settings()["voice"],
            speed=max(0.8, min(1.2, LIVETALKING_TTS_SPEED * speed)),
        ):
            choices = event.get("choices") or []
            delta = choices[0].get("delta", {}) if choices else {}
            encoded = delta.get("content")
            if not encoded:
                continue

            event_sample_rate = int(delta.get("return_sample_rate") or 24000)
            if sample_rate is None:
                sample_rate = event_sample_rate
            elif event_sample_rate != sample_rate:
                raise RuntimeError(
                    f"GLM-TTS sample rate changed from {sample_rate} to {event_sample_rate}"
                )

            try:
                pcm_chunk = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError("GLM-TTS returned invalid base64 PCM audio") from exc
            if not pcm_chunk:
                continue
            chunk_count += 1
            sample_count += len(pcm_chunk) // 2
            if sample_count * 2 > 32 * 1024 * 1024:
                raise RuntimeError("GLM-TTS audio exceeds 32 MiB")
            response = await client.post(
                f"{LIVETALKING_URL}/humanpcm",
                params={
                    "sessionid": session_id,
                    "sample_rate": sample_rate,
                    "final": "false",
                },
                content=pcm_chunk,
                headers={"Content-Type": "application/octet-stream"},
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("code") not in (None, 0):
                raise RuntimeError(data.get("msg") or "LiveTalking PCM stream failed")
            if first_chunk_ms is None:
                first_chunk_ms = round(
                    (asyncio.get_running_loop().time() - tts_started_at) * 1000
                )
                _mark_livetalking_used()

        if not chunk_count or sample_rate is None:
            raise RuntimeError("GLM-TTS returned no PCM audio")
        if finalize:
            await _finish_livetalking_pcm_stream(session_id, sample_rate)

        print(
            "[livetalking] streamed semantic TTS audio: "
            f"session={session_id} chunks={chunk_count} "
            f"samples={sample_count} sample_rate={sample_rate} "
            f"first_chunk_ms={first_chunk_ms} "
            f"finalized={str(finalize).lower()} "
            f"total_ms={round((asyncio.get_running_loop().time() - tts_started_at) * 1000)}"
        )
    return sample_rate


async def _finish_livetalking_pcm_stream(
    session_id: str,
    sample_rate: int,
) -> None:
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        response = await client.post(
            f"{LIVETALKING_URL}/humanpcm",
            params={
                "sessionid": session_id,
                "sample_rate": sample_rate,
                "final": "true",
            },
            content=b"",
            headers={"Content-Type": "application/octet-stream"},
        )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("code") not in (None, 0):
        raise RuntimeError(data.get("msg") or "LiveTalking PCM stream failed")


_livetalking_speech_workers: dict[str, asyncio.Task[None]] = {}


def _livetalking_speech_pending(session_id: str) -> bool:
    worker = _livetalking_speech_workers.get(session_id)
    return bool(worker and not worker.done())


def _cancel_livetalking_speech_worker(session_id: str) -> None:
    worker = _livetalking_speech_workers.pop(session_id, None)
    if worker and not worker.done():
        worker.cancel()


def _start_livetalking_speech_worker(
    session_id: str,
    *,
    speed: float = 1.0,
) -> asyncio.Queue[Optional[str]]:
    _cancel_livetalking_speech_worker(session_id)
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    async def run() -> None:
        first = True
        answer_sample_rate: Optional[int] = None
        while True:
            segment = await queue.get()
            if segment is None:
                if answer_sample_rate is not None:
                    await _finish_livetalking_pcm_stream(
                        session_id,
                        answer_sample_rate,
                    )
                return
            segment_sample_rate = await _stream_tts_to_livetalking(
                session_id,
                segment,
                interrupt=first,
                speed=speed,
                finalize=False,
            )
            if segment_sample_rate is not None:
                if answer_sample_rate is None:
                    answer_sample_rate = segment_sample_rate
                elif segment_sample_rate != answer_sample_rate:
                    raise RuntimeError(
                        "GLM-TTS sample rate changed between semantic segments"
                    )
            first = False

    worker = asyncio.create_task(run())
    _livetalking_speech_workers[session_id] = worker

    def cleanup(done: asyncio.Task[None]) -> None:
        if _livetalking_speech_workers.get(session_id) is done:
            _livetalking_speech_workers.pop(session_id, None)
        if done.cancelled():
            return
        error = done.exception()
        if error:
            print(f"[warn] server-driven LiveTalking speech failed: {error}")

    worker.add_done_callback(cleanup)
    return queue


@app.post("/v1/livetalking/speak")
async def livetalking_speak(req: LiveTalkingSpeakRequest):
    try:
        await _stream_tts_to_livetalking(
            req.session_id,
            req.text,
            interrupt=req.interrupt,
            speed=req.speed,
        )
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise HTTPException(502, f"LiveTalking streaming TTS failed: {exc}") from exc
    return {"code": 0, "msg": "ok"}


@app.post("/v1/livetalking/interrupt")
async def livetalking_interrupt(req: LiveTalkingSessionRequest):
    _cancel_livetalking_speech_worker(req.session_id)
    return await _livetalking_post(
        "/interrupt_talk",
        {"sessionid": req.session_id},
    )


@app.post("/v1/livetalking/is-speaking")
async def livetalking_is_speaking(req: LiveTalkingSessionRequest):
    result = await _livetalking_post(
        "/is_speaking",
        {"sessionid": req.session_id},
    )
    if isinstance(result, dict):
        result["pending"] = _livetalking_speech_pending(req.session_id)
    return result


@app.post("/v1/livetalking/close")
async def livetalking_close(req: LiveTalkingSessionRequest):
    _cancel_livetalking_speech_worker(req.session_id)
    return await _livetalking_post(
        "/close_session",
        {"sessionid": req.session_id},
    )


@app.post("/v1/livetalking/heartbeat")
async def livetalking_heartbeat(req: LiveTalkingSessionRequest):
    return await _livetalking_post(
        "/heartbeat",
        {"sessionid": req.session_id},
    )


@app.get("/v1/routes")
async def list_routes():
    return {"routes": ROUTES}


@app.post("/v1/recommend")
async def recommend(req: RecommendRequest):
    mapping = {
        "历史": "history",
        "历史文化": "history",
        "history": "history",
        "自然": "nature",
        "风光": "nature",
        "nature": "nature",
        "亲子": "family",
        "家庭": "family",
        "family": "family",
    }
    rid = mapping.get(req.interest.strip().lower(), mapping.get(req.interest.strip(), "history"))
    route = next((r for r in ROUTES if r["id"] == rid), ROUTES[0])
    return {"interest": req.interest, "route": route}


@app.post("/v1/locate")
async def locate(req: LocateRequest):
    """多源弱定位：不把低精度或过期 GPS 强行解析成确定景点。"""
    return resolve_location(
        req.mode,
        lat=req.lat,
        lng=req.lng,
        accuracy_m=req.accuracy_m,
        timestamp_ms=req.timestamp_ms,
        code=req.code,
        spot_name=req.spot_name,
    )


@app.get("/v1/location/options")
async def get_location_options():
    """Published QR/manual point registry used by the visitor-side locator."""
    return location_options()


@app.get("/v1/kb/stats")
async def kb_stats():
    try:
        return await rag.stats()
    except RAGClientError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/v1/kb/rebuild")
async def kb_rebuild():
    try:
        return await rag.rebuild()
    except RAGClientError as exc:
        raise HTTPException(503, str(exc)) from exc


def _knowledge_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for directory, category, editable in (
        (DOCS_DIR, "官方资料", False),
        (UPLOADS_DIR, "管理员上传", True),
    ):
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in {".docx", ".txt", ".md"}:
                continue
            stat = path.stat()
            documents.append(
                {
                    "name": path.name,
                    "category": category,
                    "editable": editable,
                    "size": stat.st_size,
                    "updated_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )
    return documents


@app.get("/v1/admin/kb/documents")
async def admin_kb_documents():
    try:
        stats = await rag.stats()
    except RAGClientError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "documents": _knowledge_documents(),
        "chunk_count": stats.get("chunk_count", 0),
    }


@app.post("/v1/admin/kb/documents")
async def admin_kb_upload(file: UploadFile = File(...)):
    filename = Path(file.filename or "").name
    if not filename or filename in {".", ".."}:
        raise HTTPException(400, "文件名无效")
    if Path(filename).suffix.lower() not in {".docx", ".txt", ".md"}:
        raise HTTPException(400, "仅支持 DOCX、TXT、Markdown 知识文档")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "文件为空")
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过 10MB")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOADS_DIR / filename
    previous = destination.read_bytes() if destination.exists() else None
    destination.write_bytes(raw)
    try:
        result = await rag.rebuild()
    except RAGClientError as exc:
        if previous is None:
            destination.unlink(missing_ok=True)
        else:
            destination.write_bytes(previous)
        try:
            await rag.rebuild()
        except RAGClientError:
            pass
        raise HTTPException(400, f"知识文档解析或索引失败：{exc}") from exc
    return {
        "ok": True,
        "name": filename,
        "chunks": result.get("chunk_count", 0),
        "embedded": True,
        "message": "知识库已更新",
    }


@app.get("/v1/admin/vision/references")
async def admin_vision_references():
    return {"references": list_references(), "gallery": gallery_summary()}


@app.post("/v1/admin/vision/references")
async def admin_vision_reference_upload(
    file: UploadFile = File(...),
    attraction_id: str = Form(...),
    source_url: str = Form(""),
    note: str = Form(""),
):
    raw = await file.read()
    try:
        return add_reference(
            attraction_id.strip(), raw, source_url=source_url, note=note
        )
    except (ImageValidationError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/v1/admin/vision/references/{file_name:path}")
async def admin_vision_reference_delete(file_name: str):
    if not remove_reference(file_name):
        raise HTTPException(404, "参考图不存在或文件名无效")
    return {"ok": True, "gallery": gallery_summary()}


@app.get("/v1/admin/vision/index")
async def admin_vision_index_status():
    """Report CLIP vector index health (vectors / model / dimension)."""
    return {
        "index": vision_index.status(),
        "clip_service": vision_clip_client.health(),
        "config": {"mode": vision_clip_client.is_available()},
    }


@app.post("/v1/admin/vision/index/rebuild")
async def admin_vision_index_rebuild(force: bool = False, attraction_id: str = ""):
    """Rebuild the CLIP reference index from manifest.json."""
    try:
        return vision_index.build(force=force, attraction_id=attraction_id or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"索引重建失败：{exc}") from exc


@app.delete("/v1/admin/kb/documents/{filename}")
async def admin_kb_delete(filename: str):
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name:
        raise HTTPException(400, "文件名无效")
    target = UPLOADS_DIR / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "只能删除管理员上传的文档")
    previous = target.read_bytes()
    target.unlink()
    try:
        result = await rag.rebuild()
    except RAGClientError as exc:
        target.write_bytes(previous)
        try:
            await rag.rebuild()
        except RAGClientError:
            pass
        raise HTTPException(503, f"知识库重建失败，文件已恢复：{exc}") from exc
    return {
        "ok": True,
        "chunks": result.get("chunk_count", 0),
        "embedded": True,
    }


@app.get("/v1/admin/avatar")
async def admin_avatar_get():
    return {
        "settings": _avatar_settings(),
        "available_avatars": _available_avatars(),
        "avatars": _avatar_catalog(),
        "available_voices": ["female", "male", "tongtong", "chuichui"],
    }


@app.get("/v1/admin/avatar/{avatar_id}/preview")
async def admin_avatar_preview(avatar_id: str):
    preview = find_avatar_preview(AVATAR_DIR, avatar_id)
    if preview is None:
        raise HTTPException(404, "数字人形象预览不存在")
    return FileResponse(preview)


@app.put("/v1/admin/avatar")
async def admin_avatar_update(req: AvatarSettingsRequest):
    available = _available_avatars()
    if req.avatar_id not in available:
        raise HTTPException(400, f"数字人形象不存在：{req.avatar_id}")
    now = datetime.now(timezone.utc).isoformat()
    conn = _db()
    conn.execute(
        """
        INSERT INTO avatar_settings
            -- Empty values satisfy legacy NOT NULL columns when a fresh row is
            -- created. Existing legacy values are left untouched on updates.
            (id, display_name, avatar_id, voice, costume, expression, updated_at)
        VALUES (1,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            display_name=excluded.display_name,
            avatar_id=excluded.avatar_id,
            voice=excluded.voice,
            updated_at=excluded.updated_at
        """,
        (
            req.display_name.strip(),
            req.avatar_id,
            req.voice,
            "",
            "",
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "settings": _avatar_settings()}


@app.get("/v1/admin/location/config")
async def admin_location_config():
    return location_configuration()


@app.put("/v1/admin/location/config")
async def admin_location_config_update(req: LocationConfigurationRequest):
    try:
        return {"ok": True, "config": update_location_configuration(req.model_dump())}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/feedback")
async def feedback(req: FeedbackRequest):
    attraction = attraction_by_id(req.attraction_id.strip())
    if not attraction:
        raise HTTPException(400, "请选择有效的景区或子景点")
    sentiment = analyze_text(req.comment, req.rating)["sentiment"]
    conn = _db()
    conn.execute(
        """
        INSERT INTO feedback
            (id, session_id, attraction_id, scenic_area, attraction_name,
             rating, comment, sentiment, source, emotion_event_id, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(uuid.uuid4()),
            req.session_id or "anonymous",
            attraction["id"],
            attraction["scenic_area"],
            attraction["name"],
            req.rating,
            req.comment.strip(),
            sentiment,
            "live",
            None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "sentiment": sentiment,
        "attraction": attraction,
        "message": "感谢您的反馈",
    }


@app.get("/v1/avatar")
async def public_avatar():
    """Return only the visitor-safe part of the active avatar configuration."""
    settings = _avatar_settings()
    return {"display_name": settings["display_name"]}


@app.get("/v1/attractions")
async def attractions():
    return {"scenic_areas": attraction_catalog(), "source": "dataset.docx"}


@app.post("/v1/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    emotion_event_id = req.emotion_event_id
    if not _linked_emotion_event(emotion_event_id, session_id):
        emotion_event_id = await _record_text_emotion(
            session_id,
            req.message,
            "dialogue-text" if req.input_mode == "text" else "dialogue-voice-text",
        )
    reaction = _avatar_reaction_for_event(emotion_event_id, req.message)
    _log(
        session_id,
        "user",
        req.message,
        {
            "input_mode": req.input_mode,
            "emotion_event_id": emotion_event_id,
            "avatar_reaction": reaction,
        },
    )

    if not req.stream:
        try:
            result = await rag.chat(
                req.message,
                session_id=session_id,
                interest=req.interest,
                spot_id=req.spot_id,
                context=_guide_context(),
                model_route=req.model_route,
            )
        except RAGClientError as exc:
            raise HTTPException(503, str(exc)) from exc
        answer = str(result.get("answer") or "")
        if reaction["prefix"]:
            answer = f"{reaction['prefix']}\n{answer}"
        citations = result.get("citations") or []
        latency_ms = int(result.get("latency_ms") or 0)
        _log(
            session_id,
            "assistant",
            answer,
            {
                "latency_ms": latency_ms,
                "chunk_ids": [c.get("id") for c in citations if isinstance(c, dict)],
                "history_turns": result.get("history_turns", 0),
                "model_route": req.model_route,
                "avatar_reaction": reaction,
            },
        )
        return {
            "session_id": session_id,
            "answer": answer,
            "citations": citations,
            "history_turns": result.get("history_turns", 0),
            "retrieval_ms": result.get("retrieval_ms", 0),
            "latency_ms": latency_ms,
            "model_route": req.model_route,
            "emotion_event_id": emotion_event_id,
            "avatar_reaction": reaction,
        }

    async def event_gen():
        parts: list[str] = []
        citations: list[dict[str, Any]] = []
        latency_ms = 0
        history_turns = 0
        speech_queue = (
            _start_livetalking_speech_worker(
                req.livetalking_session_id,
                speed=float(reaction["voice_speed"]),
            )
            if req.livetalking_session_id
            else None
        )
        segmenter = SpeechSegmenter()
        cancelled = False
        prefix_sent = False
        try:
            async for event in rag.chat_stream(
                req.message,
                session_id=session_id,
                interest=req.interest,
                spot_id=req.spot_id,
                context=_guide_context(),
                model_route=req.model_route,
            ):
                event_type = event.get("type")
                if event_type == "meta":
                    citations = event.get("citations") or []
                    history_turns = int(event.get("history_turns") or 0)
                    event["session_id"] = session_id
                    event["emotion_event_id"] = emotion_event_id
                    event["avatar_reaction"] = reaction
                elif event_type == "delta":
                    token = str(event.get("content") or "")
                    if not prefix_sent and reaction["prefix"]:
                        prefix_sent = True
                        prefix = f"{reaction['prefix']}\n"
                        parts.append(prefix)
                        if speech_queue:
                            # Keep the visual prefix as its own line, but speak
                            # it as an introductory clause together with the
                            # first answer sentence.  A standalone TTS request
                            # here caused an unnatural stop before every reply.
                            spoken_prefix = re.sub(
                                r"[。！？!?，,；;]+$",
                                "",
                                reaction["prefix"].strip(),
                            )
                            for segment in segmenter.feed(f"{spoken_prefix}，"):
                                speech_queue.put_nowait(segment)
                        yield f"data: {json.dumps({'type': 'delta', 'content': prefix}, ensure_ascii=False)}\n\n"
                    parts.append(token)
                    if speech_queue:
                        for segment in segmenter.feed(token):
                            speech_queue.put_nowait(segment)
                elif event_type == "done":
                    latency_ms = int(event.get("latency_ms") or 0)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            cancelled = True
            if req.livetalking_session_id:
                _cancel_livetalking_speech_worker(req.livetalking_session_id)
            raise
        except RAGClientError as exc:
            cancelled = True
            if req.livetalking_session_id:
                _cancel_livetalking_speech_worker(req.livetalking_session_id)
            error = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
        finally:
            if speech_queue and not cancelled:
                for segment in segmenter.finish():
                    speech_queue.put_nowait(segment)
                speech_queue.put_nowait(None)
        full = "".join(parts)
        if full and not cancelled:
            _log(
                session_id,
                "assistant",
                full,
                {
                    "latency_ms": latency_ms,
                    "chunk_ids": [c.get("id") for c in citations if isinstance(c, dict)],
                    "history_turns": history_turns,
                    "model_route": req.model_route,
                    "avatar_reaction": reaction,
                },
            )

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/v1/tts")
async def tts(req: TTSRequest):
    """智谱 GLM-TTS 语音合成，返回 wav 音频。"""
    speak = _speech_text(req.text)
    if not speak:
        raise HTTPException(400, "没有可合成的正文")
    try:
        audio = await zhipu.tts(
            speak,
            voice=req.voice or _avatar_settings()["voice"],
            speed=req.speed,
        )
    except Exception as e:
        raise HTTPException(502, f"tts failed: {e}") from e
    return Response(content=audio, media_type="audio/wav")


@app.post("/v1/tts/stream")
async def tts_stream(req: TTSRequest):
    """Stream GLM-TTS PCM chunks as SSE so playback can start at the first frame."""
    speak = _speech_text(req.text)
    if not speak:
        raise HTTPException(400, "没有可合成的正文")

    async def event_gen():
        try:
            async for event in zhipu.tts_stream(
                speak,
                voice=req.voice or _avatar_settings()["voice"],
                speed=req.speed,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error = {"error": {"message": f"tts stream failed: {exc}"}}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

def _looks_like_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE"


def _normalize_asr_audio(raw: bytes, filename: str) -> tuple[bytes, str]:
    """Convert every browser recording to a model-safe mono 16k WAV."""
    name = (filename or "audio.wav").lower()
    if _looks_like_wav(raw):
        return raw, "audio.wav"

    # MediaRecorder may produce WebM/Opus, Ogg or M4A depending on the
    # browser.  Decode once on the server rather than relying on each browser
    # to decode the blob again through AudioContext.decodeAudioData().
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(
            400,
            "服务器未安装 ffmpeg，无法转换浏览器录音。请联系管理员安装 ffmpeg，或上传 WAV 文件。",
        )
    suffix = Path(name).suffix.lower()
    if suffix not in {".webm", ".ogg", ".m4a", ".mp4", ".mp3", ".aac", ".flac", ".wav"}:
        suffix = ".webm"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{suffix}"
        dst = Path(td) / "out.wav"
        src.write_bytes(raw)
        proc = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-y",
                "-i",
                str(src),
                "-ac",
                "1",
                "-ar",
                "16000",
                str(dst),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not dst.exists():
            raise HTTPException(400, f"音频转码失败: {proc.stderr[-300:]}")
        return dst.read_bytes(), "audio.wav"


@app.post("/v1/asr")
async def asr(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_id: str = Form(""),
    emotion_consent: bool = Form(False),
):
    """Recognize a visitor utterance and optionally analyze its audio emotion."""
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty audio")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(400, "audio too large")
    name = file.filename or "audio.wav"
    try:
        audio, fname = _normalize_asr_audio(raw, name)
        text = await zhipu.asr(audio, filename=fname)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"asr failed: {e}") from e
    safe_session = (session_id or str(uuid.uuid4())).strip()[:128]
    context_turns = _conversation_context(safe_session)
    if emotion_consent:
        event_id = str(uuid.uuid4())
        suffix = Path(fname).suffix.lower()
        if suffix not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
            suffix = ".wav"
        media_dir = DATA_DIR / "emotion_media"
        media_dir.mkdir(parents=True, exist_ok=True)
        media_path = media_dir / f"{event_id}{suffix}"
        media_path.write_bytes(audio)
        now = datetime.now(timezone.utc).isoformat()
        conn = _db()
        conn.execute(
            """
            INSERT INTO emotion_events
                (id, session_id, source, transcript, rating, media_kind,
                 emotion_label, emotion_scores, sentiment, valence, confidence,
                 aspects, status, model_name, analysis_mode, error,
                 created_at, completed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                safe_session,
                "dialogue-voice",
                text[:4000],
                None,
                "audio",
                None,
                "{}",
                None,
                None,
                None,
                "[]",
                "queued",
                emotion_analyzer.model_name,
                None,
                None,
                now,
                None,
            ),
        )
        conn.commit()
        conn.close()
        background_tasks.add_task(
            _process_emotion_job,
            event_id,
            media_path,
            text[:4000],
            None,
            context_turns,
        )
        analysis_status = "queued"
    else:
        event_id = await _record_text_emotion(
            safe_session,
            text,
            source="dialogue-voice-text",
        )
        analysis_status = "completed-text-only"
    return {
        "text": text,
        "session_id": safe_session,
        "emotion_event_id": event_id,
        "emotion_analysis": analysis_status,
        "audio_retained": bool(emotion_consent and EMOTION_KEEP_MEDIA),
        "emotion_timeout_seconds": EMOTION_TIMEOUT_SECONDS if emotion_consent else 0,
    }


@app.post("/v1/vision/guide")
async def vision_guide(
    file: UploadFile = File(...),
    question: str = "",
    session_id: str = Form(""),
    spot_id: str = Form(""),
):
    """Recognise a visitor photo via a multi-stage pipeline.

    Stages: quality check → CLIP reference recall (Top-K) → VLM first pass →
    prior-weighted merge → VLM reference verification (real refutation) →
    config-driven confidence threshold → RAG explanation for the confirmed
    candidate. Every stage degrades gracefully so an empty gallery or an
    unavailable CLIP service never breaks recognition.
    """
    raw = await file.read()
    try:
        prepared = normalize_scenic_image(raw)
    except ImageValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

    # Stage 0: image quality assessment (reject only severely degraded photos).
    quality = vision_quality.assess_scenic_quality(prepared.data)
    if quality.flag == "reject":
        raise HTTPException(400, f"图片质量不足：{quality.advice}")

    location = attraction_by_id(spot_id.strip()) if spot_id else None
    location_id = location["id"] if location and not location["id"].endswith("-ALL") else None
    image_b64 = base64.b64encode(prepared.data).decode("ascii")

    # Stage 1: CLIP reference recall (empty gallery → [] → skip).
    clip_hits: list[dict] = []
    try:
        if vision_clip_client.is_available():
            qvec = vision_clip_client.encode_image(prepared.data)
            if qvec is not None:
                clip_hits = vision_index.search(qvec, CLIP_TOP_K)
    except Exception as exc:  # noqa: BLE001 - CLIP is advisory only
        log.warning("vision CLIP recall failed, degrading: %s", exc)

    # Stage 2: VLM first pass. Narrow the allow-list when CLIP returned candidates.
    try:
        narrow = [h["name"] for h in clip_hits[:3]] if clip_hits else None
        first_pass = await zhipu.vision_describe(
            image_b64, vision_prompt(narrow_names=narrow), mime_type=prepared.mime_type
        )
    except Exception as exc:
        raise HTTPException(502, f"视觉模型调用失败：{exc}") from exc
    vlm_obs = parse_vision_observation(first_pass, location_attraction_id=location_id)

    # Stage 3: merge CLIP recall + VLM candidates with location prior + quality penalty.
    merged = merge_candidates(
        clip_hits, vlm_obs, location_id=location_id, quality_flag=quality.flag
    )

    # Stage 4: VLM reference verification — real refutation, not silent pass.
    reference_items = references_for(
        [item["id"] for item in merged[:3]] + ([location_id] if location_id else []),
        per_attraction=2,
    )
    verification_used = 0
    verification_verdict = "skipped"
    if reference_items:
        refs_for_model = [
            {
                "attraction_name": item["attraction_name"],
                "data_url": "data:image/jpeg;base64," + base64.b64encode(item["data"]).decode("ascii"),
            }
            for item in reference_items
        ]
        try:
            verified_raw = await zhipu.vision_compare(
                image_b64, refs_for_model, mime_type=prepared.mime_type
            )
            verified = parse_vision_observation(verified_raw, location_attraction_id=location_id)
            verification_used = len(reference_items)
            if verified["candidates"]:
                # Re-merge verification candidates on top of the prior merge so
                # CLIP side-evidence is preserved rather than overwritten.
                merged = merge_candidates(
                    clip_hits, verified, location_id=location_id,
                    quality_flag=quality.flag, prior_merge=merged,
                )
                verification_verdict = "confirmed"
            else:
                # Legally-empty verification = the VLM looked at the reference
                # images and could not match any. That is a negative signal:
                # demote and force confirmation instead of keeping the first pass.
                merged = demote_after_refutation(merged)
                verification_verdict = "refuted"
        except Exception as exc:
            # Verification errored (provider rejected multi-image, timeout, ...).
            # Treat as uncertain, not refuted: apply a softer penalty and log it.
            log.warning("vision_compare verification failed: %s", exc)
            merged = demote_after_error(merged)
            verification_verdict = "error"

    # Stage 5: config-driven confidence threshold.
    decision = decide_confidence(merged)
    observation = {
        "summary": vlm_obs["summary"],
        "candidates": merged,
        "confidence": decision["confidence"],
        "requires_confirmation": decision["requires_confirmation"],
    }

    candidate_names = "、".join(item["name"] for item in observation["candidates"]) or "未匹配到资料库景点"
    safe_session = (session_id or str(uuid.uuid4())).strip()[:128]
    prompt = question.strip() or "这是哪个景点？请结合景区知识讲解。"
    context = _guide_context({
        "视觉识别结果": observation["summary"],
        "资料库候选景点": candidate_names,
        "确认要求": "候选不确定时应提示游客确认，不得把候选说成确定事实。",
        "参考图复核": (
            f"已使用 {verification_used} 张管理员参考图（{verification_verdict}）"
            if verification_used else "尚无对应参考图，仅作首轮视觉候选"
        ),
    })
    if location:
        context["当前位置先验"] = f"{location['scenic_area']}·{location['name']}（仅作候选辅助）"
    # RAG explains the confirmed candidate with grounded citations; it does not
    # "calibrate" the recognition result.
    try:
        result = await rag.chat(prompt, session_id=safe_session, context=context)
    except RAGClientError as exc:
        raise HTTPException(503, str(exc)) from exc
    answer = result.get("answer", "")
    if observation["requires_confirmation"]:
        names = candidate_names if observation["candidates"] else "暂未匹配到资料库景点"
        answer = f"我初步识别到：{names}。请您确认候选景点后，我再为您做准确讲解。\n{answer}"
    return {
        "vision": first_pass,
        "observation": observation,
        "answer": answer,
        "citations": result.get("citations", []),
        "session_id": safe_session,
        "image": {
            "width": prepared.width,
            "sha256": prepared.sha256,
            "height": prepared.height,
            "normalized": True,
            "quality": quality.to_dict(),
        },
        "stages": {
            "clip_hits": [
                {"attraction_id": h["attraction_id"], "name": h["name"], "sim": h["sim"]}
                for h in clip_hits[:5]
            ],
            "verification": {"used": verification_used, "verdict": verification_verdict},
            "quality": quality.flag,
        },
        "reference_verification": {
            "used": verification_used,
            "verdict": verification_verdict,
            "gallery": gallery_summary(),
            "message": "已用本地参考图二次复核" if verification_used else "尚未配置该候选的参考图",
        },
    }


@app.post("/v1/vision/confirm")
async def vision_confirm(req: VisionConfirmRequest):
    """游客确认识景结果后，启动指定景点的讲解流程。"""
    attraction = attraction_by_id(req.attraction_id)
    if not attraction or attraction["id"].endswith("-ALL"):
        raise HTTPException(400, "景点不存在或不支持")

    safe_session = (req.session_id or str(uuid.uuid4())).strip()[:128]
    prompt = req.question.strip() or f"请为我讲解{attraction['name']}。"
    context = _guide_context({
        "确认景点": f"{attraction['scenic_area']}·{attraction['name']}",
        "确认来源": "游客确认（识景候选已验证）",
    })

    try:
        result = await rag.chat(prompt, session_id=safe_session, context=context)
    except RAGClientError as exc:
        raise HTTPException(503, str(exc)) from exc

    answer = result.get("answer", "")

    # 如果游客确认的景点与模型首轮候选不符，记录纠错样本
    if attraction["name"] not in req.model_candidates:
        record_vision_correction(
            model_candidates=[{"name": c} for c in req.model_candidates],
            user_confirmed_id=req.attraction_id,
            image_sha256=req.image_sha256,
        )

    return {
        "ok": True,
        "attraction_id": req.attraction_id,
        "attraction_name": attraction["name"],
        "answer": answer,
        "citations": result.get("citations", []),
        "session_id": safe_session,
    }


@app.post("/v1/vision/correction")
async def record_vision_error(req: VisionCorrectionRequest):
    """记录视觉识别的纠错案例。"""
    record_vision_correction(
        model_candidates=[{"name": c} for c in req.model_candidates],
        user_confirmed_id=req.user_confirmed,
        image_sha256=req.image_sha256,
    )
    return {"ok": True, "message": "纠错样本已记录"}


@app.get("/v1/admin/vision/corrections")
async def admin_list_vision_corrections():
    """管理员查看近期的纠错样本，用于质量评估。"""
    corrections = list_vision_corrections(limit=200)

    # 统计纠错类型
    total = len(corrections)
    missed = sum(1 for r in corrections if not r.get("model_candidates"))
    confused = total - missed

    return {
        "corrections": corrections,
        "stats": {
            "total_corrections": total,
            "missed_correct_count": missed,  # 模型没给出正确答案
            "confused_count": confused,       # 模型给出候选但与实际不符
        },
        "gallery": gallery_summary(),
    }


async def _process_emotion_job(
    job_id: str,
    media_path: Path,
    transcript: str,
    rating: Optional[int],
    context_turns: Optional[list[dict[str, str]]] = None,
) -> None:
    if not _claim_emotion_job(job_id):
        return
    try:
        result = await emotion_analyzer.analyze(
            media_path,
            transcript,
            rating,
            context_turns=context_turns,
        )
        completed_at = datetime.now(timezone.utc).isoformat()
        conn = _db()
        conn.execute(
            """
            UPDATE emotion_events
               SET emotion_label=?, emotion_scores=?, sentiment=?, valence=?,
                   confidence=?, aspects=?, status='completed', model_name=?,
                   analysis_mode=?, error=?, completed_at=?
             WHERE id=?
            """,
            (
                result.get("emotion"),
                json.dumps(result.get("scores") or {}, ensure_ascii=False),
                result.get("sentiment"),
                result.get("valence"),
                result.get("confidence"),
                json.dumps(result.get("aspects") or [], ensure_ascii=False),
                result.get("model"),
                result.get("analysis_mode"),
                result.get("model_error") or None,
                completed_at,
                job_id,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        conn = _db()
        conn.execute(
            "UPDATE emotion_events SET status='failed', error=?, completed_at=? "
            "WHERE id=?",
            (
                str(exc)[:2000],
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )
        conn.commit()
        conn.close()
    finally:
        if not EMOTION_KEEP_MEDIA:
            media_path.unlink(missing_ok=True)


@app.get("/v1/admin/emotion/status")
async def admin_emotion_status():
    status = emotion_analyzer.status()
    conn = _db()
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM emotion_events GROUP BY status"
    ).fetchall()
    conn.close()
    status["jobs"] = {str(name): int(count) for name, count in rows}
    status["media_retained"] = EMOTION_KEEP_MEDIA
    return status


@app.get("/v1/admin/emotion/events/{job_id}")
async def admin_emotion_event(job_id: str):
    conn = _db()
    row = conn.execute(
        """
        SELECT id, session_id, source, transcript, rating, media_kind,
               emotion_label, emotion_scores, sentiment, valence, confidence,
               aspects, status, model_name, analysis_mode, error,
               created_at, completed_at
          FROM emotion_events WHERE id=?
        """,
        (job_id,),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "情感分析任务不存在")
    return {
        "id": row[0],
        "session_id": row[1],
        "source": row[2],
        "transcript": row[3],
        "rating": row[4],
        "media_kind": row[5],
        "emotion": row[6],
        "scores": json.loads(row[7] or "{}"),
        "sentiment": row[8],
        "valence": row[9],
        "confidence": row[10],
        "aspects": json.loads(row[11] or "[]"),
        "status": row[12],
        "model": row[13],
        "analysis_mode": row[14],
        "error": row[15],
        "created_at": row[16],
        "completed_at": row[17],
    }


@app.get("/v1/emotion/reaction/{job_id}")
async def visitor_emotion_reaction(job_id: str, session_id: str = ""):
    """Expose only a session owner's safe avatar reaction, never raw media."""
    safe_session = (session_id or "").strip()[:128]
    if not safe_session:
        raise HTTPException(400, "缺少会话标识")
    conn = _db()
    row = conn.execute(
        """
        SELECT emotion_label, sentiment, confidence, status, analysis_mode
          FROM emotion_events
         WHERE id=? AND session_id=? AND source LIKE 'dialogue-%'
        """,
        (job_id, safe_session),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "情绪分析任务不存在")
    completed = row[3] == "completed"
    return {
        "status": row[3],
        "analysis_mode": row[4],
        "avatar_reaction": avatar_reaction(
            emotion=row[0] if completed else None,
            sentiment=row[1] if completed else None,
            confidence=row[2] if completed else None,
        ),
    }


# ---- 游客隐私：导出 / 删除本人数据 ----
# 原始音频默认在分析后删除（EMOTION_KEEP_MEDIA=false），对话文本与情绪标签按
# CHAT_RETENTION_DAYS / EMOTION_TRANSCRIPT_RETENTION_DAYS（默认 30 天）自动清理；
# 聚合数据长期保留。这里提供按 session_id 的主动导出/删除，供隐私告知落地。

@app.get("/v1/visitor/data/export")
async def visitor_data_export(session_id: str):
    """Export a visitor's own dialogue, emotion labels and feedback by session_id."""
    safe_session = (session_id or "").strip()[:128]
    if not safe_session:
        raise HTTPException(400, "缺少会话标识")
    conn = _db()
    try:
        chats = conn.execute(
            "SELECT role, content, created_at FROM chat_logs WHERE session_id=? ORDER BY created_at",
            (safe_session,),
        ).fetchall()
        emotions = conn.execute(
            """SELECT id, source, emotion_label, sentiment, confidence, aspects, status, created_at
                 FROM emotion_events WHERE session_id=? ORDER BY created_at""",
            (safe_session,),
        ).fetchall()
        feedbacks = conn.execute(
            """SELECT attraction_id, attraction_name, rating, comment, sentiment, created_at
                 FROM feedback WHERE session_id=? ORDER BY created_at""",
            (safe_session,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "session_id": safe_session,
        "retention_days": {
            "chat": CHAT_RETENTION_DAYS,
            "emotion_transcript": EMOTION_TRANSCRIPT_RETENTION_DAYS,
        },
        "dialogue": [
            {"role": r[0], "content": r[1], "created_at": r[2]} for r in chats
        ],
        "emotion_events": [
            {
                "id": r[0], "source": r[1], "emotion": r[2], "sentiment": r[3],
                "confidence": r[4], "aspects": json.loads(r[5] or "[]"),
                "status": r[6], "created_at": r[7],
            }
            for r in emotions
        ],
        "feedback": [
            {
                "attraction_id": r[0], "attraction_name": r[1], "rating": r[2],
                "comment": r[3], "sentiment": r[4], "created_at": r[5],
            }
            for r in feedbacks
        ],
        "note": "原始音频默认在分析后删除；本接口导出对话文本、情绪标签与评分。聚合统计长期保留。",
    }


@app.delete("/v1/visitor/data")
async def visitor_data_delete(session_id: str):
    """Delete a visitor's raw dialogue/transcript/feedback by session_id.

    Aggregated analytics (counts, averages) are derived and retained; only the
    visitor-identifiable raw rows are removed.
    """
    safe_session = (session_id or "").strip()[:128]
    if not safe_session:
        raise HTTPException(400, "缺少会话标识")
    conn = _db()
    try:
        chat_n = conn.execute(
            "DELETE FROM chat_logs WHERE session_id=?", (safe_session,)
        ).rowcount
        emo_n = conn.execute(
            """UPDATE emotion_events SET transcript='[应游客要求删除]'
                 WHERE session_id=? AND transcript IS NOT NULL
                   AND transcript != '[应游客要求删除]'""",
            (safe_session,),
        ).rowcount
        emo_del = conn.execute(
            "DELETE FROM emotion_events WHERE session_id=? AND source NOT LIKE 'dialogue-%'",
            (safe_session,),
        ).rowcount
        fb_n = conn.execute(
            "DELETE FROM feedback WHERE session_id=?", (safe_session,)
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    return {
        "session_id": safe_session,
        "deleted": {
            "dialogue_rows": int(chat_n or 0),
            "emotion_transcripts_redacted": int(emo_n or 0),
            "non_dialogue_emotion_rows": int(emo_del or 0),
            "feedback_rows": int(fb_n or 0),
        },
        "note": "已删除该会话的可识别原始数据；聚合统计长期保留。",
    }


@app.get("/v1/admin/analytics/historical")
async def admin_historical_analytics():
    return await asyncio.to_thread(tourism_analytics.load)


@app.post("/v1/admin/analytics/historical/rebuild")
async def admin_historical_analytics_rebuild():
    return await asyncio.to_thread(tourism_analytics.load, True)


@app.post("/v1/admin/analytics/historical/compact")
async def admin_historical_analytics_compact():
    return await asyncio.to_thread(compact_tourism_database)


@app.get("/v1/admin/analytics/overview")
async def admin_analytics_overview():
    conn = _db()
    try:
        return build_overview(conn, ROUTES)
    finally:
        conn.close()


@app.get("/v1/admin/demo-data")
async def admin_demo_data_status():
    conn = _db()
    try:
        return demo_data_status(conn)
    finally:
        conn.close()


@app.post("/v1/admin/demo-data")
async def admin_seed_demo_data():
    conn = _db()
    try:
        return seed_demo_data(conn)
    finally:
        conn.close()


@app.delete("/v1/admin/demo-data")
async def admin_clear_demo_data():
    conn = _db()
    try:
        return clear_demo_data(conn)
    finally:
        conn.close()


@app.get("/v1/stats/overview")
async def stats_overview():
    conn = _db()
    try:
        overview = build_overview(conn, ROUTES)
        return {
            key: overview[key]
            for key in (
                "service_turns",
                "unique_visitors",
                "today_visitors",
                "week_visitors",
                "avg_satisfaction",
                "avg_response_ms",
            )
        }
    finally:
        conn.close()


@app.get("/admin")
@app.get("/admin/")
async def admin_index():
    admin_path = STATIC_DIR / "admin.html"
    if admin_path.exists():
        return FileResponse(admin_path)
    raise HTTPException(404, "管理后台页面尚未生成")


@app.get("/login")
async def admin_login_page(request: Request):
    if _admin_authenticated(request):
        return RedirectResponse("/admin", status_code=303)
    login_path = STATIC_DIR / "admin-login.html"
    if login_path.exists():
        return FileResponse(login_path)
    raise HTTPException(404, "管理后台登录页面尚未生成")


@app.get("/")
async def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        _schedule_livetalking_warmup()
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return {
        "name": "Lingshan AI Guide API",
        "docs": "/docs",
        "health": "/health",
    }


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
