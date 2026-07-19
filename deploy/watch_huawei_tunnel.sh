#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IDENTITY_FILE="${HUAWEI_SSH_IDENTITY:-${HOME}/.ssh/cup_huawei_ed25519}"
LOCK_FILE="${SCRIPT_DIR}/huawei-tunnel.lock"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  exit 0
fi

while true; do
  printf '%s connecting Huawei reverse tunnel\n' "$(date --iso-8601=seconds)"
  /usr/bin/ssh \
    -NT \
    -i "${IDENTITY_FILE}" \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveCountMax=3 \
    -o ServerAliveInterval=15 \
    -o StrictHostKeyChecking=yes \
    -R 127.0.0.1:8001:127.0.0.1:8001 \
    -R 127.0.0.1:8011:127.0.0.1:8011 \
    -R 127.0.0.1:18001:127.0.0.1:8001 \
    -R 127.0.0.1:18011:127.0.0.1:8011 \
    softcup@139.159.150.134
  exit_code=$?
  printf '%s tunnel exited with code %s; retrying\n' \
    "$(date --iso-8601=seconds)" \
    "${exit_code}"
  sleep 3
done
