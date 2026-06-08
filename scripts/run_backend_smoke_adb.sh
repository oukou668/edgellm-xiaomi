#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"
BACKEND_ID="${BACKEND_ID:-llama_cpp}"
SMOKE_TYPE="${SMOKE_TYPE:-real_model_smoke}"
MODEL_ID="${MODEL_ID:-}"
BENCHMARK_ID="${BENCHMARK_ID:-qa_real_smoke_zh_en}"
REPEAT_COUNT="${REPEAT_COUNT:-3}"
WARMUP_COUNT="${WARMUP_COUNT:-0}"

cleanup_failure() {
  status=$?
  if [[ "$status" != "0" ]]; then
    echo "Smoke failed, collecting failure bundle..." >&2
    ADB="$ADB" PACKAGE="com.xiaomi.llmbenchmark" "$ROOT/scripts/collect_failure_bundle.sh" || true
  fi
  exit "$status"
}

trap cleanup_failure EXIT

case "$BACKEND_ID" in
  mlc)
    MODEL_ID="${MODEL_ID:-Qwen3-1.7B-q4f16_1-MLC}"
    ;;
  llama_cpp)
    MODEL_ID="${MODEL_ID:-minicpm4-0.5b-q4_k_m}"
    ;;
  *)
    echo "Unsupported BACKEND_ID: $BACKEND_ID" >&2
    exit 1
    ;;
esac

BACKEND_ID="$BACKEND_ID" \
SMOKE_TYPE="$SMOKE_TYPE" \
MODEL_ID="$MODEL_ID" \
BENCHMARK_ID="$BENCHMARK_ID" \
REPEAT_COUNT="$REPEAT_COUNT" \
WARMUP_COUNT="$WARMUP_COUNT" \
ADB="$ADB" \
"$ROOT/scripts/run_benchmark_adb.sh"
