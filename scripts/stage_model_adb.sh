#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"
PACKAGE="${PACKAGE:-com.xiaomi.llmbenchmark}"
BACKEND_ID="${BACKEND_ID:-llama_cpp}"
MODEL_ID="${MODEL_ID:-minicpm4-0.5b-q4_k_m}"
if [[ "$BACKEND_ID" == "llama_cpp" ]]; then
  DEFAULT_HOST_MODEL_ROOT="$ROOT/artifacts/models/gguf"
else
  DEFAULT_HOST_MODEL_ROOT="$ROOT/artifacts/models/$BACKEND_ID"
fi
HOST_MODEL_DIR="${HOST_MODEL_DIR:-$DEFAULT_HOST_MODEL_ROOT/$MODEL_ID}"
DEVICE_MODEL_DIR="${DEVICE_MODEL_DIR:-files/models/$BACKEND_ID/$MODEL_ID}"

if [[ ! -d "$HOST_MODEL_DIR" ]]; then
  echo "Host model directory not found: $HOST_MODEL_DIR" >&2
  exit 1
fi

if ! command -v "$ADB" >/dev/null 2>&1; then
  echo "adb not found: $ADB" >&2
  exit 1
fi

tmp_device_dir="$(dirname "$DEVICE_MODEL_DIR")/.partial-$(date +%Y%m%d_%H%M%S)_$MODEL_ID"
echo "Staging $HOST_MODEL_DIR -> /data/data/$PACKAGE/$DEVICE_MODEL_DIR"
echo "Temporary device dir: $tmp_device_dir"

host_hash_file="$(mktemp)"
find "$HOST_MODEL_DIR" -maxdepth 2 -type f -print0 | sort -z | while IFS= read -r -d '' file; do
  rel="${file#$HOST_MODEL_DIR/}"
  shasum -a 256 "$file" | awk -v rel="$rel" '{print $1 " " rel}'
done > "$host_hash_file"
echo "Host sha256 manifest:"
cat "$host_hash_file"

"$ADB" shell "run-as '$PACKAGE' sh -c 'rm -rf \"$tmp_device_dir\" && mkdir -p \"$(dirname "$tmp_device_dir")\" && mkdir -p \"$tmp_device_dir\"'"
COPYFILE_DISABLE=1 tar -cf - -C "$HOST_MODEL_DIR" . | "$ADB" exec-in run-as "$PACKAGE" sh -c "tar -xf - -C '$tmp_device_dir'"
"$ADB" shell "run-as '$PACKAGE' sh -c 'rm -rf \"$DEVICE_MODEL_DIR\" && mv \"$tmp_device_dir\" \"$DEVICE_MODEL_DIR\"'"
if [[ -f "$HOST_MODEL_DIR/manifest.json" ]]; then
  "$ADB" exec-in run-as "$PACKAGE" sh -c "cat > '$DEVICE_MODEL_DIR/manifest.json'" < "$HOST_MODEL_DIR/manifest.json"
fi
if "$ADB" shell "run-as '$PACKAGE' sh -c 'command -v sha256sum >/dev/null 2>&1'" >/dev/null 2>&1; then
  "$ADB" shell "run-as '$PACKAGE' sh -c 'cd \"$DEVICE_MODEL_DIR\" && find . -maxdepth 2 -type f -print | sort | while read f; do sha256sum \"\$f\" | awk '\''{print \$1 \" \" \$2}'\'' | sed '\''s# \\./# #'\'' ; done'" | tr -d '\r' > "$host_hash_file.device" || true
  echo "Device sha256 manifest:"
  cat "$host_hash_file.device" || true
  if ! diff -u "$host_hash_file" "$host_hash_file.device"; then
    echo "Device sha256 does not match host sha256." >&2
    exit 2
  fi
fi
rm -f "$host_hash_file" "$host_hash_file.device"
echo "Model staged: $DEVICE_MODEL_DIR"
