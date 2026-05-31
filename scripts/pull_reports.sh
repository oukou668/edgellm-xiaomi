#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"
DEST="$ROOT/reports"
PACKAGE="com.xiaomi.llmbenchmark"
EXTRACT="${EXTRACT:-1}"

mkdir -p "$DEST"

echo "Reports are written inside the app sandbox. Using run-as when debug build allows it."
"$ADB" shell "run-as $PACKAGE ls -la files/reports" || true
"$ADB" exec-out "run-as $PACKAGE tar -cf - files/reports" > "$DEST/llm_benchmark_reports.tar" || true

if [[ "$EXTRACT" == "1" ]]; then
  rm -rf "$DEST/extracted"
  mkdir -p "$DEST/extracted"
  tar -xf "$DEST/llm_benchmark_reports.tar" -C "$DEST/extracted" || true
fi

echo "Pulled reports into: $DEST"
