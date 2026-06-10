# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An Android app that benchmarks small LLMs running **on-device**, targeting a Xiaomi phone
(arm64-v8a, Adreno GPU). It is **benchmark-first**: models and benchmark suites are data
(JSON). There are **two inference backends** selected per-model by `backend_id`:
- **MLC** ([MLC LLM](https://github.com/mlc-ai/mlc-llm)) — reached through a reflection-only
  adapter (`MlcInferenceEngine`) so the app code never compiles against MLC classes.
- **llama.cpp** — a JNI backend (`LlamaCppInferenceEngine` + `app/src/main/cpp/llama_jni.cpp`)
  that loads GGUF weights and uses each model's official chat template from GGUF metadata.

Output is per-run reports in JSON/CSV/Markdown with latency, estimated tokens/s,
hardware/thermal telemetry, batch-throughput metrics, and a KV-length decode-speed profile.

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

The **llama.cpp** backend is compiled from source by the app's CMake build
(`app/src/main/cpp/CMakeLists.txt`); it needs a llama.cpp checkout at `LLAMA_CPP_DIR` (Gradle
property / hardcoded macOS default) and the Android NDK. `GGML_CPU_KLEIDIAI` is forced OFF
(SME2 SIGILL on the Xiaomi device). GGUF weights download from Hugging Face at first use.

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
   EngineFactory.create(context, backendId) → MlcInferenceEngine | LlamaCppInferenceEngine | Dummy
                                          │   .load / generate / generateBatch / unload
   HardwareMonitor (background sampler) ───┤
   Judge.score(item, output) ─────────────┤
                                          ▼
                              BenchmarkRunReport → ReportWriter (json/csv/md)
```

`BenchmarkService` runs the same flow headlessly as a foreground service (intent extras).

Key design points (each requires reading multiple files to grasp):

- **Two backends behind one `InferenceEngine` interface.** `EngineFactory.create(context,
  backendId)` returns `MlcInferenceEngine` (reflection into `ai.mlc.mlcllm.JSONFFIEngine`),
  `LlamaCppInferenceEngine` (JNI to `llama_jni.cpp`), or `DummyInferenceEngine` (for the report
  pipeline). `InferenceEngine` has `generate` (single) and `generateBatch` (true parallel
  decoding); the default `generateBatch` falls back to a sequential loop. Engine failures are
  caught and recorded **per item** rather than crashing the run.

- **llama.cpp parallel batching.** `nativeGenerateBatch` prefills each prompt into its own
  sequence then decodes all sequences with one `llama_decode` per step. Total `n_ctx =
  perSeqContext × batchSize` (each sequence gets the full per-seq context), so large
  batch×context combinations can legitimately OOM. Prompts are formatted with the model's
  **official GGUF chat template** (`common_chat_templates_*`, `enable_thinking` toggle) — there
  is no hand-rolled prompt string builder.

- **MLC batching + thinking.** `MlcInferenceEngine` switches `reload` to `"server"` mode for
  batched runs and fires N concurrent `chatCompletion` requests demuxed by request id. It sends
  the item's messages **verbatim** (no injected system prompt / `/no_think`); thinking is
  governed by the model's official conversation template from `mlc-chat-config.json`.

- **Per-sample timeout = 120 min** on both backends. On timeout the engine returns the partial
  generation with `finish_reason="timeout"` (it does NOT throw), so the decode-speed profile is
  preserved.

- **MLC `model_lib` must match the compiled library; GGUF artifacts are sha/size-verified.**
  For MLC models, `generate` passes `model_lib = "system://" + model.modelLib`; the hashed
  `model_lib` in `models.json` must stay in sync with `mlc/MLCChat/mlc-package-config.json`, and
  adding an MLC model means editing *both* and re-running `package_mlc_android.sh`. For llama.cpp
  models, `ModelPreflight` hard-verifies the GGUF's `artifact_size_bytes` and `artifact_sha256`
  before load (wrong values fail the run); no packaging step is needed.

- **Registries are auto-discovered from assets.** Adding a benchmark = drop a `.json`/`.jsonl`
  file in `app/src/main/assets/benchmarks/` (dir listed at runtime). Adding a model = edit
  `models.json` (+ MLC package config for MLC models).

- **Judging is string-match, not a model judge.** `Judge` normalizes (lowercase, collapse
  whitespace) and supports `judge_rule`: `contains` (default; ALL comma-separated needles),
  `contains_any`, `contains_ordered` (in order), `exact`, and `boxed_integer`/`final_integer`
  (extract the last `\boxed{...}` integer, else the last 0-999 integer, compare numerically —
  used for AIME math). `expected_answer` is a comma-separated needle list (a plain integer for
  the boxed rule).

- **Token counts and tok/s are estimates** for MLC (`estimateTokens`, a CJK-char + ASCII-word
  heuristic); llama.cpp reports real token counts and exact per-step decode timing.

- **Token-limit gotcha.** Per-item `max_new_tokens` wins, floored at `MIN_MAX_NEW_TOKENS = 1`;
  a model's `default_params.max_tokens` and a benchmark's `default_max_new_tokens` are the
  fallbacks. Adjust limits at the item level (`resolvedParams` overrides `maxTokens`).

- **Hardware telemetry.** `HardwareMonitor` samples on a background thread tagged with the
  current phase (`model_load`, `inference`, `post_inference`, `unload`, …). Each
  `BenchmarkItemResult` keeps the samples taken during its inference; `HardwareSummary`
  computes peaks for the report. Thermal reading scans `/sys/class/thermal`, normalizes
  milli-°C, and skips battery-current/trip zones.

- **Reports** land in the app sandbox at `files/reports/<yyyyMMdd_HHmmss>_<benchmark_id>/`
  (`report.json`/`.csv`/`.md`) and are extracted to `reports/extracted/` on the host by
  `pull_reports.sh` (relies on debug-build `run-as`).

- **Stress test (batch throughput + decode-speed profile).** `BenchmarkRunOptions.batchSize`
  (intent extra `batch_size`) groups items into batches and calls `generateBatch`; `batchSize=1`
  is byte-identical to the per-item path. Reports add `batch_metrics[]` (aggregate tok/s per
  batch — the throughput-vs-batch-size signal) and `decode_speed_profile` (`DecodeSpeedBucket`,
  width 4096) showing decode tok/s vs KV-cache length up to 64K. The `aime_2026` benchmark uses
  the official MathArena prompt (problem + "Put your final answer within \boxed{}...") with the
  `boxed_integer` judge. Drive it with `BATCH_SIZE=4 BENCHMARK_ID=aime_2026
  MODEL_ID=minicpm5-1b-thinking-q4 BACKEND_ID=llama_cpp SMOKE_TYPE=real_model_smoke` (see the
  plan at `~/.claude/plans/` for the full matrix and feasibility caveats).

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
