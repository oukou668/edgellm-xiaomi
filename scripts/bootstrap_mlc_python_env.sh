#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MLC_SOURCE_DIR="${MLC_LLM_SOURCE_DIR:-/Users/chenhaotian/code/iPhone/mlc-llm}"
VENV_DIR="${MLC_PYTHON_VENV:-$ROOT/artifacts/venv/mlc-python}"

if [[ ! -d "$MLC_SOURCE_DIR/python/mlc_llm" ]]; then
  echo "MLC source checkout not found or incomplete: $MLC_SOURCE_DIR" >&2
  exit 1
fi
if [[ ! -f "$MLC_SOURCE_DIR/build/lib/libtvm_runtime.dylib" ]]; then
  echo "Missing MLC build runtime library: $MLC_SOURCE_DIR/build/lib/libtvm_runtime.dylib" >&2
  echo "Build the MLC source checkout before packaging Android artifacts." >&2
  exit 1
fi
if [[ ! -f "$MLC_SOURCE_DIR/build/lib/libtvm_compiler.dylib" ]]; then
  echo "Missing MLC build compiler library: $MLC_SOURCE_DIR/build/lib/libtvm_compiler.dylib" >&2
  echo "Run: cmake --build $MLC_SOURCE_DIR/build --target tvm_compiler -j 8" >&2
  exit 1
fi

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.11)"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.12)"
else
  PYTHON_BIN="$(command -v python3)"
fi

echo "[mlc-python] source=$MLC_SOURCE_DIR"
echo "[mlc-python] venv=$VENV_DIR"
echo "[mlc-python] python=$PYTHON_BIN"

"$PYTHON_BIN" -m venv "$VENV_DIR"
MLC_PYTHON="$VENV_DIR/bin/python"
"$MLC_PYTHON" -m pip install --upgrade pip "setuptools<82" wheel
"$MLC_PYTHON" -m pip install -r "$MLC_SOURCE_DIR/python/requirements.txt"
# The current checked-out TVM Python sources are not compatible with apache-tvm-ffi 0.1.12:
# importing tvm fails while registering ir.DictAttrs. Pin the known-good FFI wheel for this
# source checkout so packaging is reproducible from a clean venv.
"$MLC_PYTHON" -m pip install --force-reinstall "apache-tvm-ffi==0.1.11"
"$MLC_PYTHON" -m pip install cloudpickle psutil scipy tornado pytest
(
  cd "$MLC_SOURCE_DIR/python"
  "$MLC_PYTHON" -m pip install -e .
)

mkdir -p "$MLC_SOURCE_DIR/3rdparty/tvm/build/lib"
ln -sf "$MLC_SOURCE_DIR/build/lib/libtvm_runtime.dylib" \
  "$MLC_SOURCE_DIR/3rdparty/tvm/build/lib/libtvm_runtime.dylib"
ln -sf "$MLC_SOURCE_DIR/build/lib/libtvm_compiler.dylib" \
  "$MLC_SOURCE_DIR/3rdparty/tvm/build/lib/libtvm_compiler.dylib"
export PYTHONPATH="$MLC_SOURCE_DIR/3rdparty/tvm/python${PYTHONPATH:+:$PYTHONPATH}"
export TVM_USE_RUNTIME_LIB=0

"$MLC_PYTHON" - <<'PY'
import importlib.util
for name in ["mlc_llm", "tvm", "requests"]:
    spec = importlib.util.find_spec(name)
    print(f"{name}: {spec.origin if spec else 'missing'}")
    if spec is None:
        raise SystemExit(1)
PY

echo "[mlc-python] export MLC_PYTHON=$MLC_PYTHON"
