# Xiaomi 17 LLM Benchmark

Android benchmark app scaffold for measuring small Qwen-family LLMs on Xiaomi 17 with MLC LLM.

The app is benchmark-first:

- models are registered through JSON manifests
- QA benchmarks are registered through JSON assets
- reports are exported as JSON, CSV, and Markdown
- MLC runtime integration is isolated behind a reflection-based engine adapter so the app can be built around the official `mlc_llm package` output

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
- `app/src/main/assets/benchmarks/*.json` - benchmark registry data
- `mlc/MLCChat/mlc-package-config.json` - MLC package config for Android
- `scripts/` - environment, packaging, install, and report pull helpers

## First Run Workflow

1. Install Android Studio or an Android SDK/NDK/CMake toolchain.
2. Install `mlc-llm` following the official MLC docs.
3. Generate the MLC Android package:

   ```bash
   ./scripts/package_mlc_android.sh
   ```

4. Build and install the app:

   ```bash
   ./scripts/install_debug.sh
   ```

5. Run the QA benchmark on the phone.
6. Pull exported reports:

   ```bash
   ./scripts/pull_reports.sh
   ```

For command-line automation, the debug app also accepts intent extras:

```bash
ADB=/Users/heng/Downloads/platform-tools/adb \
MODEL_ID=Qwen3-1.7B-q4f16_1-MLC \
BENCHMARK_ID=qa_complex_stress \
./scripts/run_benchmark_adb.sh
```

The app writes each run to its sandbox under `files/reports/<timestamp>_<benchmark_id>/`
with `report.json`, `report.csv`, and `report.md`.

## Benchmark And Hardware Metrics

Benchmark JSON supports both legacy single `prompt` items and multi-turn
`messages` items. Complex QA items can include `difficulty`, `tags`,
`judge_rule`, and per-item `max_new_tokens`.

Reports include top-level and per-item hardware samples:

- app PSS, Java heap, and native heap
- system available/total memory and used ratio
- battery temperature
- maximum readable thermal-zone temperature and zone name

## MLC Integration

The first model entry targets `HF://mlc-ai/Qwen3-1.7B-q4f16_1-MLC`, which is a 1-2B Qwen-family MLC model suitable for the requested first pass. The app keeps the APK lightweight by downloading model weights on first use instead of bundling them.

The Android engine adapter expects the MLC package to provide `ai.mlc.mlcllm.JSONFFIEngine` at runtime. If that class is absent, the app reports the missing runtime in the benchmark output.
