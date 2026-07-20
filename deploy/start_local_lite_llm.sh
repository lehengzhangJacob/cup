#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export LOCAL_LLM_PROFILE=lite
exec bash "$ROOT/deploy/start_local_llm.sh"
