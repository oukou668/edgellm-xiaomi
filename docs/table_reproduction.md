# Table Reproduction V1

This project implements the Android/Xiaomi 17 side of the MiniCPM5-1B table
reproduction as a strict, evidence-first workflow.

## Scope

- Target name: `Xiaomi 17 Q4 mobile reproduction`
- Runtime: `llama_cpp`
- Quantization: Q4, preferring `Q4_K_M`
- Models: exactly the four `table_reproduction_v1` models in `models.json`
- Datasets: exactly the 13 non-Coding/non-Agentic datasets in
  `configs/table_reproduction_v1.json`
- Generation params: `temperature=0.9`, `top_p=0.95`, `thinking_enabled=true`
- M2 math datasets use `@Avg16`.

The original table `Average Score` is not reused. Reports recompute the mean
over the 13 selected datasets and show deltas against the per-dataset table
baselines.

## Workflow

Validate static config:

```bash
python3 scripts/validate_table_reproduction_manifest.py
```

Fetch a formal GGUF model from the pinned `models.json` artifact entry:

```bash
MODEL_ID=minicpm5-1b-thinking-q4 ./scripts/fetch_gguf_model.sh
BACKEND_ID=llama_cpp MODEL_ID=minicpm5-1b-thinking-q4 ./scripts/stage_model_adb.sh
```

Prepare official dataset artifacts outside the APK:

```text
artifacts/table_reproduction/datasets/<dataset_id>/manifest.json
artifacts/table_reproduction/datasets/<dataset_id>/samples.jsonl
```

`samples.jsonl` must come from the official source recorded in
`configs/table_reproduction_v1.json`. The bundle builder fails if artifacts are
missing; it does not create fixture data.

Create and stage a run bundle:

```bash
python3 scripts/prepare_table_reproduction_bundle.py \
  --suite parser_smoke \
  --model-id minicpm5-1b-thinking-q4

BUNDLE_DIR=artifacts/table_reproduction/run_bundles/<bundle_id> \
  ./scripts/stage_table_reproduction_bundle_adb.sh
```

Run the bundle through the foreground service:

```bash
RUNNER=service \
BUNDLE_ID=<bundle_id> \
BACKEND_ID=llama_cpp \
MODEL_ID=minicpm5-1b-thinking-q4 \
SMOKE_TYPE=real_model_smoke \
TIMEOUT_SECONDS=7200 \
./scripts/run_benchmark_adb.sh
```

Score pulled raw evidence on the host:

```bash
python3 scripts/score_table_reproduction_evidence.py \
  reports/extracted/files/reports/<report_dir>
```

## Artifacts And Evidence

The app writes `raw_evidence.jsonl` in each report directory. Each row includes:

- resolved prompt/messages
- raw generation
- prompt/generated token counts
- finish reason and `hit_max_tokens`
- runtime params
- model/runtime/native/APK hashes
- dataset artifact hash
- parser/scorer identifiers
- official table baseline score

Host scoring writes:

- `table_reproduction_scored_rows.jsonl`
- `table_reproduction_summary.json`

Unsupported or unavailable official scorers, parser failures, prompt overflow,
and `finish_reason=length` stay in the denominator and are recorded as blocked
or failed rows.

## Current Limits

- The app produces raw evidence only; complex official scoring runs on the host.
- `IFEval`, `Multi-IF`, and `MultiChallenge` require their official evaluator
  or judge configuration before they can produce scored rows.
- If a model cannot allocate 80k context on Xiaomi 17, that model/dataset run is
  a formal blocker, not a reason to lower context or max tokens.
