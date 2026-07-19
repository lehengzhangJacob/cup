#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_ENV="${PUBLIC_ENV:-$ROOT/deploy/public.env}"
DIRECT_ENV="${DIRECT_ENV:-$ROOT/deploy/direct.env}"
if [[ -f "$PUBLIC_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$PUBLIC_ENV"
  set +a
fi
if [[ -f "$DIRECT_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$DIRECT_ENV"
  set +a
fi
LOCAL_TURN_ENABLED="${LOCAL_TURN_ENABLED:-true}"
unset CLOUDFLARE_TUNNEL_TOKEN TUNNEL_TOKEN
PYTHON="${CCC_PYTHON:-/home/gmn/.conda/envs/ccc/bin/python}"
API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8001}"
API_SSL_PORT="${API_SSL_PORT:-8443}"
API_SSL_BACKEND_PORT="${API_SSL_BACKEND_PORT:-9443}"
ADMIN_SSL_PORT="${ADMIN_SSL_PORT:-8444}"
ADMIN_HTTP_PORT="${ADMIN_HTTP_PORT:-8011}"
UVICORN_KEEP_ALIVE="${UVICORN_KEEP_ALIVE:-3600}"

# Validate public security settings before stopping a healthy deployment.
admin_password="${ADMIN_PASSWORD:-}"
admin_session_secret="${ADMIN_SESSION_SECRET:-}"
if [[ -n "${PUBLIC_ADMIN_URL:-}" && ${#admin_password} -lt 12 ]]; then
  echo "PUBLIC_ADMIN_URL requires ADMIN_PASSWORD with at least 12 characters." >&2
  exit 1
fi
if [[ -n "${PUBLIC_ADMIN_URL:-}" && -n "$admin_session_secret" && ${#admin_session_secret} -lt 32 ]]; then
  echo "ADMIN_SESSION_SECRET must be empty (auto-generated) or at least 32 characters." >&2
  exit 1
fi
turn_key_ready=false
turn_token_ready=false
[[ -n "${CLOUDFLARE_TURN_KEY_ID:-}" && "${CLOUDFLARE_TURN_KEY_ID:-}" != "CHANGE_ME" ]] && turn_key_ready=true
[[ -n "${CLOUDFLARE_TURN_API_TOKEN:-}" && "${CLOUDFLARE_TURN_API_TOKEN:-}" != "CHANGE_ME" ]] && turn_token_ready=true
if [[ "$turn_key_ready" != "$turn_token_ready" ]]; then
  echo "CLOUDFLARE_TURN_KEY_ID and CLOUDFLARE_TURN_API_TOKEN must be set together." >&2
  exit 1
fi

# One loopback RAG process owns BGE-M3/FAISS and all conversation sessions.
# The four public/admin API listeners share it over HTTP. API listener recovery
# must not bounce the independent RAG coordinator unless explicitly requested.
RAG_RESTART="${RAG_RESTART:-false}" bash "$ROOT/deploy/start_rag.sh"

# The local OpenAI-compatible server starts without loading model weights.
# Qwen2-7B is loaded only after the local route is selected, then unloaded idle.
if [[ "${LOCAL_LLM_AUTOSTART:-true}" =~ ^(1|true|yes)$ ]]; then
  bash "$ROOT/deploy/start_local_llm.sh"
fi

if [[ "${LIVETALKING_CPU_STANDBY:-false}" =~ ^(1|true|yes)$ ]]; then
  bash "$ROOT/deploy/start_livetalking.sh"
fi

CERT_DIR="$ROOT/deploy/certs"
CERT="$CERT_DIR/cert.pem"
KEY="$CERT_DIR/key.pem"
TURN_ROOT="$ROOT/deploy/coturn/root"
TURN_BIN="$TURN_ROOT/usr/bin/turnserver"
TURN_CONFIG="$ROOT/deploy/coturn/turnserver.conf"
TURN_LIB="$TURN_ROOT/usr/lib/x86_64-linux-gnu"
MUX_SCRIPT="$ROOT/deploy/tls_turn_mux.py"

mkdir -p "$CERT_DIR"
if [[ ! -f "$CERT" || ! -f "$KEY" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" -days 3650 \
    -subj "/CN=lingshan-guide/O=softcup/C=CN" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
fi

stop_pid_file() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(tr -dc '0-9' < "$pid_file")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      for _ in {1..20}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
      done
    fi
  fi
}

stop_pid_file "$ROOT/deploy/api.pid"
stop_pid_file "$ROOT/deploy/api-ssl.pid"
stop_pid_file "$ROOT/deploy/admin-ssl.pid"
stop_pid_file "$ROOT/deploy/admin-http.pid"
stop_pid_file "$ROOT/deploy/api-mux.pid"
stop_pid_file "$ROOT/deploy/coturn/turnserver.pid"

cd "$ROOT/services/api"
unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"
export ADMIN_PORT="$ADMIN_SSL_PORT"

# Keep the supplied XLSX as queryable source data, not only as a generated
# dashboard cache. The importer is idempotent and skips unchanged files.
"$PYTHON" -m scripts.import_tourism_dataset

nohup "$PYTHON" -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" \
  --timeout-keep-alive "$UVICORN_KEEP_ALIVE" \
  > "$ROOT/deploy/api.log" 2>&1 &
echo $! > "$ROOT/deploy/api.pid"

nohup "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_SSL_BACKEND_PORT" \
  --timeout-keep-alive "$UVICORN_KEEP_ALIVE" \
  --ssl-keyfile "$KEY" --ssl-certfile "$CERT" \
  > "$ROOT/deploy/api-ssl.log" 2>&1 &
echo $! > "$ROOT/deploy/api-ssl.pid"

nohup "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "$ADMIN_SSL_PORT" \
  --timeout-keep-alive "$UVICORN_KEEP_ALIVE" \
  --ssl-keyfile "$KEY" --ssl-certfile "$CERT" \
  > "$ROOT/deploy/admin-ssl.log" 2>&1 &
echo $! > "$ROOT/deploy/admin-ssl.pid"

# Loopback-only HTTP origin for Cloudflare Tunnel; public traffic remains HTTPS.
nohup env ADMIN_PORT="$ADMIN_HTTP_PORT" "$PYTHON" -m uvicorn app.main:app \
  --host 127.0.0.1 --port "$ADMIN_HTTP_PORT" \
  --timeout-keep-alive "$UVICORN_KEEP_ALIVE" \
  > "$ROOT/deploy/admin-http.log" 2>&1 &
echo $! > "$ROOT/deploy/admin-http.pid"

if [[ "$LOCAL_TURN_ENABLED" =~ ^(1|true|yes)$ ]]; then
  if [[ ! -x "$TURN_BIN" ]]; then
    echo "coturn binary missing: $TURN_BIN" >&2
    exit 1
  fi
  nohup env LD_LIBRARY_PATH="$TURN_LIB" "$TURN_BIN" -c "$TURN_CONFIG" \
    > "$ROOT/deploy/coturn/coturn.log" 2>&1 &
  echo $! > "$ROOT/deploy/coturn/turnserver.pid"
else
  echo "Local coturn disabled; WebRTC will use the configured external TURN service."
fi

for _ in {1..20}; do
  if curl -kfsS "https://127.0.0.1:${API_SSL_BACKEND_PORT}/health" >/dev/null 2>&1 \
    && curl -kfsS "https://127.0.0.1:${ADMIN_SSL_PORT}/health" >/dev/null 2>&1 \
    && curl -fsS "http://127.0.0.1:${ADMIN_HTTP_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

nohup env MUX_PORT="$API_SSL_PORT" HTTPS_BACKEND_PORT="$API_SSL_BACKEND_PORT" \
  "$PYTHON" "$MUX_SCRIPT" > "$ROOT/deploy/mux.log" 2>&1 &
echo $! > "$ROOT/deploy/api-mux.pid"

for _ in {1..20}; do
  if curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1 \
    && curl -kfsS "https://127.0.0.1:${API_SSL_PORT}/health" >/dev/null 2>&1 \
    && curl -kfsS "https://127.0.0.1:${ADMIN_SSL_PORT}/health" >/dev/null 2>&1 \
    && curl -fsS "http://127.0.0.1:${ADMIN_HTTP_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
curl -fsS "http://127.0.0.1:${API_PORT}/health"
echo
echo "HTTP  http://127.0.0.1:${API_PORT}/"
echo "HTTPS + TURN/TCP https://127.0.0.1:${API_SSL_PORT}/"
echo "ADMIN HTTPS https://127.0.0.1:${ADMIN_SSL_PORT}/admin"
echo "ADMIN TUNNEL ORIGIN http://127.0.0.1:${ADMIN_HTTP_PORT}/admin"
