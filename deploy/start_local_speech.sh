#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_ENV="${PUBLIC_ENV:-$ROOT/deploy/public.env}"
if [[ -f "$PUBLIC_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$PUBLIC_ENV"
  set +a
fi

PYTHON="${LOCAL_SPEECH_PYTHON:-/home/gmn/.conda/envs/ccc/bin/python}"
HOST="${LOCAL_SPEECH_HOST:-127.0.0.1}"
PORT="${LOCAL_SPEECH_PORT:-8030}"
PID_FILE="$ROOT/deploy/local-speech.pid"
LOG_FILE="$ROOT/deploy/local-speech.log"

if [[ ! -x "$PYTHON" ]]; then
  echo "Local speech environment not found: $PYTHON" >&2
  exit 1
fi

if curl -fsS --max-time 2 "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
  echo "Local speech service already ready: http://${HOST}:${PORT}"
  exit 0
fi

# Production uses a dedicated user unit so the speech process is not tied to
# the lifetime of a terminal or an API restart command.
if systemctl --user cat cup-local-speech.service >/dev/null 2>&1; then
  systemctl --user start cup-local-speech.service
  for _ in {1..120}; do
    if curl -fsS --max-time 2 "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
      echo "Local speech ready through systemd: http://${HOST}:${PORT}"
      exit 0
    fi
    sleep 1
  done
  echo "Local speech systemd unit did not become ready." >&2
  systemctl --user --no-pager --full status cup-local-speech.service >&2 || true
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    if curl -fsS --max-time 2 "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
      echo "Local speech service already ready: http://${HOST}:${PORT}"
      exit 0
    fi
    kill "$old_pid" 2>/dev/null || true
  fi
fi

cd "$ROOT"
unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

nohup "$PYTHON" -m uvicorn services.local_speech.app:app \
  --host "$HOST" --port "$PORT" --timeout-keep-alive 300 \
  > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

# Cold startup loads FunASR into CPU memory and primes Chinese TTS G2P.
for _ in {1..120}; do
  if curl -fsS --max-time 2 "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
    echo "Local speech ready: http://${HOST}:${PORT}"
    exit 0
  fi
  if ! kill -0 "$(tr -dc '0-9' < "$PID_FILE")" 2>/dev/null; then
    echo "Local speech process exited; inspect $LOG_FILE" >&2
    exit 1
  fi
  sleep 1
done

echo "Local speech did not become ready; inspect $LOG_FILE" >&2
exit 1
