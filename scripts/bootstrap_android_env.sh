#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ROOT="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
APP_NDK_VERSION="${APP_NDK_VERSION:-28.2.13676358}"
MLC_NDK_VERSION="${MLC_NDK_VERSION:-27.3.13750724}"
CMAKE_VERSION="${CMAKE_VERSION:-3.31.6}"

log() {
  printf '[bootstrap] %s\n' "$*"
}

require_brew() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required." >&2
    exit 1
  fi
}

require_brew

log "Installing host tools when missing."
brew list --versions openjdk@17 >/dev/null 2>&1 || brew install openjdk@17
brew list --versions android-commandlinetools >/dev/null 2>&1 || brew install android-commandlinetools
brew list --versions android-platform-tools >/dev/null 2>&1 || brew install android-platform-tools

OPENJDK_PREFIX="$(brew --prefix openjdk@17)"
export JAVA_HOME="$OPENJDK_PREFIX/libexec/openjdk.jdk/Contents/Home"
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="$JAVA_HOME/bin:$SDK_ROOT/cmdline-tools/latest/bin:$SDK_ROOT/platform-tools:$PATH"

mkdir -p "$SDK_ROOT"
mkdir -p "$HOME/Library/Java/JavaVirtualMachines"
ln -sfn "$OPENJDK_PREFIX/libexec/openjdk.jdk" "$HOME/Library/Java/JavaVirtualMachines/openjdk-17.jdk"

if ! command -v sdkmanager >/dev/null 2>&1; then
  echo "sdkmanager was not found after installing android-commandlinetools." >&2
  exit 1
fi

log "Accepting SDK licenses."
yes | sdkmanager --sdk_root="$SDK_ROOT" --licenses >/dev/null || true

log "Installing Android SDK components."
sdkmanager --sdk_root="$SDK_ROOT" \
  "platform-tools" \
  "platforms;android-36" \
  "build-tools;36.0.0" \
  "ndk;$APP_NDK_VERSION" \
  "ndk;$MLC_NDK_VERSION" \
  "cmake;$CMAKE_VERSION"

cat > "$ROOT/local.properties" <<EOF
sdk.dir=$SDK_ROOT
EOF

log "Wrote local.properties with sdk.dir only."
log "JAVA_HOME=$JAVA_HOME"
log "ANDROID_HOME=$ANDROID_HOME"
