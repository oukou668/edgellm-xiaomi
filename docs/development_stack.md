# Development Stack

This project targets Xiaomi 17 on Android 16/API 36 with two local inference
backends: MLC LLM and llama.cpp.

## Pinned Versions

- JDK: 17
- Android Gradle Plugin: 9.0.1
- Gradle wrapper: 9.1.0
- Android SDK platform: android-36
- Android Build Tools: 36.0.0
- App and llama.cpp NDK: 28.2.13676358
- MLC packaging NDK: 27.3.13750724
- SDK CMake: 3.31.6
- llama.cpp commit: 78433f606fde4d7934a02dcbfd910438d28beccd
- MLC source checkout: /Users/chenhaotian/code/iPhone/mlc-llm
- MLC Python FFI wheel: apache-tvm-ffi 0.1.11, pinned by
  `scripts/bootstrap_mlc_python_env.sh` for compatibility with the current TVM
  checkout.

AGP 9.0.1 is intentionally pinned for first-round stability. AGP 9.2+ is
deferred unless a build failure requires it.

## Paths

- Android SDK: `$HOME/Library/Android/sdk`
- macOS Java registration: `$HOME/Library/Java/JavaVirtualMachines/openjdk-17.jdk`
- MLC package input: `mlc/MLCChat/mlc-package-config.json`
- MLC package output: `mlc/dist`
- Gradle-consumed MLC Java/runtime artifacts: `app/libs`
- Gradle-consumed native artifacts: `app/src/main/jniLibs/arm64-v8a`
- Gradle-consumed runtime assets: `app/src/main/assets/mlc`
- Host MLC model cache: `artifacts/models/mlc/<model_id>`
- Host GGUF model cache: `artifacts/models/gguf/<model_id>`
- Device model staging: app-internal `files/models/<backend_id>/<model_id>` via debug `run-as`
- Device run-bundle staging: app-internal `files/run_bundles/<bundle_id>` via debug `run-as`

## Bootstrap

Run:

```bash
./scripts/bootstrap_android_env.sh
./scripts/check_env.sh
```

`local.properties` must only contain `sdk.dir`. Do not write a global `ndk.dir`;
Gradle and MLC packaging intentionally use different NDK versions.

## Validation

Expected host checks:

```bash
java -version
adb version
sdkmanager --list_installed
./gradlew --version
./gradlew :app:assembleDebug
```

Expected device smoke gates:

```bash
BACKEND_ID=mlc SMOKE_TYPE=real_model_smoke ./scripts/run_backend_smoke_adb.sh
BACKEND_ID=llama_cpp SMOKE_TYPE=real_model_smoke ./scripts/run_backend_smoke_adb.sh
```

Device smoke and diagnostic runs do not require a cold start. The default runner
keeps the loaded model/runtime in the app process after a run
(`UNLOAD_AFTER_RUN=0`) so adjacent runs can reuse it. Use
`UNLOAD_AFTER_RUN=1` only at an intentional backend/model boundary or when
freeing memory. Battery and thermal readings are always recorded, but there is
no device start-temperature gate.

MiniCPM5 AIME2026 Avg@1 batch/KV diagnostic:

```bash
python3 scripts/fetch_table_reproduction_datasets.py --datasets aime26 --allow-missing
python3 scripts/prepare_table_reproduction_bundle.py \
  --suite avg1_diagnostic \
  --model-id minicpm5-1b-thinking-q4 \
  --datasets aime26
MODEL_ID=minicpm5-1b-thinking-q4 ./scripts/fetch_gguf_model.sh
MLC_SMOKE_MODEL_ID=minicpm5-1b-thinking-mlc ./scripts/package_mlc_android.sh
BUNDLE_DIR=<generated-bundle> ./scripts/run_aime26_avg1_batch_matrix_adb.sh
```

The matrix runner executes `llama_cpp` and `mlc` with `BATCH_SIZE=1,2,4`.
Within each backend block it keeps the model loaded between batch sizes and
unloads only after the backend's final batch. It writes per-run Android reports
and, when reports are pulled locally,
`scripts/summarize_aime26_avg1_batch_matrix.py` emits the Avg@1, batch
speedup, and KV-cache bucket summary.
