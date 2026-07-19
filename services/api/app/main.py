from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import secrets
import sqlite3
import subprocess
import uuid
import wave
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
    ADMIN_SESSION_SECRET,
    ADMIN_SESSION_TTL_SECONDS,
    ADMIN_USERNAME,
    CORS_ORIGINS,
    DATA_DIR,
    DOCS_DIR,
    EMOTION_KEEP_MEDIA,
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
from .avatar_catalog import find_avatar_preview, list_avatar_ids
from .emotion_analysis import analyze_text, emotion_analyzer
from .kb import ROUTES
from .location import resolve_location
from .rag_client import RAGClientError, rag
from .speech_segments import SpeechSegmenter
from .tourism_analytics import ensure_tourism_schema, tourism_analytics
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
    model_route: Literal["cloud", "local"] = "cloud"
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
    costume: str = Field("禅意导游", max_length=50)
    expression: str = Field("亲切自然", max_length=50)


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


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
    conn = sqlite3.connect(LOG_DB)
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
        "SELECT display_name, avatar_id, voice, costume, expression, updated_at "
        "FROM avatar_settings WHERE id=1"
    ).fetchone()
    conn.close()
    if row:
        return {
            "display_name": row[0],
            "avatar_id": row[1],
            "voice": row[2],
            "costume": row[3],
            "expression": row[4],
            "updated_at": row[5],
        }
    return {
        "display_name": "灵山小向导",
        "avatar_id": LIVETALKING_AVATAR_ID,
        "voice": TTS_VOICE,
        "costume": "禅意导游",
        "expression": "亲切自然",
        "updated_at": "",
    }


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


def _speech_text(text: str) -> str:
    """Remove model-only JSON metadata before any TTS provider sees it."""
    spoken_lines: list[str] = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith(("{", "```json", "```JSON")):
            break
        spoken_lines.append(line)
    return "\n".join(spoken_lines).strip()


