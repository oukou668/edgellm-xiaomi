# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An Android app that benchmarks small Qwen-family LLMs running **on-device** via the
[MLC LLM](https://github.com/mlc-ai/mlc-llm) runtime, targeting a Xiaomi phone
(arm64-v8a, Adreno GPU). It is **benchmark-first**: models and benchmark suites are data
(JSON), and the runtime is reached through a reflection-only adapter so the app code never
compiles against MLC classes. Output is per-run reports in JSON/CSV/Markdown with latency,
estimated tokens/s, and hardware/thermal telemetry.

## Critical build prerequisite

**A fresh checkout cannot build the app.** `app/build.gradle.kts` adds source/asset dirs from
`../mlc/package/lib/mlc4j/...`, and the runtime `.aar`/`.jar`/`.so` artifacts live in
`app/libs/`, `app/src/main/jniLibs/`, and `app/src/main/assets/mlc/` — all **gitignored** and
**generated**, not committed. They are produced by the MLC packaging step. Until that runs,
`assembleDebug` will fail or produce an APK with no working engine.

The packaging step (`scripts/package_mlc_android.sh`) additionally requires, on the host:
- A clone of `mlc-ai/mlc-llm` at `vendor/mlc-llm` (or `$MLC_LLM_SOURCE_DIR`).
- The `mlc-llm` Python package installed.
- Android SDK + NDK + CMake (paths in the script are hardcoded to a macOS `~/Library/Android/sdk` layout; override the `ANDROID_*`/`TVM_NDK_CC` env vars on other hosts).
- ~60 GiB+ free disk for SDK/NDK/build caches/weights.

## Commands

```bash
# 1. (once) Build the MLC Android runtime package, then sync artifacts into app/.
#    Requires vendor/mlc-llm + mlc-llm python pkg + Android NDK/SDK/CMake.
./scripts/package_mlc_android.sh        # → mlc/package, then runs sync_mlc_package.sh
./scripts/sync_mlc_package.sh           # re-copy artifacts into app/ without rebuilding

# 2. Build + install the debug APK on a connected device.
./scripts/install_debug.sh              # gradlew :app:assembleDebug + adb install -r
./gradlew :app:assembleDebug            # build only

# 3. Drive a benchmark headlessly over adb (autorun via intent extras), then pull reports.
ADB=/path/to/adb MODEL_ID=Qwen3-1.7B-q4f16_1-MLC BENCHMARK_ID=qa_complex_stress \
  ./scripts/run_benchmark_adb.sh
#   WAIT=0 start-only · PULL=0 wait but don't pull · TIMEOUT_SECONDS=1800 · STAY_AWAKE=0

./scripts/pull_reports.sh               # tar reports out of the app sandbox (debug run-as)
./scripts/check_env.sh                  # host toolchain + device probe (adb getprop, df, meminfo)
```

There is **no automated test suite** and no lint config. Verification is empirical: run a
benchmark on a device and inspect the report. Model weights are **not** bundled — the app
downloads them from Hugging Face on first use of a model.

## Architecture

Flow (all under `app/src/main/java/com/xiaomi/llmbenchmark/`):

```
MainActivity ──UI/intent autorun──▶ BenchmarkRunner.run(model, benchmark, ProgressSink)
                                          │
   ModelRegistry / BenchmarkRegistry ─────┤ (parse JSON assets into ModelConfig / BenchmarkConfig)
                                          │
   ModelDownloader.ensureModel ───────────┤ (HF repo or direct URL → files/models/<id>/)
                                          │
   EngineFactory.create → MlcInferenceEngine.load / generate / unload
                                          │   (reflection into ai.mlc.mlcllm.JSONFFIEngine)
   HardwareMonitor (background sampler) ───┤
   Judge.score(item, output) ─────────────┤
                                          ▼
                              BenchmarkRunReport → ReportWriter (json/csv/md)
```

Key design points (each requires reading multiple files to grasp):

- **The MLC runtime is reached only by reflection.** `MlcInferenceEngine` is the *single*
  file that names MLC classes (`ai.mlc.mlcllm.JSONFFIEngine`). It loads native libs by name,
  proxies the streaming callback, spins up background loop daemon threads, and speaks an
  OpenAI-style `chatCompletion` JSON protocol parsing SSE-like delta events (matched by request
  id; completion is signalled by a non-null `usage` or a `finish_reason`). There is a per-item
  wall-clock timeout of `max(180s, maxNewTokens·2s)`; on timeout it resets the engine and
  throws. If the runtime class is absent or generation times out, the exception is caught and
  `BenchmarkRunner` records the failure **per item** rather than crashing the run. To swap
  engines, add an `InferenceEngine` impl and change `EngineFactory`.

- **`model_lib` must match the compiled library.** `generate` passes `model_lib =
  "system://" + model.modelLib`. The hashed `model_lib` strings in
  `app/src/main/assets/models.json` are emitted by the packaging step and **must stay in sync**
  with `mlc/MLCChat/mlc-package-config.json`. Adding a model means editing *both* files and
  re-running `package_mlc_android.sh`.

- **Registries are auto-discovered from assets.** Adding a benchmark = drop a JSON file in
  `app/src/main/assets/benchmarks/` (the dir is listed at runtime). Adding a model = edit
  `models.json` (+ package config, above).

- **Qwen3-specific prompting.** Each request prepends a system prompt forbidding
  chain-of-thought / `<think>` blocks, and appends `\n/no_think` to every user turn.

- **Judging is string-match, not a model judge.** `Judge` normalizes (lowercase, collapse
  whitespace) and supports `judge_rule`: `contains` (default; ALL comma-separated needles),
  `contains_any`, `contains_ordered` (needles must appear in order), `exact`. `expected_answer`
  is a comma-separated needle list.

- **Token counts and tok/s are estimates.** `estimateTokens` is a CJK-char + ASCII-word
  heuristic, not the real tokenizer — treat decode tok/s as approximate.

- **Token-limit gotcha.** `generate` uses `item.maxNewTokens`, and `BenchmarkItem` floors it
  at `MIN_MAX_NEW_TOKENS = 192`. The `max_tokens` in a model's `default_params` and a
  benchmark's `default_max_new_tokens` are parsed but effectively overridden by the per-item
  value and that floor — adjust limits at the item level.

- **Hardware telemetry.** `HardwareMonitor` samples on a background thread tagged with the
  current phase (`model_load`, `inference`, `post_inference`, `unload`, …). Each
  `BenchmarkItemResult` keeps the samples taken during its inference; `HardwareSummary`
  computes peaks for the report. Thermal reading scans `/sys/class/thermal`, normalizes
  milli-°C, and skips battery-current/trip zones.

- **Reports** land in the app sandbox at `files/reports/<yyyyMMdd_HHmmss>_<benchmark_id>/`
  (`report.json`/`.csv`/`.md`) and are extracted to `reports/extracted/` on the host by
  `pull_reports.sh` (relies on debug-build `run-as`).

## Conventions & environment

- **No AndroidX, no XML layouts.** `android.useAndroidX=false`; the entire UI is built
  programmatically in `MainActivity` with framework `View`s. `minSdk=28`, `compile/targetSdk=36`,
  Java (not Kotlin) for app code, **arm64-v8a only**.
- Package name / `applicationId`: `com.xiaomi.llmbenchmark`.
- **China-network mirrors are baked in:** `settings.gradle.kts` uses Aliyun maven mirrors, and
  `scripts/mlc_package_bypass.py` rewrites Hugging Face URLs to `hf-mirror.com`
  (override via `MLC_HF_ENDPOINT`).
- `scripts/mlc_package_bypass.py` exists to work around a broken MLC nightly wheel whose
  top-level `import mlc_llm` fails; it loads only the `mlc_llm.cli.package` submodule as a
  namespace package. `scripts/mlc_bypass_pkg/` is a shim put on `PYTHONPATH` for the same reason.
```
