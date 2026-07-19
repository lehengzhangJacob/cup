#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/deploy/livetalking/service.pid"
WATCHDOG_PID_FILE="$ROOT/deploy/livetalking/watchdog.pid"
LAST_USED_FILE="$ROOT/deploy/livetalking/last-used"

if [[ -f "$WATCHDOG_PID_FILE" ]]; then
  watchdog_pid="$(tr -dc '0-9' < "$WATCHDOG_PID_FILE")"
  if [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
    kill "$watchdog_pid" 2>/dev/null || true
  fi
fi

if [[ -f "$PID_FILE" ]]; then
  pid="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    for _ in {1..50}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
fi

rm -f "$PID_FILE" "$WATCHDOG_PID_FILE" "$LAST_USED_FILE"
echo "LiveTalking stopped; GPU memory released"
