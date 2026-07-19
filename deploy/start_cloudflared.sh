#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_ENV="${PUBLIC_ENV:-$ROOT/deploy/public.env}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-/home/gmn/.local/bin/cloudflared}"
PID_FILE="$ROOT/deploy/cloudflared.pid"
LOG_FILE="$ROOT/deploy/cloudflared.log"

if [[ ! -f "$PUBLIC_ENV" ]]; then
  echo "Missing $PUBLIC_ENV; copy deploy/public.env.example and fill it first." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$PUBLIC_ENV"

if [[ ! -x "$CLOUDFLARED_BIN" ]]; then
  echo "cloudflared not found: $CLOUDFLARED_BIN" >&2
  echo "Run: bash deploy/install_cloudflared.sh" >&2
  exit 1
fi
if [[ -z "${CLOUDFLARE_TUNNEL_TOKEN:-}" || "$CLOUDFLARE_TUNNEL_TOKEN" == "CHANGE_ME" ]]; then
  echo "Set CLOUDFLARE_TUNNEL_TOKEN in $PUBLIC_ENV" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid"
    for _ in {1..30}; do
      kill -0 "$old_pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
fi

export TUNNEL_TOKEN="$CLOUDFLARE_TUNNEL_TOKEN"
unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"
nohup "$CLOUDFLARED_BIN" tunnel --no-autoupdate run > "$LOG_FILE" 2>&1 &
tunnel_pid=$!
unset TUNNEL_TOKEN
echo "$tunnel_pid" > "$PID_FILE"

sleep 1
if ! kill -0 "$tunnel_pid" 2>/dev/null; then
  echo "cloudflared exited; inspect $LOG_FILE" >&2
  exit 1
fi
echo "cloudflared started (pid $tunnel_pid); log: $LOG_FILE"
