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

HOST="${RAG_HOST:-127.0.0.1}"
PORT="${RAG_PORT:-8020}"
INTERVAL="${RAG_WATCHDOG_INTERVAL_SECONDS:-5}"
FAILURE_THRESHOLD="${RAG_WATCHDOG_FAILURE_THRESHOLD:-3}"
failures=0

while true; do
  if curl -fsS --max-time 2 "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
    failures=0
    sleep "$INTERVAL"
    continue
  fi

  failures=$((failures + 1))
  if (( failures < FAILURE_THRESHOLD )); then
    echo "$(date -Is) RAG health check failed (${failures}/${FAILURE_THRESHOLD}); retrying"
    sleep "$INTERVAL"
    continue
  fi

  echo "$(date -Is) RAG unhealthy; restarting"
  if RAG_RESTART=true RAG_EMBED_RESTART=false RAG_WATCHDOG_CHILD=true \
    bash "$ROOT/deploy/start_rag.sh"; then
    echo "$(date -Is) RAG restart succeeded"
    failures=0
  else
    echo "$(date -Is) RAG restart failed; retrying in ${INTERVAL}s"
  fi
  sleep "$INTERVAL"
done
