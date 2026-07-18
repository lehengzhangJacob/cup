#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${CCC_PYTHON:-/home/gmn/.conda/envs/ccc/bin/python}"
GPU="${LIVETALKING_GPU:-1}"
PROXY="${LIVETALKING_PROXY:-http://127.0.0.1:7890}"
PID_FILE="$ROOT/deploy/livetalking/service.pid"
LOG_FILE="$ROOT/deploy/livetalking/service.log"

mkdir -p "$ROOT/deploy/livetalking"
if [[ -f "$PID_FILE" ]]; then
  old_pid="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "LiveTalking already running: PID $old_pid"
    exit 0
  fi
fi
if curl -fsS http://127.0.0.1:8010/api/admin/config >/dev/null 2>&1; then
  echo "LiveTalking already ready: http://127.0.0.1:8010"
  exit 0
fi

cd "$ROOT/LiveTalking"
export CUDA_VISIBLE_DEVICES="$GPU"
export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY"
export http_proxy="$PROXY" https_proxy="$PROXY"
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"

nohup "$PYTHON" app.py > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

for _ in {1..60}; do
  if curl -fsS http://127.0.0.1:8010/api/admin/config >/dev/null; then
    echo "LiveTalking ready on GPU $GPU: http://127.0.0.1:8010"
    exit 0
  fi
  sleep 1
done

echo "LiveTalking did not become ready; inspect $LOG_FILE" >&2
exit 1
