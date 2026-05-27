#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"

cd "$ROOT"
if [[ ! -x ./gradlew ]]; then
  echo "Gradle wrapper is not present. Open this project in Android Studio or install Gradle, then run:"
  echo "  gradle wrapper"
  exit 1
fi

./gradlew :app:assembleDebug
"$ADB" install -r app/build/outputs/apk/debug/app-debug.apk
