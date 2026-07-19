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

CCC_PYTHON_BIN="${CCC_PYTHON:-/home/gmn/.conda/envs/ccc/bin/python}"
TRANSFORMERS="${LOCAL_LLM_TRANSFORMERS:-${CCC_PYTHON_BIN%/*}/transformers}"
HOST="${LOCAL_LLM_HOST:-127.0.0.1}"
PORT="${LOCAL_LLM_PORT:-8021}"
GPU="${LOCAL_LLM_GPU:-2}"
IDLE_SECONDS="${LOCAL_LLM_IDLE_SECONDS:-120}"
MODEL="${RAG_LOCAL_LLM_MODEL:-/home/huggingface/Qwen2-7B-Instruct}"
PID_FILE="$ROOT/deploy/local-llm.pid"
LOG_FILE="$ROOT/deploy/local-llm.log"
WATCHDOG_PID_FILE="$ROOT/deploy/local-llm-watchdog.pid"
WATCHDOG_LOG_FILE="$ROOT/deploy/local-llm-watchdog.log"
LAST_USED_FILE="$ROOT/deploy/local-llm.last-used"

start_watchdog() {
  if [[ -f "$WATCHDOG_PID_FILE" ]]; then
    watchdog_pid="$(tr -dc '0-9' < "$WATCHDOG_PID_FILE")"
    if [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
      return
    fi
  fi
  nohup bash "$ROOT/deploy/watch_local_llm.sh" > "$WATCHDOG_LOG_FILE" 2>&1 &
  echo $! > "$WATCHDOG_PID_FILE"
}

if [[ ! -x "$TRANSFORMERS" ]]; then
  echo "Transformers CLI not found: $TRANSFORMERS" >&2
  exit 1
fi
if [[ ! -f "$MODEL/config.json" ]]; then
  echo "Local model not found: $MODEL" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    if curl -fsS "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
      start_watchdog
      echo "Local LLM service already ready: http://${HOST}:${PORT}"
      exit 0
    fi
    kill "$old_pid"
  fi
fi

rm -f "$LAST_USED_FILE"

unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"

nohup env CUDA_VISIBLE_DEVICES="$GPU" "$TRANSFORMERS" serve \
  --host "$HOST" \
  --port "$PORT" \
  --device cuda:0 \
  --dtype bfloat16 \
  --reasoning off \
  --model-timeout "$IDLE_SECONDS" \
  --log-level info \
  > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

for _ in {1..60}; do
  if curl -fsS "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
    start_watchdog
    echo "Local LLM ready: http://${HOST}:${PORT}"
    echo "Model loads on demand: $MODEL"
    echo "Idle process stop: ${IDLE_SECONDS}s; physical GPU: $GPU"
    exit 0
  fi
  if ! kill -0 "$(tr -dc '0-9' < "$PID_FILE")" 2>/dev/null; then
    echo "Local LLM process exited; inspect $LOG_FILE" >&2
    exit 1
  fi
  sleep 1
done

echo "Local LLM did not become ready; inspect $LOG_FILE" >&2
exit 1
