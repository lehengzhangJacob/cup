#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WATCHER="$ROOT/deploy/titan_huawei/watch_reverse_tunnel.sh"
PID_FILE="$ROOT/deploy/titan-huawei-tunnel.pid"
LOG_FILE="$ROOT/deploy/titan-huawei-tunnel.log"

if [[ -f "$PID_FILE" ]]; then
  pid="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "Titan Huawei reverse tunnel already active: pid=$pid"
    exit 0
  fi
fi

if [[ ! -f /root/.ssh/cup_titan_huawei_ed25519 ]]; then
  echo "Titan Huawei SSH key is missing." >&2
  exit 1
fi

nohup bash "$WATCHER" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 1
pid="$(tr -dc '0-9' < "$PID_FILE")"
if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
  echo "Titan Huawei reverse tunnel failed to start; see $LOG_FILE" >&2
  exit 1
fi
echo "Titan Huawei reverse tunnel started: pid=$pid"
