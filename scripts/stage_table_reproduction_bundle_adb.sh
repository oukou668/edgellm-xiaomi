#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"
PACKAGE="${PACKAGE:-com.xiaomi.llmbenchmark}"
BUNDLE_DIR="${BUNDLE_DIR:-}"

if [[ -z "$BUNDLE_DIR" ]]; then
  echo "Set BUNDLE_DIR to artifacts/table_reproduction/run_bundles/<bundle_id>" >&2
  exit 1
fi
if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "Bundle directory not found: $BUNDLE_DIR" >&2
  exit 1
fi
if [[ ! -f "$BUNDLE_DIR/benchmark.jsonl" || ! -f "$BUNDLE_DIR/bundle_manifest.json" ]]; then
  echo "Bundle must contain benchmark.jsonl and bundle_manifest.json" >&2
  exit 2
fi

BUNDLE_ID="$(python3 - "$BUNDLE_DIR/bundle_manifest.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["bundle_id"])
PY
)"
DEVICE_DIR="files/run_bundles/$BUNDLE_ID"
TMP_DIR="files/run_bundles/.partial-$(date +%Y%m%d_%H%M%S)_$BUNDLE_ID"

echo "Staging bundle $BUNDLE_ID -> /data/data/$PACKAGE/$DEVICE_DIR"
"$ADB" shell "run-as '$PACKAGE' sh -c 'rm -rf \"$TMP_DIR\" && mkdir -p \"$(dirname "$TMP_DIR")\" && mkdir -p \"$TMP_DIR\"'"
COPYFILE_DISABLE=1 tar -cf - -C "$BUNDLE_DIR" . | "$ADB" exec-in run-as "$PACKAGE" sh -c "tar -xf - -C '$TMP_DIR'"
"$ADB" shell "run-as '$PACKAGE' sh -c 'rm -rf \"$DEVICE_DIR\" && mv \"$TMP_DIR\" \"$DEVICE_DIR\"'"
echo "Bundle staged: $DEVICE_DIR"
echo "Run with:"
echo "  RUNNER=service BUNDLE_ID=$BUNDLE_ID BACKEND_ID=llama_cpp MODEL_ID=<formal-model-id> SMOKE_TYPE=real_model_smoke ./scripts/run_benchmark_adb.sh"
