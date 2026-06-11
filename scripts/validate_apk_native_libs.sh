#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK="${1:-$ROOT/app/build/outputs/apk/debug/app-debug.apk}"
EXPECT_VULKAN="${EXPECT_VULKAN:-0}"

if [[ ! -f "$APK" ]]; then
  echo "APK not found: $APK" >&2
  exit 1
fi

libs="$(unzip -Z1 "$APK" | grep '^lib/' || true)"
unexpected_abi="$(grep -E '^lib/[^/]+/' <<<"$libs" | cut -d/ -f2 | sort -u | grep -v '^arm64-v8a$' || true)"
if [[ -n "$unexpected_abi" ]]; then
  echo "Unexpected ABI(s) in APK:" >&2
  echo "$unexpected_abi" >&2
  exit 2
fi

required=(
  "lib/arm64-v8a/libllmbenchmark-llama.so"
  "lib/arm64-v8a/libllama.so"
  "lib/arm64-v8a/libggml.so"
)
for lib in "${required[@]}"; do
  if ! grep -qxF "$lib" <<<"$libs"; then
    echo "Missing required native lib: $lib" >&2
    exit 3
  fi
done

if [[ "$EXPECT_VULKAN" == "1" ]]; then
  if ! grep -qxF "lib/arm64-v8a/libggml-vulkan.so" <<<"$libs"; then
    echo "Missing Vulkan backend lib: lib/arm64-v8a/libggml-vulkan.so" >&2
    exit 4
  fi
fi

echo "APK native libs ok: $APK"
if [[ "$EXPECT_VULKAN" == "1" ]]; then
  echo "Vulkan backend lib present."
fi
