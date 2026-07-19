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

PYTHON="${CCC_PYTHON:-/home/gmn/.conda/envs/ccc/bin/python}"
GPU="${LIVETALKING_GPU:-2}"
CPU_STANDBY="${LIVETALKING_CPU_STANDBY:-true}"
PROXY="${LIVETALKING_PROXY:-http://127.0.0.1:7890}"
IDLE_SECONDS="${LIVETALKING_IDLE_SECONDS:-120}"
READY_INTERVAL_SECONDS="${LIVETALKING_READY_INTERVAL_SECONDS:-0.2}"
PID_FILE="$ROOT/deploy/livetalking/service.pid"
LOG_FILE="$ROOT/deploy/livetalking/service.log"
RESTART="${LIVETALKING_RESTART:-false}"
WATCHDOG_PID_FILE="$ROOT/deploy/livetalking/watchdog.pid"
WATCHDOG_LOG_FILE="$ROOT/deploy/livetalking/watchdog.log"
LAST_USED_FILE="$ROOT/deploy/livetalking/last-used"
WATCHDOG_ENABLED="${LIVETALKING_WATCHDOG_ENABLED:-true}"

mkdir -p "$ROOT/deploy/livetalking"
exec 9>"$ROOT/deploy/livetalking/start.lock"
flock -w 85 9

start_watchdog() {
  if [[ ! "$WATCHDOG_ENABLED" =~ ^(1|true|yes)$ ]]; then
    return
  fi
  if [[ -f "$WATCHDOG_PID_FILE" ]]; then
    watchdog_pid="$(tr -dc '0-9' < "$WATCHDOG_PID_FILE")"
    if [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
      return
    fi
  fi
  nohup bash "$ROOT/deploy/watch_livetalking.sh" > "$WATCHDOG_LOG_FILE" 2>&1 9>&- &
  echo $! > "$WATCHDOG_PID_FILE"
}

stop_watchdog() {
  if [[ -f "$WATCHDOG_PID_FILE" ]]; then
    watchdog_pid="$(tr -dc '0-9' < "$WATCHDOG_PID_FILE")"
    if [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
      kill "$watchdog_pid" 2>/dev/null || true
      for _ in {1..20}; do
        kill -0 "$watchdog_pid" 2>/dev/null || break
        sleep 0.05
      done
    fi
    rm -f "$WATCHDOG_PID_FILE"
  fi
}

if [[ ! "$WATCHDOG_ENABLED" =~ ^(1|true|yes)$ ]]; then
  stop_watchdog
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    if [[ "$RESTART" =~ ^(1|true|yes)$ ]]; then
      echo "Restarting LiveTalking PID $old_pid"
      # Stop the old watcher before replacing its service PID. Otherwise it
      # can observe the intentional shutdown and delete the new PID file.
      stop_watchdog
      kill "$old_pid"
      for _ in {1..50}; do
        kill -0 "$old_pid" 2>/dev/null || break
        sleep 0.1
      done
    else
      touch "$LAST_USED_FILE"
      start_watchdog
      echo "LiveTalking already running: PID $old_pid"
      exit 0
    fi
  fi
fi
if curl -fsS http://127.0.0.1:8010/api/admin/config >/dev/null 2>&1; then
  touch "$LAST_USED_FILE"
  start_watchdog
  echo "LiveTalking already ready: http://127.0.0.1:8010"
  exit 0
fi

cd "$ROOT/LiveTalking"
export LIVETALKING_CPU_STANDBY="$CPU_STANDBY"
if [[ "$CPU_STANDBY" =~ ^(1|true|yes)$ ]]; then
  unset CUDA_VISIBLE_DEVICES
else
  export CUDA_VISIBLE_DEVICES="$GPU"
fi
export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY"
export http_proxy="$PROXY" https_proxy="$PROXY"
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"

# BLAS/OpenMP libraries otherwise create hundreds of workers per WebRTC
# session on this 112-thread host, increasing scheduling jitter.
CPU_THREADS="${LIVETALKING_CPU_THREADS:-8}"
export OMP_NUM_THREADS="$CPU_THREADS"
export MKL_NUM_THREADS="$CPU_THREADS"
export OPENBLAS_NUM_THREADS="$CPU_THREADS"
export NUMEXPR_NUM_THREADS="$CPU_THREADS"

nohup "$PYTHON" app.py > "$LOG_FILE" 2>&1 9>&- &
echo $! > "$PID_FILE"
touch "$LAST_USED_FILE"

for _ in {1..300}; do
  if curl -fsS http://127.0.0.1:8010/api/admin/config >/dev/null; then
    start_watchdog
    if [[ "$CPU_STANDBY" =~ ^(1|true|yes)$ ]]; then
      echo "LiveTalking ready in CPU standby: http://127.0.0.1:8010"
    else
      echo "LiveTalking ready on GPU $GPU: http://127.0.0.1:8010"
    fi
    exit 0
  fi
  sleep "$READY_INTERVAL_SECONDS"
done

echo "LiveTalking did not become ready; inspect $LOG_FILE" >&2
exit 1
