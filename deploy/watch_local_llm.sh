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

PROFILE="${LOCAL_LLM_PROFILE:-full}"
if [[ "$PROFILE" == "lite" ]]; then
  IDLE_SECONDS="${LOCAL_LITE_LLM_IDLE_SECONDS:-120}"
  FILE_PREFIX="local-llm-lite"
  SERVICE_LABEL="Lightweight local Qwen3-1.7B"
elif [[ "$PROFILE" == "full" ]]; then
  IDLE_SECONDS="${LOCAL_LLM_IDLE_SECONDS:-120}"
  FILE_PREFIX="local-llm"
  SERVICE_LABEL="Full local Qwen2-7B"
else
  echo "Unsupported LOCAL_LLM_PROFILE: $PROFILE" >&2
  exit 1
fi
PID_FILE="$ROOT/deploy/${FILE_PREFIX}.pid"
WATCHDOG_PID_FILE="$ROOT/deploy/${FILE_PREFIX}-watchdog.pid"
LAST_USED_FILE="$ROOT/deploy/${FILE_PREFIX}.last-used"

if [[ ! -f "$PID_FILE" ]]; then
  rm -f "$WATCHDOG_PID_FILE"
  exit 0
fi
service_pid="$(tr -dc '0-9' < "$PID_FILE")"
while [[ -n "$service_pid" ]] && kill -0 "$service_pid" 2>/dev/null; do
  if [[ -f "$LAST_USED_FILE" ]]; then
    last_used="$(stat -c %Y "$LAST_USED_FILE")"
    now="$(date +%s)"
    if (( now - last_used >= IDLE_SECONDS )); then
      kill "$service_pid" 2>/dev/null || true
      for _ in {1..50}; do
        kill -0 "$service_pid" 2>/dev/null || break
        sleep 0.1
      done
      rm -f "$PID_FILE" "$LAST_USED_FILE" "$WATCHDOG_PID_FILE"
      echo "$SERVICE_LABEL stopped after ${IDLE_SECONDS}s idle; GPU memory released"
      exit 0
    fi
  fi
  sleep 5
done

rm -f "$PID_FILE" "$LAST_USED_FILE" "$WATCHDOG_PID_FILE"
