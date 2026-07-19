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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
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
from .admin_auth import ADMIN_COOKIE_NAME, create_admin_token, verify_admin_token
from .avatar_catalog import find_avatar_preview, list_avatar_ids
from .kb import ROUTES
from .location import resolve_location
from .rag_client import RAGClientError, rag
from .speech_segments import SpeechSegmenter
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
    return_audio: bool = False


class LiveTalkingSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    transport: Optional[Literal["http", "webrtc"]] = None


class LiveTalkingHttpSessionRequest(BaseModel):
    avatar: Optional[str] = None


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = None
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
            rating INTEGER NOT NULL,
            comment TEXT,
            sentiment TEXT,
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
    conn.commit()
    return conn


def _infer_sentiment(text: str, rating: Optional[int] = None) -> str:
    if rating is not None:
        if rating >= 4:
            return "positive"
        if rating <= 2:
            return "negative"
    positive = ("喜欢", "满意", "很好", "不错", "漂亮", "方便", "感谢", "推荐", "开心")
    negative = ("不满", "失望", "不好", "太慢", "拥挤", "排队", "投诉", "贵", "累", "生气")
    positive_hits = sum(word in text for word in positive)
    negative_hits = sum(word in text for word in negative)
    if positive_hits > negative_hits:
        return "positive"
    if negative_hits > positive_hits:
        return "negative"
    return "neutral"


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


def _admin_url(request: Request, path: str = "/admin") -> str:
    if PUBLIC_ADMIN_URL:
        return f"{PUBLIC_ADMIN_URL}{path}"
    hostname = request.url.hostname or "localhost"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    return f"https://{hostname}:{ADMIN_PORT}{path}"


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
        if admin_page or path == "/login":
            return RedirectResponse(_admin_url(request, "/admin"), status_code=307)
        if admin_api:
            return JSONResponse(
                {"detail": "管理接口仅在独立后台端口提供"},
                status_code=404,
            )
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


_livetalking_start_lock = asyncio.Lock()
_livetalking_last_used_file = ROOT / "deploy" / "livetalking" / "last-used"


def _mark_livetalking_used() -> None:
    _livetalking_last_used_file.parent.mkdir(parents=True, exist_ok=True)
    _livetalking_last_used_file.touch()


