#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${CCC_PYTHON:-/home/gmn/.conda/envs/ccc/bin/python}"
API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8001}"
API_SSL_PORT="${API_SSL_PORT:-8443}"
CERT_DIR="$ROOT/deploy/certs"
CERT="$CERT_DIR/cert.pem"
KEY="$CERT_DIR/key.pem"

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

cd "$ROOT/services/api"
unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"

nohup "$PYTHON" -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" \
  > "$ROOT/deploy/api.log" 2>&1 &
echo $! > "$ROOT/deploy/api.pid"

nohup "$PYTHON" -m uvicorn app.main:app --host "$API_HOST" --port "$API_SSL_PORT" \
  --ssl-keyfile "$KEY" --ssl-certfile "$CERT" \
  > "$ROOT/deploy/api-ssl.log" 2>&1 &
echo $! > "$ROOT/deploy/api-ssl.pid"

sleep 2
curl -fsS "http://127.0.0.1:${API_PORT}/health"
echo
echo "HTTP  http://127.0.0.1:${API_PORT}/"
echo "HTTPS https://127.0.0.1:${API_SSL_PORT}/"
