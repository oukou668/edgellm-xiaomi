#!/usr/bin/env bash
set -euo pipefail

MLC_SOURCE_DIR="${MLC_LLM_SOURCE_DIR:-/Users/chenhaotian/code/iPhone/mlc-llm}"
BUILD_DIR="${MLC_TVM_BUILD_DIR:-$MLC_SOURCE_DIR/build}"
LLVM_CONFIG="${LLVM_CONFIG:-}"

if [[ -z "$LLVM_CONFIG" ]]; then
  if [[ -x /opt/homebrew/opt/llvm/bin/llvm-config ]]; then
    LLVM_CONFIG=/opt/homebrew/opt/llvm/bin/llvm-config
  elif command -v llvm-config >/dev/null 2>&1; then
    LLVM_CONFIG="$(command -v llvm-config)"
  else
    echo "llvm-config not found. Install Homebrew llvm or set LLVM_CONFIG." >&2
    exit 1
  fi
fi

if [[ ! -f "$MLC_SOURCE_DIR/CMakeLists.txt" ]]; then
  echo "MLC source checkout not found: $MLC_SOURCE_DIR" >&2
  exit 1
fi

echo "[mlc-tvm] source=$MLC_SOURCE_DIR"
echo "[mlc-tvm] build=$BUILD_DIR"
echo "[mlc-tvm] llvm=$("$LLVM_CONFIG" --version) ($LLVM_CONFIG)"

cmake -S "$MLC_SOURCE_DIR" -B "$BUILD_DIR" \
  -DUSE_LLVM="$LLVM_CONFIG" \
  -DMLC_LLM_BUILD_PYTHON_MODULE=OFF
cmake --build "$BUILD_DIR" --target tvm_compiler -j "${JOBS:-8}"

test -f "$BUILD_DIR/lib/libtvm_runtime.dylib"
test -f "$BUILD_DIR/lib/libtvm_compiler.dylib"

echo "[mlc-tvm] compiler ready: $BUILD_DIR/lib/libtvm_compiler.dylib"
