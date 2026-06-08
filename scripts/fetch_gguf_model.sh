#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_ID="${MODEL_ID:-minicpm4-0.5b-q4_k_m}"
DEST_ROOT="${DEST_ROOT:-$ROOT/artifacts/models/gguf}"

eval "$(
python3 - "$ROOT/app/src/main/assets/models.json" "$MODEL_ID" <<'PY'
import json, shlex, sys
path, model_id = sys.argv[1], sys.argv[2]
models = json.load(open(path))["models"]
matches = [m for m in models if m.get("model_id") == model_id]
if not matches:
    raise SystemExit(f"Unsupported MODEL_ID: {model_id}")
model = matches[0]
if model.get("backend_id") != "llama_cpp":
    raise SystemExit(f"MODEL_ID is not a llama_cpp GGUF model: {model_id}")
required = ["hf_repo", "hf_revision", "artifact_filename", "artifact_sha256", "artifact_size_bytes"]
missing = [key for key in required if not model.get(key)]
if missing:
    raise SystemExit(f"MODEL_ID {model_id} is missing fields: {', '.join(missing)}")
mapping = {
    "HF_REPO": model["hf_repo"],
    "HF_REVISION": model["hf_revision"],
    "FILE_NAME": model["artifact_filename"],
    "SHA256": model["artifact_sha256"],
    "SIZE_BYTES": str(model["artifact_size_bytes"]),
}
for key, value in mapping.items():
    print(f"{key}={shlex.quote(value)}")
PY
)"

DEST_DIR="$DEST_ROOT/$MODEL_ID"
PARTIAL="$DEST_DIR/$FILE_NAME.partial"
FINAL="$DEST_DIR/$FILE_NAME"
URL="https://huggingface.co/$HF_REPO/resolve/$HF_REVISION/$FILE_NAME"

mkdir -p "$DEST_DIR"

if [[ ! -f "$FINAL" ]]; then
  echo "Downloading $URL"
  curl -L --fail --continue-at - --output "$PARTIAL" "$URL"
  mv "$PARTIAL" "$FINAL"
fi

actual_size="$(wc -c < "$FINAL" | tr -d ' ')"
if [[ "$actual_size" != "$SIZE_BYTES" ]]; then
  echo "Size mismatch: expected $SIZE_BYTES actual $actual_size" >&2
  exit 2
fi

actual_sha="$(shasum -a 256 "$FINAL" | awk '{print $1}')"
if [[ "$actual_sha" != "$SHA256" ]]; then
  echo "SHA mismatch: expected $SHA256 actual $actual_sha" >&2
  exit 3
fi

python3 - "$DEST_DIR/manifest.json" <<PY
import json, pathlib, sys, time
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
  "backend_id": "llama_cpp",
  "model_id": "$MODEL_ID",
  "hf_repo": "$HF_REPO",
  "hf_revision": "$HF_REVISION",
  "artifact_filename": "$FILE_NAME",
  "artifact_sha256": "$SHA256",
  "artifact_size_bytes": int("$SIZE_BYTES"),
  "verified_at_ms": int(time.time() * 1000),
}, indent=2, sort_keys=True) + "\\n")
PY

echo "GGUF ready: $DEST_DIR"
