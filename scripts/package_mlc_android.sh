#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/mlc/MLCChat/mlc-package-config.json"
OUT_DIR="$ROOT/mlc/dist"
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$HOME/Library/Android/sdk/cmake/3.31.6/bin:$PATH"
if [[ -z "${JAVA_HOME:-}" && -d /opt/homebrew/opt/openjdk@17 ]]; then
  export JAVA_HOME="/opt/homebrew/opt/openjdk@17"
fi
if [[ -n "${JAVA_HOME:-}" ]]; then
  export PATH="$JAVA_HOME/bin:$PATH"
fi
export PYTHONPATH="$ROOT/scripts/mlc_bypass_pkg${PYTHONPATH:+:$PYTHONPATH}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
export ANDROID_NDK_HOME="${ANDROID_NDK_HOME:-$ANDROID_HOME/ndk/27.3.13750724}"
export ANDROID_NDK="${ANDROID_NDK:-$ANDROID_NDK_HOME}"
NDK_LLVM_PREBUILT="$(find "$ANDROID_NDK_HOME/toolchains/llvm/prebuilt" -maxdepth 1 -mindepth 1 -type d | head -1)"
export TVM_NDK_CC="${TVM_NDK_CC:-$NDK_LLVM_PREBUILT/bin/aarch64-linux-android28-clang}"
MLC_PYTHON="${MLC_PYTHON:-$ROOT/artifacts/venv/mlc-python/bin/python}"

MLC_SOURCE_DIR="${MLC_LLM_SOURCE_DIR:-/Users/chenhaotian/code/iPhone/mlc-llm}"
if [[ ! -d "$MLC_SOURCE_DIR" ]]; then
  echo "MLC source directory not found: $MLC_SOURCE_DIR"
  echo "Clone https://github.com/mlc-ai/mlc-llm there, or set MLC_LLM_SOURCE_DIR."
  exit 1
fi
if [[ ! -x "$MLC_PYTHON" ]]; then
  echo "MLC Python interpreter not found: $MLC_PYTHON"
  echo "Run ./scripts/bootstrap_mlc_python_env.sh or set MLC_PYTHON."
  exit 1
fi
mkdir -p "$MLC_SOURCE_DIR/3rdparty/tvm/build/lib"
ln -sf "$MLC_SOURCE_DIR/build/lib/libtvm_runtime.dylib" \
  "$MLC_SOURCE_DIR/3rdparty/tvm/build/lib/libtvm_runtime.dylib"
if [[ -f "$MLC_SOURCE_DIR/build/lib/libtvm_compiler.dylib" ]]; then
  ln -sf "$MLC_SOURCE_DIR/build/lib/libtvm_compiler.dylib" \
    "$MLC_SOURCE_DIR/3rdparty/tvm/build/lib/libtvm_compiler.dylib"
else
  echo "MLC TVM compiler library not found: $MLC_SOURCE_DIR/build/lib/libtvm_compiler.dylib"
  echo "Run: cmake --build $MLC_SOURCE_DIR/build --target tvm_compiler -j 8"
  exit 1
fi
export PYTHONPATH="$MLC_SOURCE_DIR/3rdparty/tvm/python:$PYTHONPATH"
export MLC_LLM_PYTHON_PACKAGE_DIR="$MLC_SOURCE_DIR/python/mlc_llm"
export TVM_USE_RUNTIME_LIB=0

mkdir -p "$OUT_DIR"
rm -rf "$ROOT/build/CMakeCache.txt" "$ROOT/build/CMakeFiles"
"$MLC_PYTHON" "$ROOT/scripts/mlc_package_bypass.py" \
  --package-config "$CONFIG" \
  --mlc-llm-source-dir "$MLC_SOURCE_DIR" \
  --output "$OUT_DIR"

echo "MLC Android package written to: $OUT_DIR"
"$ROOT/scripts/sync_mlc_package.sh" "$OUT_DIR"
python3 "$ROOT/scripts/validate_mlc_android_package.py"
