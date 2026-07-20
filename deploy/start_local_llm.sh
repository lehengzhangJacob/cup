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

TRANSFORMERS="${LOCAL_LLM_TRANSFORMERS:-/home/gmn/.conda/envs/ccc/bin/transformers}"
PYTHON="${CCC_PYTHON:-/home/gmn/.conda/envs/ccc/bin/python}"
PROFILE="${LOCAL_LLM_PROFILE:-full}"
if [[ "$PROFILE" == "lite" ]]; then
  HOST="${LOCAL_LITE_LLM_HOST:-127.0.0.1}"
  PORT="${LOCAL_LITE_LLM_PORT:-8022}"
  GPU_SETTING="${LOCAL_LITE_LLM_GPU:-auto}"
  GPU_CANDIDATES="${LOCAL_LITE_LLM_GPU_CANDIDATES:-0,1,2,3}"
  GPU_MIN_FREE_MB="${LOCAL_LITE_LLM_GPU_MIN_FREE_MB:-6000}"
  IDLE_SECONDS="${LOCAL_LITE_LLM_IDLE_SECONDS:-120}"
  MODEL="${RAG_LOCAL_LITE_LLM_MODEL:-/home/datasets/EMO_GEN/EMO_GEN_model/Qwen/Qwen3-1.7B}"
  FILE_PREFIX="local-llm-lite"
  SERVICE_LABEL="Lightweight local Qwen3-1.7B"
elif [[ "$PROFILE" == "full" ]]; then
  HOST="${LOCAL_LLM_HOST:-127.0.0.1}"
  PORT="${LOCAL_LLM_PORT:-8021}"
  GPU_SETTING="${LOCAL_LLM_GPU:-auto}"
  GPU_CANDIDATES="${LOCAL_LLM_GPU_CANDIDATES:-0,1,2,3}"
  GPU_MIN_FREE_MB="${LOCAL_LLM_GPU_MIN_FREE_MB:-18000}"
  IDLE_SECONDS="${LOCAL_LLM_IDLE_SECONDS:-120}"
  MODEL="${RAG_LOCAL_LLM_MODEL:-/home/huggingface/Qwen2-7B-Instruct}"
  FILE_PREFIX="local-llm"
  SERVICE_LABEL="Full local Qwen2-7B"
else
  echo "Unsupported LOCAL_LLM_PROFILE: $PROFILE (expected full or lite)" >&2
  exit 1
fi
GPU_SELECTOR="$ROOT/deploy/select_free_gpu.py"
PID_FILE="$ROOT/deploy/${FILE_PREFIX}.pid"
LOG_FILE="$ROOT/deploy/${FILE_PREFIX}.log"
WATCHDOG_PID_FILE="$ROOT/deploy/${FILE_PREFIX}-watchdog.pid"
WATCHDOG_LOG_FILE="$ROOT/deploy/${FILE_PREFIX}-watchdog.log"
LAST_USED_FILE="$ROOT/deploy/${FILE_PREFIX}.last-used"
START_LOCK="$ROOT/deploy/${FILE_PREFIX}-start.lock"

exec 9>"$START_LOCK"
flock -w 90 9

start_watchdog() {
  if [[ -f "$WATCHDOG_PID_FILE" ]]; then
    watchdog_pid="$(tr -dc '0-9' < "$WATCHDOG_PID_FILE")"
    if [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
      return
    fi
  fi
  nohup env LOCAL_LLM_PROFILE="$PROFILE" bash "$ROOT/deploy/watch_local_llm.sh" > "$WATCHDOG_LOG_FILE" 2>&1 &
  echo $! > "$WATCHDOG_PID_FILE"
}

if [[ ! -x "$TRANSFORMERS" ]]; then
  echo "Transformers CLI not found: $TRANSFORMERS" >&2
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Python runtime not found: $PYTHON" >&2
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
      echo "$SERVICE_LABEL service already ready: http://${HOST}:${PORT}"
      exit 0
    fi
    kill "$old_pid"
  fi
fi

rm -f "$LAST_USED_FILE"

if ! selection="$("$PYTHON" "$GPU_SELECTOR" \
  --candidates "$GPU_CANDIDATES" \
  --min-free-mb "$GPU_MIN_FREE_MB" \
  --requested "$GPU_SETTING")"; then
  echo "Unable to select a GPU for $SERVICE_LABEL (minimum ${GPU_MIN_FREE_MB} MiB free)." >&2
  exit 1
fi
IFS=$'\t' read -r GPU GPU_FREE_MB GPU_UTILIZATION <<< "$selection"
if [[ -z "$GPU" || -z "$GPU_FREE_MB" || -z "$GPU_UTILIZATION" ]]; then
  echo "GPU selector returned an invalid result: $selection" >&2
  exit 1
fi
echo "Selected physical GPU $GPU for $SERVICE_LABEL: ${GPU_FREE_MB} MiB free, ${GPU_UTILIZATION}% utilization"
{
  date -Is
  printf 'Selected physical GPU %s: %s MiB free, %s%% utilization; threshold %s MiB; model %s\n' \
    "$GPU" "$GPU_FREE_MB" "$GPU_UTILIZATION" "$GPU_MIN_FREE_MB" "$MODEL"
} > "$LOG_FILE"

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
  >> "$LOG_FILE" 2>&1 9>&- &
echo $! > "$PID_FILE"

for _ in {1..60}; do
  if curl -fsS "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
    start_watchdog
    echo "$SERVICE_LABEL ready: http://${HOST}:${PORT}"
    echo "Model loads on demand: $MODEL"
    echo "Idle process stop: ${IDLE_SECONDS}s; physical GPU: $GPU; selection threshold: ${GPU_MIN_FREE_MB} MiB"
    exit 0
  fi
  if ! kill -0 "$(tr -dc '0-9' < "$PID_FILE")" 2>/dev/null; then
    echo "$SERVICE_LABEL process exited; inspect $LOG_FILE" >&2
    exit 1
  fi
  sleep 1
done

echo "$SERVICE_LABEL did not become ready; inspect $LOG_FILE" >&2
exit 1
