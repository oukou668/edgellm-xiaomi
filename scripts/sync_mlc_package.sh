#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="${1:-$ROOT/mlc/dist}"
APP_DIR="$ROOT/app"

if [[ ! -d "$PACKAGE_DIR" ]]; then
  echo "MLC package directory not found: $PACKAGE_DIR"
  echo "Run ./scripts/package_mlc_android.sh first, or pass the package output directory as the first argument."
  exit 1
fi

mkdir -p "$APP_DIR/libs" "$APP_DIR/src/main/jniLibs/arm64-v8a" "$APP_DIR/src/main/assets/mlc"

find "$PACKAGE_DIR" -maxdepth 8 -name '*.aar' -print -exec cp {} "$APP_DIR/libs/" \;
find "$PACKAGE_DIR" -maxdepth 8 -name '*.jar' -print -exec cp {} "$APP_DIR/libs/" \;
find "$PACKAGE_DIR" -maxdepth 10 -path '*/arm64-v8a/*.so' -print -exec cp {} "$APP_DIR/src/main/jniLibs/arm64-v8a/" \;

if [[ -d "$PACKAGE_DIR/bundle" ]] && find "$PACKAGE_DIR/bundle" -type f | grep -q .; then
  rsync -a "$PACKAGE_DIR/bundle/" "$APP_DIR/src/main/assets/mlc/"
elif [[ -d "$PACKAGE_DIR/dist" ]]; then
  rsync -a "$PACKAGE_DIR/dist/" "$APP_DIR/src/main/assets/mlc/"
fi
if [[ -d "$PACKAGE_DIR/lib/mlc4j/src/main/assets" ]]; then
  rsync -a "$PACKAGE_DIR/lib/mlc4j/src/main/assets/" "$APP_DIR/src/main/assets/mlc/"
fi

echo "Synced MLC package artifacts into app/libs, app/src/main/jniLibs, and app/src/main/assets/mlc."
