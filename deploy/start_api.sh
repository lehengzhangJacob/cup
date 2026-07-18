#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source /home/softcup/miniconda3/etc/profile.d/conda.sh
conda activate softcup
export ZHIPU_API_KEY="$(tr -d '\n\r' < "$ROOT/softcup_glmkey")"
export API_HOST="${API_HOST:-0.0.0.0}"
export API_PORT="${API_PORT:-8000}"
export API_SSL_PORT="${API_SSL_PORT:-8443}"

CERT_DIR="$ROOT/deploy/certs"
CERT="$CERT_DIR/cert.pem"
KEY="$CERT_DIR/key.pem"
mkdir -p "$CERT_DIR"
if [[ ! -f "$CERT" || ! -f "$KEY" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" -days 3650 \
    -subj "/CN=lingshan-guide/O=softcup/C=CN" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:139.159.150.134"
  echo "generated self-signed cert -> $CERT"
fi

cd "$ROOT/services/api"
# kill old
pkill -f 'uvicorn app.main:app' 2>/dev/null || true
sleep 1

# 智谱 open.bigmodel.cn 本机可直连；勿继承 shell 里的 SOCKS ALL_PROXY
# （httpx 未装 socks 扩展时会导致 TTS/对话 502）
unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"

# HTTP (文字/上传语音可用)
nohup python -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" \
  > "$ROOT/deploy/api.log" 2>&1 &
echo $! > "$ROOT/deploy/api.pid"

# HTTPS (麦克风需要安全上下文)
nohup python -m uvicorn app.main:app --host "$API_HOST" --port "$API_SSL_PORT" \
  --ssl-keyfile "$KEY" --ssl-certfile "$CERT" \
  > "$ROOT/deploy/api-ssl.log" 2>&1 &
echo $! > "$ROOT/deploy/api-ssl.pid"

sleep 2
echo "HTTP  http://0.0.0.0:${API_PORT}/"
echo "HTTPS https://0.0.0.0:${API_SSL_PORT}/  (浏览器需点「高级-继续访问」)"
curl -sS "http://127.0.0.1:${API_PORT}/health" || true
echo