def _pcm16_mono_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap one continuous little-endian PCM16 stream in a WAV container."""
    if not pcm:
        raise ValueError("empty PCM audio")
    if len(pcm) % 2:
        raise ValueError("PCM16 audio must contain complete samples")
    if not 8_000 <= sample_rate <= 96_000:
        raise ValueError(f"unsupported PCM sample rate: {sample_rate}")

    wav_file = io.BytesIO()
    with wave.open(wav_file, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)
    return wav_file.getvalue()


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_api_key()
    conn = _db()
    conn.execute(
        "UPDATE emotion_events SET status='failed', "
        "error='服务重启，未完成的分析任务已终止' "
        "WHERE status IN ('queued','processing')"
    )
    conn.commit()
    conn.close()
    turn_config_error = cloudflare_turn_config_error()
    if turn_config_error:
        raise RuntimeError(turn_config_error)
    if PUBLIC_ADMIN_URL and len(ADMIN_PASSWORD) < 12:
        raise RuntimeError("公网管理后台密码至少需要 12 个字符")
    if PUBLIC_ADMIN_URL and ADMIN_SESSION_SECRET and len(ADMIN_SESSION_SECRET) < 32:
        raise RuntimeError("ADMIN_SESSION_SECRET 至少需要 32 个字符")
    yield


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
    if PUBLIC_ADMIN_URL:
        return origin == PUBLIC_ADMIN_URL
    hostname = request.url.hostname or "localhost"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    return origin == f"https://{hostname}:{ADMIN_PORT}"


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
        path in {"/", "/login", "/health", "/favicon.ico"}
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
) -> None:
    if interrupt:
        await _livetalking_post(
            "/interrupt_talk",
            {"sessionid": session_id},
        )

    speech_text = _speech_text(text)
    if not speech_text:
        return

    pcm_audio = bytearray()
    sample_rate: Optional[int] = None
    chunk_count = 0
    tts_started_at = asyncio.get_running_loop().time()
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        async for event in zhipu.tts_stream(
            speech_text,
            voice=_avatar_settings()["voice"],
            speed=LIVETALKING_TTS_SPEED,
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
            pcm_audio.extend(pcm_chunk)
            if len(pcm_audio) > 32 * 1024 * 1024:
                raise RuntimeError("GLM-TTS audio exceeds 32 MiB")

        if not pcm_audio or sample_rate is None:
            raise RuntimeError("GLM-TTS returned no PCM audio")

        # Upload one complete semantic segment. LiveTalking resamples and fades
        # every uploaded WAV independently, so forwarding each provider chunk as
        # its own WAV creates artificial micro-pauses and can clip syllables at
        # chunk boundaries.
        wav_audio = _pcm16_mono_wav(bytes(pcm_audio), sample_rate)
        response = await client.post(
            f"{LIVETALKING_URL}/humanaudio",
            data={"sessionid": session_id},
            files={"file": ("speech.wav", wav_audio, "audio/wav")},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("code") not in (None, 0):
            raise RuntimeError(data.get("msg") or "LiveTalking audio upload failed")
        _mark_livetalking_used()

        print(
            "[livetalking] queued semantic TTS audio: "
            f"session={session_id} chunks={chunk_count} "
            f"samples={len(pcm_audio) // 2} sample_rate={sample_rate} "
            f"total_ms={round((asyncio.get_running_loop().time() - tts_started_at) * 1000)}"
        )


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
) -> asyncio.Queue[Optional[str]]:
    _cancel_livetalking_speech_worker(session_id)
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    async def run() -> None:
        first = True
        while True:
            segment = await queue.get()
            if segment is None:
                return
            await _stream_tts_to_livetalking(
                session_id,
                segment,
                interrupt=first,
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
            (id, display_name, avatar_id, voice, costume, expression, updated_at)
        VALUES (1,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            display_name=excluded.display_name,
            avatar_id=excluded.avatar_id,
            voice=excluded.voice,
            costume=excluded.costume,
            expression=excluded.expression,
            updated_at=excluded.updated_at
        """,
        (
            req.display_name.strip(),
            req.avatar_id,
            req.voice,
            req.costume,
            req.expression,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "settings": _avatar_settings()}


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
    _log(
        session_id,
        "user",
        req.message,
        {"input_mode": req.input_mode, "emotion_event_id": emotion_event_id},
    )

    if not req.stream:
        try:
            result = await rag.chat(
                req.message,
                session_id=session_id,
                interest=req.interest,
                spot_id=req.spot_id,
                model_route=req.model_route,
            )
        except RAGClientError as exc:
            raise HTTPException(503, str(exc)) from exc
        answer = str(result.get("answer") or "")
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
        }

    async def event_gen():
        parts: list[str] = []
        citations: list[dict[str, Any]] = []
        latency_ms = 0
        history_turns = 0
        speech_queue = (
            _start_livetalking_speech_worker(req.livetalking_session_id)
            if req.livetalking_session_id
            else None
        )
        segmenter = SpeechSegmenter()
        cancelled = False
        try:
            async for event in rag.chat_stream(
                req.message,
                session_id=session_id,
                interest=req.interest,
                spot_id=req.spot_id,
                model_route=req.model_route,
            ):
                event_type = event.get("type")
                if event_type == "meta":
                    citations = event.get("citations") or []
                    history_turns = int(event.get("history_turns") or 0)
                    event["session_id"] = session_id
                    event["emotion_event_id"] = emotion_event_id
                elif event_type == "delta":
                    token = str(event.get("content") or "")
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
    """Ensure payload is something glm-asr accepts (prefer wav)."""
    name = (filename or "audio.wav").lower()
    if _looks_like_wav(raw) or name.endswith((".wav", ".mp3", ".m4a")):
        if _looks_like_wav(raw) and not name.endswith(".wav"):
            return raw, "audio.wav"
        return raw, filename or "audio.wav"

    # browser often sends webm/ogg — try ffmpeg if present
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(
            400,
            "当前音频格式(webm/ogg)不被识别接口支持。请用页面「按住说话」(会录成 wav)，或上传 wav/mp3。",
        )
    suffix = ".webm" if "webm" in name else ".ogg"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{suffix}"
        dst = Path(td) / "out.wav"
        src.write_bytes(raw)
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", str(src), "-ac", "1", "-ar", "16000", str(dst)],
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
    }


@app.post("/v1/vision/guide")
async def vision_guide(file: UploadFile = File(...), question: str = "这是灵山胜境的哪个景点？请结合景区知识讲解。"):
    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(400, "image too large")
    b64 = base64.b64encode(raw).decode("ascii")
    # first let vision describe, then ground with RAG
    vision_text = await zhipu.vision_describe(
        b64,
        "请识别图片中可能的景区建筑/雕像/场景，用中文简短描述关键视觉特征与可能景点名。",
    )
    try:
        result = await rag.chat(
            question,
            session_id=str(uuid.uuid4()),
            context={"视觉识别结果": vision_text},
        )
    except RAGClientError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "vision": vision_text,
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
    }


async def _process_emotion_job(
    job_id: str,
    media_path: Path,
    transcript: str,
    rating: Optional[int],
    context_turns: Optional[list[dict[str, str]]] = None,
) -> None:
    conn = _db()
    conn.execute(
        "UPDATE emotion_events SET status='processing' WHERE id=?",
        (job_id,),
    )
    conn.commit()
    conn.close()
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


@app.get("/v1/admin/analytics/historical")
async def admin_historical_analytics():
    return await asyncio.to_thread(tourism_analytics.load)


@app.post("/v1/admin/analytics/historical/rebuild")
async def admin_historical_analytics_rebuild():
    return await asyncio.to_thread(tourism_analytics.load, True)


@app.get("/v1/admin/analytics/overview")
async def admin_analytics_overview():
    conn = _db()
    try:
        return build_overview(conn, ROUTES)
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
        return FileResponse(index_path)
    return {
        "name": "Lingshan AI Guide API",
        "docs": "/docs",
        "health": "/health",
    }


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
