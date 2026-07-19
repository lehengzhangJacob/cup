#!/usr/bin/env bash

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RETRY_SECONDS="${API_STACK_RETRY_SECONDS:-3}"
CHECK_SECONDS="${API_STACK_CHECK_SECONDS:-5}"
FAILURE_THRESHOLD="${API_STACK_FAILURE_THRESHOLD:-3}"

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

  failures=0
  while true; do
    if stack_ready; then
      failures=0
      sleep "$CHECK_SECONDS"
      continue
    fi

    failures=$((failures + 1))
    printf '%s API stack health check failed (%s/%s)\n' \
      "$(date --iso-8601=seconds)" "$failures" "$FAILURE_THRESHOLD"
    if (( failures >= FAILURE_THRESHOLD )); then
      break
    fi
    sleep "$CHECK_SECONDS"
  done

  printf '%s API stack unhealthy; restarting\n' "$(date --iso-8601=seconds)"
  sleep "$RETRY_SECONDS"
done
