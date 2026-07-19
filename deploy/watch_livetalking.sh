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

IDLE_SECONDS="${LIVETALKING_IDLE_SECONDS:-120}"
PID_FILE="$ROOT/deploy/livetalking/service.pid"
WATCHDOG_PID_FILE="$ROOT/deploy/livetalking/watchdog.pid"
LAST_USED_FILE="$ROOT/deploy/livetalking/last-used"

service_pid="$(tr -dc '0-9' < "$PID_FILE")"
while [[ -n "$service_pid" ]] && kill -0 "$service_pid" 2>/dev/null; do
  if [[ -f "$LAST_USED_FILE" ]]; then
    last_used="$(stat -c %Y "$LAST_USED_FILE")"
    now="$(date +%s)"
    # Zero or a negative value disables idle shutdown and keeps the avatar hot.
    if (( IDLE_SECONDS > 0 && now - last_used >= IDLE_SECONDS )); then
      kill "$service_pid" 2>/dev/null || true
      for _ in {1..50}; do
        kill -0 "$service_pid" 2>/dev/null || break
        sleep 0.1
      done
      if kill -0 "$service_pid" 2>/dev/null; then
        kill -9 "$service_pid" 2>/dev/null || true
      fi
      rm -f "$PID_FILE" "$LAST_USED_FILE" "$WATCHDOG_PID_FILE"
      echo "LiveTalking stopped after ${IDLE_SECONDS}s idle; GPU memory released"
      exit 0
    fi
  fi
  sleep 5
done

rm -f "$PID_FILE" "$LAST_USED_FILE" "$WATCHDOG_PID_FILE"
