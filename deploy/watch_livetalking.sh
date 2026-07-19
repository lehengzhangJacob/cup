#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_ENV="${PUBLIC_ENV:-$ROOT/deploy/public.env}"
if [[ -f "$PUBLIC_ENV" ]]; then
  set -a
  source "$PUBLIC_ENV"
  set +a
fi

CPU_STANDBY="${LIVETALKING_CPU_STANDBY:-true}"
IDLE_SECONDS="${LIVETALKING_IDLE_SECONDS:-120}"
INTERVAL_SECONDS="${LIVETALKING_WATCHDOG_INTERVAL_SECONDS:-1}"
RESTART_DELAY_SECONDS="${LIVETALKING_RESTART_DELAY_SECONDS:-0.5}"
PID_FILE="$ROOT/deploy/livetalking/service.pid"
WATCHDOG_PID_FILE="$ROOT/deploy/livetalking/watchdog.pid"
LAST_USED_FILE="$ROOT/deploy/livetalking/last-used"

cleanup() {
  if [[ -f "$WATCHDOG_PID_FILE" ]]; then
    recorded_pid="$(tr -dc '0-9' < "$WATCHDOG_PID_FILE")"
    if [[ "$recorded_pid" == "$$" ]]; then
      rm -f "$WATCHDOG_PID_FILE"
    fi
  fi
}
trap 'cleanup; exit 0' INT TERM
trap cleanup EXIT

while true; do
  service_pid=""
  if [[ -f "$PID_FILE" ]]; then
    service_pid="$(tr -dc '0-9' < "$PID_FILE")"
  fi

  if [[ -n "$service_pid" ]] && kill -0 "$service_pid" 2>/dev/null; then
    if [[ ! "$CPU_STANDBY" =~ ^(1|true|yes)$ ]] && [[ -f "$LAST_USED_FILE" ]]; then
      last_used="$(stat -c %Y "$LAST_USED_FILE")"
      now="$(date +%s)"
      # Zero or a negative value disables idle shutdown and keeps the avatar hot.
      if (( IDLE_SECONDS > 0 && now - last_used >= IDLE_SECONDS )); then
        kill "$service_pid" 2>/dev/null || true
        rm -f "$PID_FILE" "$LAST_USED_FILE"
        echo "LiveTalking stopped after ${IDLE_SECONDS}s idle; GPU memory released"
        exit 0
      fi
    fi
    sleep "$INTERVAL_SECONDS"
    continue
  fi

  rm -f "$PID_FILE" "$LAST_USED_FILE"
  if [[ "$CPU_STANDBY" =~ ^(1|true|yes)$ ]]; then
    echo "$(date -Is) LiveTalking exited; restarting in CPU standby"
    if bash "$ROOT/deploy/start_livetalking.sh"; then
      echo "$(date -Is) LiveTalking CPU standby restart succeeded"
    else
      echo "$(date -Is) LiveTalking CPU standby restart failed"
    fi
    sleep "$RESTART_DELAY_SECONDS"
    continue
  fi

  exit 0
done
