#!/usr/bin/env bash
set -u

KEY="/root/.ssh/cup_titan_huawei_ed25519"
LOG_PREFIX="[titan-huawei-tunnel]"

while true; do
  echo "$LOG_PREFIX connecting"
  ssh -NT \
    -i "$KEY" \
    -o BatchMode=yes \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=yes \
    -R 127.0.0.1:20101:127.0.0.1:8001 \
    -R 127.0.0.1:20111:127.0.0.1:8011 \
    softcup@139.159.150.134
  status=$?
  echo "$LOG_PREFIX disconnected (status=$status); retrying in 3 seconds"
  sleep 3
done
