#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${LOCAL_LLM_PROFILE:-full}"
if [[ "$PROFILE" == "lite" ]]; then
  FILE_PREFIX="local-llm-lite"
  SERVICE_LABEL="Lightweight local Qwen3-1.7B"
elif [[ "$PROFILE" == "full" ]]; then
  FILE_PREFIX="local-llm"
  SERVICE_LABEL="Full local Qwen2-7B"
else
  echo "Unsupported LOCAL_LLM_PROFILE: $PROFILE" >&2
  exit 1
fi
PID_FILE="$ROOT/deploy/${FILE_PREFIX}.pid"
WATCHDOG_PID_FILE="$ROOT/deploy/${FILE_PREFIX}-watchdog.pid"
LAST_USED_FILE="$ROOT/deploy/${FILE_PREFIX}.last-used"

if [[ -f "$WATCHDOG_PID_FILE" ]]; then
  watchdog_pid="$(tr -dc '0-9' < "$WATCHDOG_PID_FILE")"
  if [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
    kill "$watchdog_pid" 2>/dev/null || true
  fi
fi

if [[ ! -f "$PID_FILE" ]]; then
  echo "$SERVICE_LABEL is not running"
  exit 0
fi

pid="$(tr -dc '0-9' < "$PID_FILE")"
if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  for _ in {1..50}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
  done
fi
rm -f "$PID_FILE" "$WATCHDOG_PID_FILE" "$LAST_USED_FILE"
echo "$SERVICE_LABEL stopped; model GPU memory released"
