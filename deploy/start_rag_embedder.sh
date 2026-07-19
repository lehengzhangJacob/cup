#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_ENV="${PUBLIC_ENV:-$ROOT/deploy/public.env}"
if [[ -f "$PUBLIC_ENV" ]]; then
  set -a
  source "$PUBLIC_ENV"
  set +a
fi

PYTHON="${RAG_PYTHON:-/home/gmn/.conda/envs/softcup/bin/python}"
PID_FILE="$ROOT/deploy/rag-embedder.pid"
LOG_FILE="$ROOT/deploy/rag-embedder.log"
SOCKET="${RAG_EMBED_SOCKET:-$ROOT/deploy/rag-embedder.sock}"
STATUS_FILE="${RAG_EMBED_STATUS_FILE:-$ROOT/deploy/rag-embedder-status.json}"
RESTART="${RAG_EMBED_RESTART:-false}"
HF_OFFLINE="${RAG_HF_OFFLINE:-true}"

if [[ ! -x "$PYTHON" ]]; then
  echo "RAG Python environment not found: $PYTHON" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(tr -dc '0-9' < "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    if [[ "$RESTART" =~ ^(1|true|yes)$ ]]; then
      kill "$old_pid" 2>/dev/null || true
      for _ in {1..100}; do
        kill -0 "$old_pid" 2>/dev/null || break
        sleep 0.1
      done
      if kill -0 "$old_pid" 2>/dev/null; then
        kill -KILL "$old_pid" 2>/dev/null || true
      fi
    elif [[ -S "$SOCKET" ]] && grep -q '"ready": true' "$STATUS_FILE" 2>/dev/null; then
      echo "RAG embedding coordinator already ready: $SOCKET"
      exit 0
    else
      echo "RAG embedding coordinator is running but not ready: PID $old_pid" >&2
      exit 1
    fi
  fi
fi

"$PYTHON" - "$SOCKET" "$STATUS_FILE" <<'PY'
from pathlib import Path
import sys

for value in sys.argv[1:]:
    Path(value).unlink(missing_ok=True)
PY
cd "$ROOT/llm"
export RAG_EMBED_DEVICE=on-demand
export RAG_EMBED_SOCKET="$SOCKET"
export RAG_EMBED_STATUS_FILE="$STATUS_FILE"
export PYTORCH_NVML_BASED_CUDA_CHECK=1
unset CUDA_VISIBLE_DEVICES
if [[ "$HF_OFFLINE" =~ ^(1|true|yes)$ ]]; then
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
fi
unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"

nohup "$PYTHON" -m rag.embed_service > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

for _ in {1..180}; do
  if [[ -S "$SOCKET" ]] && grep -q '"ready": true' "$STATUS_FILE" 2>/dev/null; then
    echo "RAG embedding coordinator ready on CPU: $SOCKET"
    exit 0
  fi
  if ! kill -0 "$(tr -dc '0-9' < "$PID_FILE")" 2>/dev/null; then
    echo "RAG embedding coordinator exited; inspect $LOG_FILE" >&2
    exit 1
  fi
  sleep 1
done

echo "RAG embedding coordinator did not become ready; inspect $LOG_FILE" >&2
exit 1
