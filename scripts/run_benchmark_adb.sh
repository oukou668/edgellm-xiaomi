#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"
PACKAGE="com.xiaomi.llmbenchmark"
ACTIVITY="$PACKAGE/.MainActivity"
MODEL_ID="${MODEL_ID:-Qwen3-1.7B-q4f16_1-MLC}"
BENCHMARK_ID="${BENCHMARK_ID:-qa_smoke_zh_en}"
BUNDLE_ID="${BUNDLE_ID:-}"
BACKEND_ID="${BACKEND_ID:-mlc}"
SMOKE_TYPE="${SMOKE_TYPE:-dummy_backend_regression}"
REPEAT_COUNT="${REPEAT_COUNT:-1}"
WARMUP_COUNT="${WARMUP_COUNT:-0}"
WAIT="${WAIT:-1}"
PULL="${PULL:-1}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-900}"
POLL_SECONDS="${POLL_SECONDS:-5}"
STAY_AWAKE="${STAY_AWAKE:-1}"
RUNNER="${RUNNER:-activity}"
REPORTS_DIR="$ROOT/reports"
EFFECTIVE_BENCHMARK_ID="${BUNDLE_ID:-$BENCHMARK_ID}"
restore_stay_awake=0

cleanup() {
  if [[ "$restore_stay_awake" == "1" ]]; then
    "$ADB" shell svc power stayon false >/dev/null 2>&1 || true
  fi
}

cd "$ROOT"
before_reports="$("$ADB" shell "run-as $PACKAGE ls files/reports 2>/dev/null" | tr -d '\r' || true)"
if [[ "$STAY_AWAKE" == "1" ]]; then
  "$ADB" shell svc power stayon true || true
  if [[ "$WAIT" == "1" ]]; then
    restore_stay_awake=1
    trap cleanup EXIT
  fi
fi
"$ADB" shell am force-stop "$PACKAGE" || true
if [[ "$RUNNER" == "service" ]]; then
  service_args=(
    am start-foreground-service
    -n "$PACKAGE/.BenchmarkService"
    --es backend_id "$BACKEND_ID"
    --es model_id "$MODEL_ID"
    --es benchmark_id "$BENCHMARK_ID"
    --es smoke_type "$SMOKE_TYPE"
    --ei repeat_count "$REPEAT_COUNT"
    --ei warmup_count "$WARMUP_COUNT"
  )
  if [[ -n "$BUNDLE_ID" ]]; then
    service_args+=(--es bundle_id "$BUNDLE_ID")
  fi
  "$ADB" shell "${service_args[@]}"
else
  activity_args=(
    am start -W
    -n "$ACTIVITY"
    --ez autorun true
    --es backend_id "$BACKEND_ID"
    --es model_id "$MODEL_ID"
    --es benchmark_id "$BENCHMARK_ID"
    --es smoke_type "$SMOKE_TYPE"
    --ei repeat_count "$REPEAT_COUNT"
    --ei warmup_count "$WARMUP_COUNT"
  )
  if [[ -n "$BUNDLE_ID" ]]; then
    activity_args+=(--es bundle_id "$BUNDLE_ID")
  fi
  "$ADB" shell "${activity_args[@]}"
fi

echo "Started benchmark: runner=$RUNNER backend=$BACKEND_ID model=$MODEL_ID benchmark=$EFFECTIVE_BENCHMARK_ID smoke=$SMOKE_TYPE repeat=$REPEAT_COUNT warmup=$WARMUP_COUNT"
if [[ "$WAIT" != "1" ]]; then
  echo "After it finishes, pull reports with: ADB=$ADB ./scripts/pull_reports.sh"
  exit 0
fi

echo "Waiting for report, timeout=${TIMEOUT_SECONDS}s ..."
started_at="$(date +%s)"
new_report=""
while true; do
  reports="$("$ADB" shell "run-as $PACKAGE ls files/reports 2>/dev/null" | tr -d '\r' || true)"
  while IFS= read -r report; do
    [[ -z "$report" ]] && continue
    [[ "$report" == *"_$EFFECTIVE_BENCHMARK_ID" ]] || continue
    if ! grep -qxF "$report" <<<"$before_reports"; then
      new_report="$report"
    fi
  done <<<"$reports"
  if [[ -n "$new_report" ]]; then
    break
  fi
  now="$(date +%s)"
  if (( now - started_at >= TIMEOUT_SECONDS )); then
    echo "Timed out waiting for report."
    exit 2
  fi
  sleep "$POLL_SECONDS"
done

echo "Report created on device: files/reports/$new_report"
if [[ "$PULL" == "1" ]]; then
  ADB="$ADB" "$ROOT/scripts/pull_reports.sh"
  local_report="$REPORTS_DIR/extracted/files/reports/$new_report/report.md"
  if [[ -f "$local_report" ]]; then
    echo
    echo "Latest report summary:"
    sed -n '1,24p' "$local_report"
    echo
    echo "Local report: $local_report"
  fi
fi