async def _ensure_livetalking_started() -> bool:
    if not LIVETALKING_ENABLED:
        raise HTTPException(503, "LiveTalking is disabled")
    async with _livetalking_start_lock:
        was_ready = False
        try:
            async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
                response = await client.get(f"{LIVETALKING_URL}/api/admin/config")
            response.raise_for_status()
        except httpx.HTTPError:
            pass
        else:
            was_ready = True

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
    return not was_ready


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
    elif TURN_ENABLED and not PUBLIC_APP_URL:
        hostname = request.url.hostname or "localhost"
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        turn = {
            "urls": [f"turn:{hostname}:{TURN_PORT}?transport=tcp"],
            "username": TURN_USERNAME,
            "credential": TURN_CREDENTIAL,
        }
        ice_servers = [turn]
    elif PUBLIC_APP_URL:
        ice_detail = "公网模式需要配置 Cloudflare TURN"

    status = {
        "enabled": LIVETALKING_ENABLED,
        "ready": False,
        "on_demand": True,
        "avatar_id": avatar_id,
        "available_avatars": _available_avatars(),
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
    elif PUBLIC_APP_URL:
        raise HTTPException(503, "公网模式需要配置 Cloudflare TURN")
    return await _livetalking_post("/offer", payload, timeout=20.0)


@app.post("/v1/livetalking/session")
async def livetalking_http_session(req: LiveTalkingHttpSessionRequest):
    payload = {"avatar": req.avatar or _avatar_settings()["avatar_id"]}
    data = await _livetalking_post("/session", payload, timeout=120.0)
    session_id = str(data.get("sessionid") or "")
    if not session_id:
        raise HTTPException(502, "LiveTalking did not return an HTTP session")
    return {
        "code": 0,
        "session_id": session_id,
        "mjpeg_url": f"/v1/livetalking/mjpeg?session_id={session_id}",
        "transport": "http",
    }


@app.get("/v1/livetalking/mjpeg")
async def livetalking_mjpeg(session_id: str):
    if not LIVETALKING_ENABLED:
        raise HTTPException(503, "LiveTalking is disabled")

    async def stream():
        async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
            async with client.stream(
                "GET",
                f"{LIVETALKING_URL}/mjpeg",
                params={"sessionid": session_id},
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_raw(chunk_size=65536):
                    yield chunk

    return StreamingResponse(
        stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/v1/livetalking/frame.jpg")
async def livetalking_frame_jpg(session_id: str):
    if not LIVETALKING_ENABLED:
        raise HTTPException(503, "LiveTalking is disabled")
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            response = await client.get(
                f"{LIVETALKING_URL}/frame.jpg",
                params={"sessionid": session_id},
            )
        if response.status_code == 404:
            raise HTTPException(404, "session not found")
        if response.status_code >= 400 or not response.content:
            raise HTTPException(503, "no frame yet")
        return Response(
            content=response.content,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"LiveTalking frame proxy failed: {exc}") from exc


async def _stream_tts_to_livetalking(
    session_id: str,
    text: str,
    *,
    interrupt: bool,
    return_audio: bool = False,
) -> dict[str, Any]:
    if interrupt:
        await _livetalking_post(
            "/interrupt_talk",
            {"sessionid": session_id},
        )

    speech_text = _speech_text(text)
    if not speech_text:
        return {"code": 0, "msg": "ok"}

    total_pcm_bytes = 0
    pcm_audio = bytearray()
    sample_rate: Optional[int] = None
    chunk_count = 0
    tts_started_at = asyncio.get_running_loop().time()
    first_upload_ms: Optional[int] = None
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
            if return_audio:
                pcm_audio.extend(pcm_chunk)
            chunk_count += 1
            total_pcm_bytes += len(pcm_chunk)
            if total_pcm_bytes > 32 * 1024 * 1024:
                raise RuntimeError("GLM-TTS audio exceeds 32 MiB")

            if not return_audio:
                # WebRTC carries audio itself, so forward each TTS chunk at once.
                wav_audio = _pcm16_mono_wav(pcm_chunk, sample_rate)
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
                if first_upload_ms is None:
                    first_upload_ms = round(
                        (asyncio.get_running_loop().time() - tts_started_at) * 1000
                    )

        if not total_pcm_bytes or sample_rate is None:
            raise RuntimeError("GLM-TTS returned no PCM audio")

        if return_audio:
            # HTTP video has no media audio track. Queue the complete sentence and
            # return the same WAV to the browser so voice and mouth start together.
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
            first_upload_ms = round(
                (asyncio.get_running_loop().time() - tts_started_at) * 1000
            )

        print(
            "[livetalking] streamed TTS audio: "
            f"session={session_id} chunks={chunk_count} "
            f"samples={total_pcm_bytes // 2} sample_rate={sample_rate} "
            f"first_upload_ms={first_upload_ms} "
            f"total_ms={round((asyncio.get_running_loop().time() - tts_started_at) * 1000)}"
        )

    result: dict[str, Any] = {"code": 0, "msg": "ok"}
    if return_audio and pcm_audio and sample_rate is not None:
        wav_audio = _pcm16_mono_wav(bytes(pcm_audio), sample_rate)
        result["audio_wav_base64"] = base64.b64encode(wav_audio).decode("ascii")
        result["sample_rate"] = sample_rate
    return result


async def _stream_synced_tts_to_livetalking(
    session_id: str,
    text: str,
    *,
    interrupt: bool,
):
    """Feed each GLM-TTS PCM chunk to Wav2Lip and yield it to the browser."""
    if interrupt:
        await _livetalking_post(
            "/interrupt_talk",
            {"sessionid": session_id},
        )

    speech_text = _speech_text(text)
    if not speech_text:
        return

    total_pcm_bytes = 0
    chunk_count = 0
    sample_rate: Optional[int] = None
    started_at = asyncio.get_running_loop().time()
    first_chunk_ms: Optional[int] = None
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

            total_pcm_bytes += len(pcm_chunk)
            chunk_count += 1
            if total_pcm_bytes > 32 * 1024 * 1024:
                raise RuntimeError("GLM-TTS audio exceeds 32 MiB")

            wav_audio = _pcm16_mono_wav(pcm_chunk, event_sample_rate)
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
            if first_chunk_ms is None:
                first_chunk_ms = round(
                    (asyncio.get_running_loop().time() - started_at) * 1000
                )
            yield event

    if not total_pcm_bytes:
        raise RuntimeError("GLM-TTS returned no PCM audio")
    print(
        "[livetalking] synced TTS stream: "
        f"session={session_id} chunks={chunk_count} "
        f"samples={total_pcm_bytes // 2} sample_rate={sample_rate} "
        f"first_chunk_ms={first_chunk_ms} "
        f"total_ms={round((asyncio.get_running_loop().time() - started_at) * 1000)}"
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
        return await _stream_tts_to_livetalking(
            req.session_id,
            req.text,
            interrupt=req.interrupt,
            return_audio=req.return_audio,
        )
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise HTTPException(502, f"LiveTalking streaming TTS failed: {exc}") from exc


@app.post("/v1/livetalking/speak-stream")
async def livetalking_speak_stream(req: LiveTalkingSpeakRequest):
    async def event_gen():
        try:
            async for event in _stream_synced_tts_to_livetalking(
                req.session_id,
                req.text,
                interrupt=req.interrupt,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            error = {
                "error": {
                    "message": f"LiveTalking streaming TTS failed: {exc}"
                }
            }
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


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
    path = "/session/close" if req.transport == "http" else "/close_session"
    return await _livetalking_post(
        path,
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
    sentiment = _infer_sentiment(req.comment, req.rating)
    conn = _db()
    conn.execute(
        "INSERT INTO feedback VALUES (?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            req.session_id or "anonymous",
            req.rating,
            req.comment.strip(),
            sentiment,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "sentiment": sentiment, "message": "感谢您的反馈"}


@app.post("/v1/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    _log(session_id, "user", req.message)

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
        effective_model_route = str(result.get("model_route") or req.model_route)
        _log(
            session_id,
            "assistant",
            answer,
            {
                "latency_ms": latency_ms,
                "chunk_ids": [c.get("id") for c in citations if isinstance(c, dict)],
                "history_turns": result.get("history_turns", 0),
                "model_route": effective_model_route,
            },
        )
        return {
            "session_id": session_id,
            "answer": answer,
            "citations": citations,
            "history_turns": result.get("history_turns", 0),
            "retrieval_ms": result.get("retrieval_ms", 0),
            "latency_ms": latency_ms,
            "model_route": effective_model_route,
        }

    async def event_gen():
        parts: list[str] = []
        citations: list[dict[str, Any]] = []
        latency_ms = 0
        history_turns = 0
        effective_model_route = req.model_route
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
                    effective_model_route = str(event.get("model_route") or req.model_route)
                    event["session_id"] = session_id
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
                    "model_route": effective_model_route,
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
async def asr(file: UploadFile = File(...)):
    """智谱语音识别。推荐上传 wav/mp3；webm 需本机有 ffmpeg。"""
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
    return {"text": text}


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


@app.get("/v1/stats/overview")
async def stats_overview():
    conn = _db()
    user_rows = conn.execute(
        "SELECT session_id, content, meta, created_at FROM chat_logs "
        "WHERE role='user' ORDER BY created_at DESC"
    ).fetchall()
    assistant_rows = conn.execute(
        "SELECT meta FROM chat_logs WHERE role='assistant' ORDER BY created_at DESC LIMIT 500"
    ).fetchall()
    feedback_rows = conn.execute(
        "SELECT rating, comment, sentiment, created_at FROM feedback "
        "ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    week_start = (now.date() - timedelta(days=6)).isoformat()
    recent_questions = [row[1] for row in user_rows[:200]]
    today_sessions = {row[0] for row in user_rows if row[3][:10] == today}
    week_sessions = {row[0] for row in user_rows if row[3][:10] >= week_start}

    hot = ["灵山大佛", "梵宫", "九龙灌浴", "祥符禅寺", "路线", "五印坛城"]
    counts = {key: sum(1 for question in recent_questions if key in question) for key in hot}

    daily = []
    for offset in range(6, -1, -1):
        day = (now.date() - timedelta(days=offset)).isoformat()
        day_rows = [row for row in user_rows if row[3][:10] == day]
        daily.append(
            {
                "date": day,
                "turns": len(day_rows),
                "visitors": len({row[0] for row in day_rows}),
            }
        )

    sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
    for _, content, meta_text, _ in user_rows[:500]:
        try:
            sentiment = json.loads(meta_text or "{}").get("sentiment")
        except json.JSONDecodeError:
            sentiment = None
        sentiment = sentiment or _infer_sentiment(content)
        sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1
    for _, _, sentiment, _ in feedback_rows:
        sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1

    ratings = [row[0] for row in feedback_rows]
    satisfaction_trend = []
    for offset in range(6, -1, -1):
        day = (now.date() - timedelta(days=offset)).isoformat()
        values = [row[0] for row in feedback_rows if row[3][:10] == day]
        satisfaction_trend.append(
            {
                "date": day,
                "score": round(sum(values) / len(values), 2) if values else None,
                "count": len(values),
            }
        )

    latencies = []
    for (meta_text,) in assistant_rows:
        try:
            latency = json.loads(meta_text or "{}").get("latency_ms")
        except json.JSONDecodeError:
            latency = None
        if isinstance(latency, (int, float)):
            latencies.append(float(latency))

    suggestions = []
    if sentiment_counts.get("negative", 0) > sentiment_counts.get("positive", 0):
        suggestions.append("负向反馈偏多，建议复核高频问题回答与现场排队体验。")
    if counts.get("路线", 0) > 0:
        suggestions.append("路线咨询活跃，可在入口增加分众路线二维码和预计时长提示。")
    if counts.get("九龙灌浴", 0) > 0:
        suggestions.append("九龙灌浴关注度较高，建议突出表演时刻和最佳观看位置。")
    if not suggestions:
        suggestions.append("当前服务运行平稳，建议持续扩充高频问题知识库并收集满意度。")

    return {
        "service_turns": len(user_rows),
        "unique_visitors": len({row[0] for row in user_rows}),
        "today_visitors": len(today_sessions),
        "week_visitors": len(week_sessions),
        "avg_satisfaction": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "feedback_count": len(feedback_rows),
        "avg_response_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "hot_topics": sorted(
            [{"name": k, "count": v} for k, v in counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        ),
        "sentiment": sentiment_counts,
        "daily_service": daily,
        "satisfaction_trend": satisfaction_trend,
        "recent_questions": recent_questions[:10],
        "recent_feedback": [
            {
                "rating": row[0],
                "comment": row[1],
                "sentiment": row[2],
                "created_at": row[3],
            }
            for row in feedback_rows[:10]
        ],
        "service_suggestions": suggestions,
        "routes": ROUTES,
    }


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
        return FileResponse(
            index_path,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    return {
        "name": "Lingshan AI Guide API",
        "docs": "/docs",
        "health": "/health",
    }


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
