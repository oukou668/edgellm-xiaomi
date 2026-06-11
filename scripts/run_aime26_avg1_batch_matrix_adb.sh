#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_DIR="${BUNDLE_DIR:-}"
BATCH_SIZES="${BATCH_SIZES:-1,2,4}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-28800}"
WAIT="${WAIT:-1}"
PULL="${PULL:-1}"
SUMMARY="${SUMMARY:-1}"

cd "$ROOT"

if [[ -z "$BUNDLE_DIR" ]]; then
  python3 "$ROOT/scripts/fetch_table_reproduction_datasets.py" --datasets aime26 --allow-missing
  prepare_output="$(
    python3 "$ROOT/scripts/prepare_table_reproduction_bundle.py" \
      --suite avg1_diagnostic \
      --model-id minicpm5-1b-thinking-q4 \
      --datasets aime26
  )"
  echo "$prepare_output"
  BUNDLE_DIR="$(awk '/^bundle ready:/ {print $3}' <<<"$prepare_output")"
fi

if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "Bundle directory not found: $BUNDLE_DIR" >&2
  exit 1
fi

BUNDLE_ID="$(python3 - "$BUNDLE_DIR/bundle_manifest.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["bundle_id"])
PY
)"

BUNDLE_DIR="$BUNDLE_DIR" "$ROOT/scripts/stage_table_reproduction_bundle_adb.sh"

IFS=',' read -r -a batch_values <<<"$BATCH_SIZES"
declare -a report_dirs=()
declare -a backend_specs=(
  "llama_cpp:minicpm5-1b-thinking-q4"
  "mlc:minicpm5-1b-thinking-mlc"
)

for spec in "${backend_specs[@]}"; do
  backend="${spec%%:*}"
  model="${spec#*:}"
  for batch_index in "${!batch_values[@]}"; do
    batch_size="${batch_values[$batch_index]}"
    batch_size="$(echo "$batch_size" | tr -d '[:space:]')"
    [[ -n "$batch_size" ]] || continue
    unload_after_run=0
    if [[ "$batch_index" == "$((${#batch_values[@]} - 1))" ]]; then
      unload_after_run=1
    fi
    echo "== AIME26 Avg@1 backend=$backend model=$model batch_size=$batch_size =="
    RUNNER=service \
      BACKEND_ID="$backend" \
      MODEL_ID="$model" \
      BUNDLE_ID="$BUNDLE_ID" \
      SMOKE_TYPE=real_model_smoke \
      REPEAT_COUNT=1 \
      WARMUP_COUNT=0 \
      BATCH_SIZE="$batch_size" \
      UNLOAD_AFTER_RUN="$unload_after_run" \
      WAIT="$WAIT" \
      PULL="$PULL" \
      TIMEOUT_SECONDS="$TIMEOUT_SECONDS" \
      "$ROOT/scripts/run_benchmark_adb.sh"
    if [[ "$WAIT" == "1" && "$PULL" == "1" ]]; then
      latest="$(
        find "$ROOT/reports/extracted/files/reports" -maxdepth 1 -type d -name "*_${BUNDLE_ID}" -print 2>/dev/null \
          | sort \
          | tail -1
      )"
      if [[ -n "$latest" && -f "$latest/report.json" ]]; then
        report_dirs+=("$latest")
      fi
    fi
  done
done

if [[ "$SUMMARY" == "1" && "${#report_dirs[@]}" -gt 0 ]]; then
  python3 "$ROOT/scripts/summarize_aime26_avg1_batch_matrix.py" "${report_dirs[@]}"
fi
