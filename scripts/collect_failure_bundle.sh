#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"
PACKAGE="${PACKAGE:-com.xiaomi.llmbenchmark}"
DEST="${DEST:-$ROOT/failure_bundles/$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$DEST"

{
  echo "package=$PACKAGE"
  echo "cwd=$ROOT"
  date
  git -C "$ROOT" status --short --branch || true
  git -C "$ROOT" rev-parse HEAD || true
} > "$DEST/identity.txt"

if command -v "$ADB" >/dev/null 2>&1; then
  "$ADB" devices -l > "$DEST/adb_devices.txt" 2>&1 || true
  "$ADB" shell getprop > "$DEST/getprop.txt" 2>&1 || true
  "$ADB" logcat -d -t 2000 > "$DEST/logcat_tail.txt" 2>&1 || true
  "$ADB" exec-out "run-as $PACKAGE tar -cf - files/reports files/smoke 2>/dev/null" > "$DEST/app_files.tar" 2>/dev/null || true
  "$ADB" shell "ls -la /data/tombstones 2>/dev/null" > "$DEST/tombstones_listing.txt" 2>&1 || true
fi

echo "Failure bundle: $DEST"

