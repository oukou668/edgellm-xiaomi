# Xiaomi 17 LLM Benchmark

Android benchmark app scaffold for measuring small local LLMs on Xiaomi 17 with
MLC LLM and llama.cpp.

The app is benchmark-first:

- models are registered through JSON manifests
- QA benchmarks are registered through JSON assets
- reports are exported as JSON, JSONL, CSV, Markdown, and run manifests
- dummy backend checks and real-model smoke gates are kept separate
- MLC and llama.cpp are selected through `backend_id`
- model identity, native library hashes, source commits, and device diagnostics
  are written into every report
- MiniCPM5 table reproduction uses a strict host-built bundle flow: the phone
  generates raw evidence, and host-side scorers compute table deltas

## Current Device Notes

The connected Xiaomi device can be detected through:

```bash
adb devices -l
```

Observed target properties:

- Android 16 / API 36
- ABI: `arm64-v8a`
- GPU: Adreno 840
- device storage: about 448 GiB free under `/data`

Prefer 60 GiB+ free before compiling multiple models locally. Android SDK, NDK,
MLC build caches, and downloaded model weights can grow quickly.

## Project Layout

- `app/` - Android application source
- `app/src/main/assets/models.json` - model registry
- `app/src/main/assets/benchmarks/*.json` and `*.jsonl` - benchmark registry data
- `mlc/MLCChat/mlc-package-config.json` - MLC package config for Android
- `mlc/dist/` - generated MLC package output consumed only after validation
- `artifacts/models/` - host-side model cache for staged real-model smoke
- `scripts/` - environment, packaging, install, and report pull helpers
- `docs/development_stack.md` - pinned toolchain and path ownership
- `docs/model_matrix.md` - real smoke model matrix and success gates
- `docs/table_reproduction.md` - 4-model by 13-dataset reproduction workflow
- `docs/completion_log.md` - command and validation log

## First Run Workflow

1. Bootstrap the pinned host toolchain:

   ```bash
   ./scripts/bootstrap_android_env.sh
   ./scripts/check_env.sh
   ```

2. Generate and validate the MLC Android package:

   ```bash
   ./scripts/package_mlc_android.sh
   ```

3. Build and install the app:

   ```bash
   ./scripts/install_debug.sh
   ```

4. Stage a real GGUF smoke model when using llama.cpp:

   ```bash
   ./scripts/fetch_gguf_model.sh minicpm4-0.5b-q4_k_m
   BACKEND_ID=llama_cpp MODEL_ID=minicpm4-0.5b-q4_k_m ./scripts/stage_model_adb.sh
   ```

5. Run dummy or real smoke on the phone:

   ```bash
   BACKEND_ID=mlc SMOKE_TYPE=real_model_smoke ./scripts/run_backend_smoke_adb.sh
   BACKEND_ID=llama_cpp SMOKE_TYPE=real_model_smoke ./scripts/run_backend_smoke_adb.sh
   ```

6. Pull exported reports:

   ```bash
   ./scripts/pull_reports.sh
   ```

For command-line automation, the debug app also accepts intent extras:

```bash
ADB=/Users/heng/Downloads/platform-tools/adb \
BACKEND_ID=llama_cpp \
SMOKE_TYPE=real_model_smoke \
MODEL_ID=Qwen3-1.7B-q4f16_1-MLC \
BENCHMARK_ID=qa_real_smoke_zh_en \
REPEAT_COUNT=3 \
WARMUP_COUNT=1 \
./scripts/run_benchmark_adb.sh
```

By default the script keeps the device awake while plugged in, starts the app,
waits for the selected benchmark report, pulls the report archive, extracts it
under `reports/extracted`, and prints the Markdown summary. The app writes each
run to its sandbox under `files/reports/<timestamp>_<benchmark_id>/` with
`report.json`, `report.csv`, `report.md`, `run_manifest.json`,
`task_results.jsonl`, `generation_log.jsonl`, and
`warmup_generation_log.jsonl`.

Useful overrides:

```bash
WAIT=0 ./scripts/run_benchmark_adb.sh          # start only
PULL=0 ./scripts/run_benchmark_adb.sh          # wait but do not pull reports
TIMEOUT_SECONDS=1800 ./scripts/run_benchmark_adb.sh
STAY_AWAKE=0 ./scripts/run_benchmark_adb.sh
```

## Benchmark And Hardware Metrics

Benchmark JSON supports both legacy single `prompt` items and multi-turn
`messages` items. Complex QA items can include `difficulty`, `tags`,
`judge_rule`, and per-item `max_new_tokens`.

Strict JSONL tasks are also supported for reproducible smoke and benchmark
runs. Scored generation rows are written to `generation_log.jsonl`; warmup rows
are written separately so scored row count stays equal to `task_count *
repeat_count`.

Current benchmark sets include:

- `qa_smoke_zh_en`: bilingual QA smoke set.
- `qa_complex_stress`: longer QA, summarization, reasoning, and multi-turn tasks.
- `agent_long_horizon_tau_like`: tau-bench-inspired long-horizon agent tasks
  with domain policy, tool lists, state constraints, ordered action plans, and
  final user responses.

Reports include top-level and per-item hardware samples:

- app PSS, Java heap, and native heap
- system available/total memory and used ratio
- battery temperature
- maximum readable thermal-zone temperature and zone name

## MLC Integration

The mandatory MLC smoke model targets
`HF://mlc-ai/Qwen3-1.7B-q4f16_1-MLC` at the pinned revision in
`app/src/main/assets/models.json`. MLC package input is
`mlc/MLCChat/mlc-package-config.json`; package output is `mlc/dist/`; Gradle
only consumes synchronized artifacts in `app/libs`,
`app/src/main/jniLibs/arm64-v8a`, and `app/src/main/assets/mlc`.

The Android engine adapter expects the MLC package to provide `ai.mlc.mlcllm.JSONFFIEngine` at runtime. If that class is absent, the app reports the missing runtime in the benchmark output.

## llama.cpp Integration

The mandatory llama.cpp smoke model is
`Mungert/MiniCPM4-0.5B-GGUF/MiniCPM4-0.5B-q4_k_m.gguf`, pinned by revision,
size, and sha256 in `models.json`. The app loads GGUF files from an app-private
filesystem path, not directly from APK assets. The JNI bridge owns model,
context, sampler, and batch resources, releases partial loads, and supports
repeat load/unload smoke checks.

## Table Reproduction

The formal table reproduction config lives in
`configs/table_reproduction_v1.json`. It pins four `llama_cpp` Q4 models and 13
non-Coding/non-Agentic datasets. Validate it with:

```bash
python3 scripts/validate_table_reproduction_manifest.py
```

Official dataset artifacts must be placed under
`artifacts/table_reproduction/datasets/<dataset_id>/`; missing artifacts block
bundle creation rather than falling back to fixtures. See
`docs/table_reproduction.md` for the bundle, device-run, and host-scoring flow.
