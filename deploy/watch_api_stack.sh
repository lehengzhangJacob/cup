#!/usr/bin/env bash

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RETRY_SECONDS="${API_STACK_RETRY_SECONDS:-3}"
CHECK_SECONDS="${API_STACK_CHECK_SECONDS:-5}"

trap 'exit 0' INT TERM

stack_ready() {
  curl -fsS --max-time 2 "http://127.0.0.1:8001/health" >/dev/null 2>&1 \
    && curl -kfsS --max-time 2 "https://127.0.0.1:8443/health" >/dev/null 2>&1 \
    && curl -kfsS --max-time 2 "https://127.0.0.1:8444/health" >/dev/null 2>&1 \
    && curl -fsS --max-time 2 "http://127.0.0.1:8011/health" >/dev/null 2>&1
}

while true; do
  if ! bash "$ROOT/deploy/start_api.sh"; then
    printf '%s API stack start failed; retrying in %ss\n' \
      "$(date --iso-8601=seconds)" "$RETRY_SECONDS"
    sleep "$RETRY_SECONDS"
    continue
  fi

  while stack_ready; do
    sleep "$CHECK_SECONDS"
  done

  printf '%s API stack unhealthy; restarting\n' "$(date --iso-8601=seconds)"
  sleep "$RETRY_SECONDS"
done
