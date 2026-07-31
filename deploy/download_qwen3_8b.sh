#!/usr/bin/env bash

set -Eeuo pipefail

TARGET="/home/huggingface/Qwen3-8B"
BASE_URL="https://modelscope.cn/models/Qwen/Qwen3-8B/resolve/master"

mkdir -p "$TARGET"

download_one() {
  local file="$1"
  local final="$TARGET/$file"
  local partial="$final.part"

  if [[ -s "$final" ]]; then
    printf 'SKIP %s (%s bytes)\n' "$file" "$(stat -c %s "$final")"
    return 0
  fi

  printf 'START %s (resume=%s bytes)\n' \
    "$file" "$([[ -f "$partial" ]] && stat -c %s "$partial" || printf 0)"
  curl \
    --location \
    --fail \
    --silent \
    --show-error \
    --retry 30 \
    --retry-delay 5 \
    --retry-all-errors \
    --connect-timeout 20 \
    --continue-at - \
    --output "$partial" \
    "$BASE_URL/$file"
  mv -- "$partial" "$final"
  printf 'DONE %s (%s bytes)\n' "$file" "$(stat -c %s "$final")"
}

weights=(
  model-00001-of-00005.safetensors
  model-00002-of-00005.safetensors
  model-00003-of-00005.safetensors
  model-00004-of-00005.safetensors
  model-00005-of-00005.safetensors
)

pids=()
for file in "${weights[@]}"; do
  download_one "$file" &
  pids+=("$!")
done

failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=1
done
if (( failed != 0 )); then
  printf 'WEIGHT_DOWNLOAD_FAILED\n' >&2
  exit 1
fi

metadata=(
  model.safetensors.index.json
  tokenizer.json
  tokenizer_config.json
  vocab.json
)
for file in "${metadata[@]}"; do
  download_one "$file"
done

/home/gmn/.conda/envs/softcup/bin/python - "$TARGET" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
index = json.loads((target / "model.safetensors.index.json").read_text())
shards = sorted(set(index["weight_map"].values()))
missing = [name for name in shards if not (target / name).is_file()]
if missing:
    raise SystemExit(f"missing model shards: {missing}")
for name in ("config.json", "tokenizer.json", "tokenizer_config.json"):
    if not (target / name).is_file():
        raise SystemExit(f"missing required file: {name}")
print(
    "DOWNLOAD_COMPLETE",
    f"shards={len(shards)}",
    f"declared_bytes={index.get('metadata', {}).get('total_size', 'unknown')}",
)
PY

du -sh "$TARGET"
