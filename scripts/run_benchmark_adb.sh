#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"
PACKAGE="com.xiaomi.llmbenchmark"
ACTIVITY="$PACKAGE/.MainActivity"
MODEL_ID="${MODEL_ID:-Qwen3-1.7B-q4f16_1-MLC}"
BENCHMARK_ID="${BENCHMARK_ID:-qa_smoke_zh_en}"

cd "$ROOT"
"$ADB" shell am force-stop "$PACKAGE" || true
"$ADB" shell am start -W \
  -n "$ACTIVITY" \
  --ez autorun true \
  --es model_id "$MODEL_ID" \
  --es benchmark_id "$BENCHMARK_ID"

echo "Started benchmark: model=$MODEL_ID benchmark=$BENCHMARK_ID"
echo "After it finishes, pull reports with: ADB=$ADB ./scripts/pull_reports.sh"
