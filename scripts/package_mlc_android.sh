#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/mlc/MLCChat/mlc-package-config.json"
OUT_DIR="$ROOT/mlc/package"
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$HOME/Library/Android/sdk/cmake/3.22.1/bin:$PATH"
export PYTHONPATH="$ROOT/scripts/mlc_bypass_pkg${PYTHONPATH:+:$PYTHONPATH}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
export ANDROID_NDK="${ANDROID_NDK:-$ANDROID_HOME/ndk/27.3.13750724}"
export TVM_NDK_CC="${TVM_NDK_CC:-$ANDROID_NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android28-clang}"

MLC_SOURCE_DIR="${MLC_LLM_SOURCE_DIR:-$ROOT/vendor/mlc-llm}"
if [[ ! -d "$MLC_SOURCE_DIR" ]]; then
  echo "MLC source directory not found: $MLC_SOURCE_DIR"
  echo "Clone https://github.com/mlc-ai/mlc-llm there, or set MLC_LLM_SOURCE_DIR."
  exit 1
fi

mkdir -p "$OUT_DIR"
python3 "$ROOT/scripts/mlc_package_bypass.py" \
  --package-config "$CONFIG" \
  --mlc-llm-source-dir "$MLC_SOURCE_DIR" \
  --output "$OUT_DIR"

echo "MLC Android package written to: $OUT_DIR"
"$ROOT/scripts/sync_mlc_package.sh" "$OUT_DIR"
