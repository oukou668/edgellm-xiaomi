#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_ID="${MODEL_ID:-}"
BUNDLE_DIR="${BUNDLE_DIR:-}"
BACKEND_ID="${BACKEND_ID:-llama_cpp}"
SMOKE_TYPE="${SMOKE_TYPE:-real_model_smoke}"
REPEAT_COUNT="${REPEAT_COUNT:-1}"
WARMUP_COUNT="${WARMUP_COUNT:-0}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-7200}"

if [[ -z "$MODEL_ID" ]]; then
  echo "Set MODEL_ID to one formal reproduction model id." >&2
  exit 1
fi
if [[ -z "$BUNDLE_DIR" ]]; then
  echo "Set BUNDLE_DIR to artifacts/table_reproduction/run_bundles/<bundle_id>." >&2
  exit 1
fi

BUNDLE_ID="$(python3 - "$BUNDLE_DIR/bundle_manifest.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["bundle_id"])
PY
)"

BUNDLE_DIR="$BUNDLE_DIR" "$ROOT/scripts/stage_table_reproduction_bundle_adb.sh"
RUNNER=service \
BACKEND_ID="$BACKEND_ID" \
MODEL_ID="$MODEL_ID" \
BUNDLE_ID="$BUNDLE_ID" \
SMOKE_TYPE="$SMOKE_TYPE" \
REPEAT_COUNT="$REPEAT_COUNT" \
WARMUP_COUNT="$WARMUP_COUNT" \
TIMEOUT_SECONDS="$TIMEOUT_SECONDS" \
"$ROOT/scripts/run_benchmark_adb.sh"
