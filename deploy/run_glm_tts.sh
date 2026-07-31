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

PYTHON="${GLM_TTS_PYTHON:-/home/gmn/.conda/envs/glmtts/bin/python}"
HOST="${GLM_TTS_HOST:-127.0.0.1}"
PORT="${GLM_TTS_PORT:-8031}"
GPU_SETTING="${GLM_TTS_GPU:-auto}"
GPU_CANDIDATES="${GLM_TTS_GPU_CANDIDATES:-0,1,2,3}"
GPU_MIN_FREE_MB="${GLM_TTS_GPU_MIN_FREE_MB:-18000}"
SELECTOR="$ROOT/deploy/select_free_gpu.py"

if [[ ! -x "$PYTHON" ]]; then
  echo "GLM-TTS Python environment is missing: $PYTHON" >&2
  exit 1
fi

if ! selection="$("$PYTHON" "$SELECTOR" \
  --candidates "$GPU_CANDIDATES" \
  --min-free-mb "$GPU_MIN_FREE_MB" \
  --requested "$GPU_SETTING")"; then
  echo "GLM-TTS could not find a GPU with at least ${GPU_MIN_FREE_MB} MiB free." >&2
  exit 1
fi

IFS=$'\t' read -r GPU GPU_FREE_MB GPU_UTILIZATION <<< "$selection"
echo "GLM-TTS selected physical GPU $GPU: ${GPU_FREE_MB} MiB free, ${GPU_UTILIZATION}% utilization"

unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"
export no_proxy="$NO_PROXY"
export CUDA_VISIBLE_DEVICES="$GPU"
export GLM_TTS_GPU_PHYSICAL="$GPU"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT"
exec "$PYTHON" -m uvicorn services.glm_tts.app:app \
  --host "$HOST" --port "$PORT" --timeout-keep-alive 300
