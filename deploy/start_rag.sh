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

PYTHON="${RAG_PYTHON:-/home/gmn/.conda/envs/softcup/bin/python}"
HOST="${RAG_HOST:-127.0.0.1}"
PORT="${RAG_PORT:-8020}"
GPU="${RAG_GPU:-3}"
HF_OFFLINE="${RAG_HF_OFFLINE:-true}"
EMBED_DEVICE="${RAG_EMBED_DEVICE:-on-demand}"
PID_FILE="$ROOT/deploy/rag.pid"
LOG_FILE="$ROOT/deploy/rag.log"
RESTART="${RAG_RESTART:-false}"
WATCHDOG_CHILD="${RAG_WATCHDOG_CHILD:-false}"
WATCHDOG_PID_FILE="$ROOT/deploy/rag-watchdog.pid"
WATCHDOG_LOG_FILE="$ROOT/deploy/rag-watchdog.log"

start_watchdog() {
  if [[ "$WATCHDOG_CHILD" =~ ^(1|true|yes)$ ]]; then
    return
  fi
  if [[ -f "$WATCHDOG_PID_FILE" ]]; then
    watchdog_pid="$(tr -dc '0-9' < "$WATCHDOG_PID_FILE")"
    if [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
      return
    fi
  fi
  existing_watchdog_pid="$(pgrep -f "bash $ROOT/deploy/watch_rag.sh" | head -n 1 || true)"
  if [[ -n "$existing_watchdog_pid" ]]; then
    echo "$existing_watchdog_pid" > "$WATCHDOG_PID_FILE"
    return
  fi
  nohup bash "$ROOT/deploy/watch_rag.sh" > "$WATCHDOG_LOG_FILE" 2>&1 &
  echo $! > "$WATCHDOG_PID_FILE"
}

if [[ "$RESTART" =~ ^(1|true|yes)$ ]] && [[ "$WATCHDOG_CHILD" != "true" ]]; then
  if [[ -f "$WATCHDOG_PID_FILE" ]]; then
    watchdog_pid="$(tr -dc '0-9' < "$WATCHDOG_PID_FILE")"
    if [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
      kill "$watchdog_pid" 2>/dev/null || true
    fi
    rm -f "$WATCHDOG_PID_FILE"
  fi
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "RAG Python environment not found: $PYTHON" >&2
  exit 1
fi

export RAG_EMBED_DEVICE="$EMBED_DEVICE"
if [[ "$EMBED_DEVICE" == "on-demand" ]]; then
  export RAG_EMBED_SOCKET="${RAG_EMBED_SOCKET:-$ROOT/deploy/rag-embedder.sock}"
  export RAG_EMBED_STATUS_FILE="${RAG_EMBED_STATUS_FILE:-$ROOT/deploy/rag-embedder-status.json}"
  RAG_EMBED_RESTART="$RESTART" bash "$ROOT/deploy/start_rag_embedder.sh"
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    if [[ "$RESTART" =~ ^(1|true|yes)$ ]]; then
      kill "$old_pid"
      for _ in {1..50}; do
        kill -0 "$old_pid" 2>/dev/null || break
        sleep 0.1
      done
    elif curl -fsS "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
      start_watchdog
      echo "RAG service already ready: http://${HOST}:${PORT}"
      exit 0
    else
      echo "RAG process is running but not healthy: PID $old_pid" >&2
      exit 1
    fi
  fi
fi

cd "$ROOT/llm"
if [[ "$EMBED_DEVICE" == cuda* ]]; then
  export CUDA_VISIBLE_DEVICES="$GPU"
  DEVICE_LABEL="physical GPU $GPU ($EMBED_DEVICE)"
else
  unset CUDA_VISIBLE_DEVICES
  if [[ "$EMBED_DEVICE" == "on-demand" ]]; then
    DEVICE_LABEL="CPU standby + on-demand GPU"
  else
    DEVICE_LABEL="$EMBED_DEVICE"
  fi
fi
if [[ "$HF_OFFLINE" =~ ^(1|true|yes)$ ]]; then
  # Production startup must use the already-downloaded BGE-M3 snapshot instead
  # of making Hugging Face metadata requests on every restart.
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
fi
unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"

nohup "$PYTHON" -m uvicorn api:app --host "$HOST" --port "$PORT" \
  > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

# Loading BGE-M3 can take tens of seconds on a cold start.
for _ in {1..180}; do
  if curl -fsS "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
    start_watchdog
    echo "RAG ready on $DEVICE_LABEL: http://${HOST}:${PORT}"
    exit 0
  fi
  if ! kill -0 "$(tr -dc '0-9' < "$PID_FILE")" 2>/dev/null; then
    echo "RAG process exited; inspect $LOG_FILE" >&2
    exit 1
  fi
  sleep 1
done

echo "RAG did not become ready; inspect $LOG_FILE" >&2
exit 1
