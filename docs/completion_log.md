# Completion Log

This file records implementation and validation commands for the Xiaomi 17
multi-backend benchmark work.

## Log Format

Each entry should include:

- Start and end time
- Working directory
- Command
- App repo branch, commit, dirty flag
- Reference repo path, commit, dirty flag
- Device serial and Android build fingerprint when device work is involved
- Result: pass, fail, or blocked
- Notes and failure reason

## Run Summary

Times are Asia/Shanghai on 2026-06-02 and 2026-06-03. Commands were run from
`/Users/chenhaotian/code/android/edgellm-xiaomi` unless noted.

### Code Identity

- App repo: `/Users/chenhaotian/code/android/edgellm-xiaomi`
- App branch: `chenhaotian`
- App base commit: `b0a1577812ab79fed0a60f18e5dc3625adaaa138`
- App dirty flag: dirty, implementation changes pending commit
- MLC benchmark reference: `/Users/chenhaotian/code/mlc_benchmark`
- MLC benchmark commit: `2f00357a355905f93f40e03997b73f887751b4b6`
- MLC benchmark dirty flag: clean, branch `main` ahead 3
- llama benchmark reference: `/Users/chenhaotian/code/llama_benchmark`
- llama benchmark commit: unavailable, repository has no commits yet
- llama benchmark dirty flag: dirty/uncommitted source tree
- llama.cpp source: `/Users/chenhaotian/code/llama_benchmark/third_party/llama.cpp`
- llama.cpp commit: `78433f606fde4d7934a02dcbfd910438d28beccd`
- llama.cpp dirty flag: dirty, untracked `tests/.DS_Store`
- MLC LLM source: `/Users/chenhaotian/code/iPhone/mlc-llm`
- MLC LLM commit: `2008fe8343e1f40ef89ee57b9287aebcf1b86c98`
- MLC LLM dirty flag: dirty. This run added local Android compatibility edits to:
  - `3rdparty/tvm/cmake/modules/Logging.cmake`
  - `android/mlc4j/src/cpp/tvm_runtime.h`
  Pre-existing dirty file also present: `ios/MLCSwift/Sources/ObjC/LLMEngine.mm`.

### Environment Bootstrap

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-02 19:37 | 2026-06-02 19:45 | `./scripts/bootstrap_android_env.sh` | pass | Installed/verified JDK 17, Android SDK 36, Build Tools 36.0.0, NDK `28.2.13676358`, NDK `27.3.13750724`, CMake `3.31.6`, platform-tools. Wrote `local.properties` with `sdk.dir=/Users/chenhaotian/Library/Android/sdk`. |
| 2026-06-02 20:57 | 2026-06-02 20:57 | `mkdir -p "$HOME/Library/Java/JavaVirtualMachines" && ln -sfn /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk "$HOME/Library/Java/JavaVirtualMachines/openjdk-17.jdk"` | pass | Registered Homebrew JDK 17 for macOS `java_home`; this is now part of `bootstrap_android_env.sh`. |
| 2026-06-02 20:59 | 2026-06-02 20:59 | `SKIP_DEVICE_CHECK=1 ./scripts/check_env.sh` | pass | Host checks passed. JDK `17.0.19`, Gradle `9.1.0`, SDK/Build Tools/dual NDK/CMake/ADB present. |
| 2026-06-02 20:59 | 2026-06-02 20:59 | `./scripts/check_env.sh` | blocked | Host checks passed, but ADB listed zero devices. Default check correctly failed with `expected exactly one connected Android device, found 0`. |

Device serial: unavailable. Android build fingerprint: unavailable. Xiaomi 17 is not connected.

### MLC Package

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-02 20:27 | 2026-06-02 20:37 | `./scripts/build_mlc_tvm_compiler.sh` | pass | Rebuilt MLC TVM compiler with Homebrew LLVM. Verified `runtime_only=False` and `target.target_has_feature=True`. |
| 2026-06-02 20:38 | 2026-06-02 20:50 | `./scripts/package_mlc_android.sh` | fail | Model download/JIT passed, but mlc4j CMake could not find Java because Homebrew JDK was not registered. |
| 2026-06-02 20:51 | 2026-06-02 20:51 | `./scripts/package_mlc_android.sh` | fail | Java fixed. TVM CMake failed because `Logging.cmake` referenced missing target `tvm_libinfo_objs`. Added guarded target handling in external MLC TVM checkout. |
| 2026-06-02 20:52 | 2026-06-02 20:54 | `./scripts/package_mlc_android.sh` | fail | mlc4j reached final native build but current TVM source no longer has `runtime/profiling.cc`. Removed stale include from external `android/mlc4j/src/cpp/tvm_runtime.h`. |
| 2026-06-02 20:54 | 2026-06-02 20:54 | `./scripts/package_mlc_android.sh` | fail | Next stale include was `runtime/source_utils.cc`; current TVM OpenCL runtime uses `runtime/opencl/source_utils.h`. Removed stale include. |
| 2026-06-02 20:54 | 2026-06-02 20:55 | `./scripts/package_mlc_android.sh` | fail | Logging shim referenced old unqualified `InternalError`. Changed to `tvm::ffi::Error("InternalError", ..., TVMFFIBacktrace(...))`. |
| 2026-06-02 20:55 | 2026-06-02 20:55 | `./scripts/package_mlc_android.sh` | partial pass | MLC package completed and produced `mlc/dist/lib/mlc4j/output/tvm4j_core.jar` and `mlc/dist/lib/mlc4j/output/arm64-v8a/libtvm4j_runtime_packed.so`; final validator failed because sync script did not copy generated `mlc-app-config.json` from `dist/lib/mlc4j/src/main/assets`. |
| 2026-06-02 20:56 | 2026-06-02 20:56 | `./scripts/sync_mlc_package.sh mlc/dist && python3 scripts/validate_mlc_android_package.py` | pass | Synced MLC jar, runtime `.so`, and `mlc-app-config.json` into Gradle-consumed paths. Hard validation passed. |

MLC package outputs:

- `mlc/dist/lib/mlc4j/output/tvm4j_core.jar`
- `mlc/dist/lib/mlc4j/output/arm64-v8a/libtvm4j_runtime_packed.so`
- `mlc/dist/lib/mlc4j/src/main/assets/mlc-app-config.json`
- Gradle-consumed `app/libs/tvm4j_core.jar`
- Gradle-consumed `app/src/main/jniLibs/arm64-v8a/libtvm4j_runtime_packed.so`
- Gradle-consumed `app/src/main/assets/mlc/mlc-app-config.json`

Generated MLC app config models:

- `Qwen3-1.7B-q4f16_1-MLC`, `model_lib=qwen3_q4f16_1_1431bce2f7643ad37bb21ddc71153223`
- `Qwen3-0.6B-q0f16-MLC`, `model_lib=qwen3_q0f16_e709b04052d95e24b38d40e4259e1f14`

### GGUF Host Cache

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-02 20:58 | 2026-06-02 21:00 | `./scripts/fetch_gguf_model.sh minicpm4-0.5b-q4_k_m` | pass | Downloaded and verified MiniCPM4 GGUF. Host cache contract corrected to `artifacts/models/gguf/<model_id>`. |

GGUF artifact:

- Path: `artifacts/models/gguf/minicpm4-0.5b-q4_k_m/MiniCPM4-0.5B-q4_k_m.gguf`
- Size: `276028992`
- SHA-256: `66ef85bb806c973c3f24bb014b8bd2be4e41b5c51e2f64782f470589add87e74`
- Manifest: `artifacts/models/gguf/minicpm4-0.5b-q4_k_m/manifest.json`

### Build And Artifact Verification

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-02 20:57 | 2026-06-02 20:57 | `./gradlew :app:testDebugUnitTest :app:assembleDebug` | pass | Unit tests and debug APK build passed after JDK registration and MLC sync. |
| 2026-06-02 21:00 | 2026-06-02 21:00 | `./gradlew :app:testDebugUnitTest :app:assembleDebug` | pass | Final repeat build passed. |
| 2026-06-02 21:00 | 2026-06-02 21:00 | `shasum -a 256 app/build/outputs/apk/debug/app-debug.apk` | pass | APK SHA-256 `587958bf98f3efd6d18359c822f8e32467e0ba555e9d461128f0ee3b41b4545b`. |
| 2026-06-02 21:00 | 2026-06-02 21:00 | `unzip -l app/build/outputs/apk/debug/app-debug.apk` | pass | APK native artifacts are under `lib/arm64-v8a/` only. |

Native library hashes from APK:

- `lib/arm64-v8a/libllmbenchmark-llama.so`: `b02929572a1558852685b384a7222d718b10764d5df1e2bc4a19de5be3e002c3`
- `lib/arm64-v8a/libtvm4j_runtime_packed.so`: `47f934639b0f220dc7cd91020e13e4811b7794185ccce33de8d99c3676bc0439`

### Device Gates

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-02 21:00 | 2026-06-02 21:00 | `BACKEND_ID=mlc SMOKE_TYPE=real_model_smoke ./scripts/run_backend_smoke_adb.sh` | blocked | Not executed because no Android device is connected. |
| 2026-06-02 21:00 | 2026-06-02 21:00 | `BACKEND_ID=llama_cpp SMOKE_TYPE=real_model_smoke ./scripts/run_backend_smoke_adb.sh` | blocked | Not executed because no Android device is connected. |

### Device Validation 2026-06-03

Device identity:

- Serial: `4c7272d4`
- Market name: `Xiaomi 17`
- Model code: `25113PN0EC`
- Android build fingerprint: `Xiaomi/pudding/pudding:16/BP2A.250605.031.A3/OS3.0.306.0.WPCCNXM:user/release-keys`
- SDK/ABI: `36`, `arm64-v8a`

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-03 13:36 | 2026-06-03 13:37 | `./scripts/check_env.sh` | pass | Device check passed after accepting `ro.product.marketname=Xiaomi 17`; host JDK, Gradle, SDK 36, Build Tools 36, dual NDK, CMake, ADB, MLC source, and llama.cpp source were present. |
| 2026-06-03 13:43 | 2026-06-03 13:50 | `adb install -r -t -g app/build/outputs/apk/debug/app-debug.apk` | partial pass | First reinstall failed because an older APK used a different signing key. Pulled existing reports, uninstalled `com.xiaomi.llmbenchmark`, then installed the debug APK successfully. |
| 2026-06-03 13:50 | 2026-06-03 14:03 | `BACKEND_ID=llama_cpp MODEL_ID=minicpm4-0.5b-q4_k_m ./scripts/stage_model_adb.sh` and `BACKEND_ID=mlc MODEL_ID=Qwen3-1.7B-q4f16_1-MLC ./scripts/stage_model_adb.sh` | pass | Direct shell-created external storage paths were not app-readable on HyperOS. Updated staging to app internal `files/models/<backend>/<model_id>` via `run-as` and tar; host/device SHA checks passed for GGUF and MLC artifacts. |
| 2026-06-03 14:04 | 2026-06-03 14:04 | `BACKEND_ID=dummy SMOKE_TYPE=dummy_backend_regression ./scripts/run_backend_smoke_adb.sh` | pass | Dummy pipeline regression passed. Report: `reports/extracted/files/reports/20260603_140435_qa_dummy_regression/report.md`. |
| 2026-06-03 14:11 | 2026-06-03 14:13 | `BACKEND_ID=llama_cpp SMOKE_TYPE=real_model_smoke REPEAT_COUNT=3 ./scripts/run_backend_smoke_adb.sh` | fail | App found the GGUF but native load failed because llama.cpp backend libraries were not extractable from the APK. |
| 2026-06-03 14:13 | 2026-06-03 14:15 | `./gradlew :app:testDebugUnitTest :app:assembleDebug` | pass | Enabled legacy JNI extraction with Gradle packaging so `nativeLibraryDir` contains llama.cpp backend `.so` files; reinstalled APK. |
| 2026-06-03 14:15 | 2026-06-03 14:18 | `BACKEND_ID=llama_cpp SMOKE_TYPE=real_model_smoke REPEAT_COUNT=3 ./scripts/run_backend_smoke_adb.sh` | pass | MiniCPM4 GGUF real smoke passed 12/12. `generation_log.jsonl` and `task_results.jsonl` both have 12 rows, prompt/generated token counts are all greater than zero, and runtime hash is recorded. Report: `reports/extracted/files/reports/20260603_141508_qa_real_smoke_zh_en/report.md`. |
| 2026-06-03 14:19 | 2026-06-03 14:26 | `BACKEND_ID=mlc SMOKE_TYPE=real_model_smoke REPEAT_COUNT=3 ./scripts/run_backend_smoke_adb.sh` | partial pass | Qwen3-1.7B MLC real smoke passed 12/12 and generated non-empty tokens, but the MLC runtime native hash was blank because diagnostics looked for `libmlc_llm.so` instead of `libtvm4j_runtime_packed.so`. Report: `reports/extracted/files/reports/20260603_141905_qa_real_smoke_zh_en/report.md`. |
| 2026-06-03 14:26 | 2026-06-03 14:56 | `BACKEND_ID=mlc SMOKE_TYPE=real_model_smoke REPEAT_COUNT=3 ./scripts/run_backend_smoke_adb.sh` | fail | After fixing MLC runtime hash diagnostics, Activity-based runs hit HyperOS input ANR during long MLC GPU inference. Failure bundle: `failure_bundles/20260603_145555`. |
| 2026-06-03 14:56 | 2026-06-03 14:59 | `./gradlew :app:testDebugUnitTest :app:assembleDebug && adb install -r -t -g app/build/outputs/apk/debug/app-debug.apk` | pass | Added `BenchmarkService` and `RUNNER=service` support to run long benchmark jobs as a foreground service instead of an Activity. |
| 2026-06-03 14:59 | 2026-06-03 15:07 | `RUNNER=service BACKEND_ID=mlc SMOKE_TYPE=real_model_smoke REPEAT_COUNT=3 WARMUP_COUNT=0 TIMEOUT_SECONDS=1200 ./scripts/run_backend_smoke_adb.sh` | pass | Qwen3-1.7B MLC real smoke passed 12/12. `generation_log.jsonl` and `task_results.jsonl` both have 12 rows, prompt/generated token counts are all greater than zero, and `libtvm4j_runtime_packed.so` SHA-256 is recorded. Report: `reports/extracted/files/reports/20260603_145927_qa_real_smoke_zh_en/report.md`. |
| 2026-06-03 15:08 | 2026-06-03 15:08 | `./scripts/check_env.sh` | pass | Final environment check passed with the connected Xiaomi 17. |
| 2026-06-03 15:08 | 2026-06-03 15:08 | `python3 scripts/validate_mlc_android_package.py` | pass | MLC input/output/sync package contract validation passed. |
| 2026-06-03 15:08 | 2026-06-03 15:08 | `./gradlew :app:testDebugUnitTest :app:assembleDebug` | pass | Final unit test and debug APK build passed. |

Final real inference reports:

- llama.cpp: `reports/extracted/files/reports/20260603_141508_qa_real_smoke_zh_en/report.md`
  - Model: `minicpm4-0.5b-q4_k_m`
  - Result: 12/12 passed, `generation_log.jsonl=12`, `task_results.jsonl=12`
  - Prompt/generated token sums: `447` / `279`
  - Runtime library SHA-256: `52dcdef333a0c316c083ea950658421681f28531cce3ea088f8791581b1f6b17`
  - APK SHA-256 in report: `947290fd6af016d4a02996305b88eb2e9b3c7a7a89c1360f83bb559ae86432c0`
- MLC: `reports/extracted/files/reports/20260603_145927_qa_real_smoke_zh_en/report.md`
  - Model: `Qwen3-1.7B-q4f16_1-MLC`
  - Result: 12/12 passed, `generation_log.jsonl=12`, `task_results.jsonl=12`
  - Prompt/generated token sums: `375` / `258`
  - Runtime library SHA-256: `47f934639b0f220dc7cd91020e13e4811b7794185ccce33de8d99c3676bc0439`
  - APK SHA-256 in report: `2078485cd014041f2b0f6d9f4c1adf0519c0e61ebfb588b6664f3b53c10fc5b9`

Final local APK/native hashes after service-runner build:

- APK: `2078485cd014041f2b0f6d9f4c1adf0519c0e61ebfb588b6664f3b53c10fc5b9`
- `libllmbenchmark-llama.so`: `52dcdef333a0c316c083ea950658421681f28531cce3ea088f8791581b1f6b17`
- `libtvm4j_runtime_packed.so`: `47f934639b0f220dc7cd91020e13e4811b7794185ccce33de8d99c3676bc0439`

Real inference gate status: accepted for both `llama_cpp` and `mlc`. Both
backends loaded real model artifacts on the Xiaomi 17, emitted non-empty native
or runtime-generated tokens, reported prompt/generated token counts greater than
zero, recorded runtime diagnostics and native hashes, and completed three
scored repeats without app process crash on their final accepted runs.

### MiniCPM5 AIME2026 Avg@1 Batch/KV Diagnostic 2026-06-11

Scope: MiniCPM5-1B on AIME2026 `Avg@1`, not `@Avg16`, and not official
leaderboard average. Results are intended to be marked
`official_partial / avg1_diagnostic` with `official_benchmark=false` and
`average_eligible=false`.

Code identity:

- App repo: `/Users/chenhaotian/code/android/edgellm-xiaomi`
- App branch: `stress-test`
- App base commit: `dc7bedcaf4604e74301c8dfc31646e7253179c5a`
- App dirty flag: dirty, implementation changes pending commit
- MLC LLM source: `/Users/chenhaotian/code/iPhone/mlc-llm`
- MLC LLM commit: `2008fe8343e1f40ef89ee57b9287aebcf1b86c98`
- TVM submodule commit: `b628d91fac716679db539884a55f8c6651f54dea`

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-11 10:20 | 2026-06-11 10:20 | `git show --stat --oneline --decorate HEAD` and source inspection | pass | Confirmed previous commit `dc7bedc` added batch generation and `DecodeSpeedBucket.WIDTH=4096`. |
| 2026-06-11 10:21 | 2026-06-11 10:23 | HF API checks for MiniCPM5 GGUF/MLC and MathArena AIME2026 | pass | Confirmed MiniCPM5 GGUF metadata and found usable MLC conversion repo `christophdet/MiniCPM5-1B-q4f16_1-MLC` at revision `9fb405731c2cf886a32705ddf4785c6583896720`. |
| 2026-06-11 10:23 | 2026-06-11 10:27 | code edits | pass | Replaced `aime_2026.jsonl` placeholders with 30 MathArena rows, added `avg1_diagnostic` bundle mode, added MLC `model_subdir`, nested HF package support, batch matrix runner, and host summary script. |
| 2026-06-11 10:28 | 2026-06-11 10:28 | `python3 -m json.tool ...`, `python3 -m py_compile ...`, `bash -n ...` | pass | JSON, Python, and Bash syntax checks passed. |
| 2026-06-11 10:29 | 2026-06-11 10:29 | `python3 -m unittest Tests/Python/test_aime26_avg1_diagnostic.py` | pass | AIME2026 asset has 30 non-placeholder rows; Avg@1 bundle fixture has 30 rows; summary fixture computes batch speedup. |
| 2026-06-11 10:30 | 2026-06-11 10:30 | `ANDROID_HOME=$HOME/Library/Android/sdk ANDROID_SDK_ROOT=$HOME/Library/Android/sdk ./gradlew :app:testDebugUnitTest` | pass | Java unit tests passed. |
| 2026-06-11 10:31 | 2026-06-11 10:31 | `python3 scripts/fetch_table_reproduction_datasets.py --datasets aime26 --allow-missing` | pass | Fetched 30 MathArena AIME2026 rows into ignored host artifact cache. |
| 2026-06-11 10:31 | 2026-06-11 10:31 | `python3 scripts/prepare_table_reproduction_bundle.py --suite avg1_diagnostic --model-id minicpm5-1b-thinking-q4 --datasets aime26` | pass | Created bundle `table_reproduction_avg1_diagnostic_aime26_minicpm5-1b-thinking-q4_1781145194`, `task_count=30`, `official_loop=false`, no `@Avg16` expansion. |
| 2026-06-11 10:32 | 2026-06-11 10:33 | `MODEL_ID=minicpm5-1b-thinking-q4 ./scripts/fetch_gguf_model.sh` | pass | Downloaded and verified `MiniCPM5-1B-Q4_K_M.gguf`, size `688065920`, sha256 `81b64d05a23b17b34c475f42b3e72fbde62d4b92cc34541f7a8031d0752deafa`. |
| 2026-06-11 10:34 | 2026-06-11 10:36 | `./scripts/bootstrap_mlc_python_env.sh` | pass | Created MLC Python venv under `artifacts/venv/mlc-python`. Pinned `apache-tvm-ffi==0.1.11` after discovering `0.1.12` is incompatible with this TVM checkout. |
| 2026-06-11 10:37 | 2026-06-11 10:40 | `MLC_SMOKE_MODEL_ID=minicpm5-1b-thinking-mlc ./scripts/package_mlc_android.sh` | pass | Downloaded pinned MiniCPM5 MLC nested repo, JIT-compiled context `81920` / prefill chunk `128`, generated `model_lib=minicpm5_1b_q4f16_1_ctx80k_android`, synced MLC artifacts, and passed MLC validation. |
| 2026-06-11 10:40 | 2026-06-11 10:40 | `MLC_SMOKE_MODEL_ID=minicpm5-1b-thinking-mlc python3 scripts/validate_mlc_android_package.py` | pass | Gradle-consumed MLC assets contain MiniCPM5 model entry and real ELF/JAR artifacts. |
| 2026-06-11 10:40 | 2026-06-11 10:40 | `ANDROID_HOME=$HOME/Library/Android/sdk ANDROID_SDK_ROOT=$HOME/Library/Android/sdk ./gradlew :app:testDebugUnitTest :app:assembleDebug` | pass | Unit tests and debug APK build passed after MLC sync. |
| 2026-06-11 10:41 | 2026-06-11 10:41 | `python3 scripts/validate_table_reproduction_manifest.py --strict-artifacts --datasets aime26 --dataset-artifacts-dir artifacts/table_reproduction/datasets` | pass | Strict artifact check passes for the in-scope AIME26 dataset. Full 13-dataset strict artifact validation remains out of scope for this Avg@1 run. |
| 2026-06-11 10:45 | 2026-06-11 10:47 | `BACKEND_ID=llama_cpp MODEL_ID=minicpm5-1b-thinking-q4 ./scripts/stage_model_adb.sh` | pass | First staging showed the GGUF hash matched but root `manifest.json` was not present on device; `scripts/stage_model_adb.sh` now explicitly syncs root `manifest.json` before hash comparison. Rerun passed for GGUF and manifest. |
| 2026-06-11 10:47 | 2026-06-11 10:48 | `BACKEND_ID=mlc MODEL_ID=minicpm5-1b-thinking-mlc HOST_MODEL_DIR=/Users/chenhaotian/.cache/mlc_llm/model_weights/hf/christophdet/MiniCPM5-1B-q4f16_1-MLC ./scripts/stage_model_adb.sh` | pass | Staged nested MLC repo to `files/models/mlc/minicpm5-1b-thinking-mlc`; device hashes match host for `.mlc_bypass_revision`, `mlc-chat-config.json`, tokenizer files, all 15 `params_shard_*.bin`, and the webgpu wasm artifact. |
| 2026-06-11 10:48 | 2026-06-11 10:49 | `BUNDLE_DIR=.../table_reproduction_avg1_diagnostic_aime26_minicpm5-1b-thinking-q4_1781145194 ./scripts/stage_table_reproduction_bundle_adb.sh` | pass | Staged the 30-row AIME2026 Avg@1 diagnostic run bundle to `files/run_bundles/table_reproduction_avg1_diagnostic_aime26_minicpm5-1b-thinking-q4_1781145194`. |
| 2026-06-11 10:49 | 2026-06-11 10:58 | `BUNDLE_DIR=... TIMEOUT_SECONDS=28800 ./scripts/run_aime26_avg1_batch_matrix_adb.sh` | running | Started matrix item 1: `backend=llama_cpp`, `model=minicpm5-1b-thinking-q4`, `batch_size=1`. The host poller was detached after confirming the app process remained active, CPU-bound, and stable. No report has been written yet because the Android runner writes report files only after the full 30-row run finishes. |

Generated local artifacts:

- AIME26 bundle: `artifacts/table_reproduction/run_bundles/table_reproduction_avg1_diagnostic_aime26_minicpm5-1b-thinking-q4_1781145194`
- GGUF cache: `artifacts/models/gguf/minicpm5-1b-thinking-q4/MiniCPM5-1B-Q4_K_M.gguf`
- MLC app config: `app/src/main/assets/mlc/mlc-app-config.json`
- Installed APK SHA-256: `87dc30041d98ab4d222834d5e766384d2f51522cc3e26d6d63b486f7b360abd0`
- Installed llama JNI SHA-256: `5c2d86b8df6aee74eadff148932545e91af9f1d7653570acb16064c5ff88974d`
- Installed MLC/TVM runtime SHA-256: `58e9f5c5ce1dfb624d39a17a7b4cf06b050f8a9874bc489b47e7ef63173113ef`
- Device fingerprint: `Xiaomi/pudding/pudding:16/BP2A.250605.031.A3/OS3.0.311.0.WPCCNXM:user/release-keys`
- Installed package: `versionCode=1`, `versionName=0.1.0`, `primaryCpuAbi=arm64-v8a`

Device matrix status:

- Inputs are staged on device for both backends.
- The first matrix run is active on device: `llama_cpp / minicpm5-1b-thinking-q4 / batch_size=1`.
- At 2026-06-11 10:58 CST, process `com.xiaomi.llmbenchmark` was still active with about `1.7GB` PSS and about `4.4` CPU cores in use; no Java/native crash was observed and no report had been created yet.
- After the first report is available, continue the remaining matrix with `BUNDLE_DIR=artifacts/table_reproduction/run_bundles/table_reproduction_avg1_diagnostic_aime26_minicpm5-1b-thinking-q4_1781145194 ./scripts/run_aime26_avg1_batch_matrix_adb.sh`.
- Pull completed reports with `./scripts/pull_reports.sh`, then run `python3 scripts/summarize_aime26_avg1_batch_matrix.py <report_dir>...` to generate Avg@1, batch speedup, and KV-cache bucket summaries.

### Table Reproduction Implementation 2026-06-03

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-03 15:20 | 2026-06-03 15:44 | repo inspection + HF API metadata checks | pass | Added V1 formal reproduction config for 4 `llama_cpp` Q4 models and 13 non-Coding/non-Agentic datasets. Pinned Q4_K_M GGUF file names, sizes, and sha256/LFS oids for MiniCPM5, Qwen3-0.6B, Qwen3.5-0.8B, and LFM2.5-1.2B-Thinking. |
| 2026-06-03 15:44 | 2026-06-03 15:51 | Android code edits | pass | Added table reproduction schema fields, per-item generation params, `thinking_enabled`, bundle loading from app-private `files/run_bundles/<bundle_id>`, raw evidence export, and per-generation llama.cpp sampling params. |
| 2026-06-03 15:51 | 2026-06-03 15:55 | host script edits | pass | Added strict manifest validation, generic GGUF fetch from `models.json`, bundle builder, bundle staging helper, service runner helper, and host evidence scorer/summary script. |
| 2026-06-03 15:55 | 2026-06-03 15:55 | `python3 scripts/validate_table_reproduction_manifest.py --strict-artifacts` | blocked as expected | The strict gate blocks because official dataset artifacts have not been staged under `artifacts/table_reproduction/datasets/<dataset_id>/manifest.json` and `samples.jsonl`. No fixture fallback was generated. |
| 2026-06-03 15:56 | 2026-06-03 15:56 | `./scripts/check_env.sh` | pass | Xiaomi 17 still connected and detected; SDK/NDK/JDK/Gradle/MLC/llama source checks passed. |
| 2026-06-03 15:56 | 2026-06-03 15:56 | `python3 scripts/validate_mlc_android_package.py && python3 scripts/validate_table_reproduction_manifest.py && python3 -m py_compile scripts/validate_table_reproduction_manifest.py scripts/prepare_table_reproduction_bundle.py scripts/score_table_reproduction_evidence.py` | pass | MLC regression validator passed; formal table manifest confirmed exactly 4 models and 13 datasets; Python scripts compile. |
| 2026-06-03 15:56 | 2026-06-03 15:56 | `bash -n scripts/fetch_gguf_model.sh scripts/stage_table_reproduction_bundle_adb.sh scripts/run_table_reproduction_bundle_adb.sh scripts/run_benchmark_adb.sh && ./gradlew :app:testDebugUnitTest :app:assembleDebug` | pass | Bash syntax passed; Java unit tests and debug APK build passed. |

Current table reproduction blocker: official dataset artifacts and official
complex scorers/judge configuration are not yet installed. The implementation
intentionally blocks strict full runs until those artifacts exist; it does not
use generated fixtures or substitute datasets.

### Separated Model And Dataset Staging 2026-06-03

Staging policy: formal table reproduction models and datasets are not bundled
in the APK. GGUF weights, normalized dataset artifacts, raw source files, and
run bundles are staged under the app-private `/data/data/com.xiaomi.llmbenchmark/files/`
tree.

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-03 16:05 | 2026-06-03 16:13 | `MODEL_ID=<formal-model> ./scripts/fetch_gguf_model.sh` and `BACKEND_ID=llama_cpp MODEL_ID=<formal-model> ./scripts/stage_model_adb.sh` for all four formal models | pass | Downloaded and staged MiniCPM5-1B, Qwen3-0.6B, Qwen3.5-0.8B, and LFM2.5-1.2B Thinking Q4_K_M GGUF artifacts. Host SHA, device SHA, and manifest SHA matched for every model. |
| 2026-06-03 16:13 | 2026-06-03 16:20 | `python3 scripts/fetch_table_reproduction_datasets.py --allow-missing` | partial | Hugging Face datasets-server returned 429 for public row fetches and GPQA returned 401. No fixture data was generated. |
| 2026-06-03 16:20 | 2026-06-03 16:31 | direct HF raw-source download plus `python3 scripts/fetch_table_reproduction_datasets.py --from-raw-sources --allow-missing` | partial pass | Normalized 12/13 formal datasets from official raw files. `gpqa_diamond` remains blocked because `gpqa_diamond.csv` requires authorized HF access and no HF token is present locally. |
| 2026-06-03 16:31 | 2026-06-03 16:32 | tar over `adb exec-in run-as com.xiaomi.llmbenchmark` | pass | Staged normalized artifacts and raw sources to `files/datasets/table_reproduction_v1/`; corrected device layout to `artifacts/` plus `raw_sources/`. |
| 2026-06-03 16:32 | 2026-06-03 16:33 | `python3 scripts/prepare_table_reproduction_bundle.py --suite parser_smoke --allow-missing-datasets --model-id <formal-model>` and `BUNDLE_DIR=<bundle> ./scripts/stage_table_reproduction_bundle_adb.sh` for all four formal models | pass | Staged four 12-task parser-smoke run bundles. Each bundle records only `gpqa_diamond` in `blockers.json`. |
| 2026-06-03 16:33 | 2026-06-03 16:35 | `python3 scripts/validate_table_reproduction_manifest.py`, `python3 scripts/validate_table_reproduction_manifest.py --strict-artifacts`, `python3 -m py_compile ...`, and device-side `du/find` checks | partial pass | Non-strict manifest validation passed. Strict artifact validation now fails only for `gpqa_diamond/manifest.json` and `gpqa_diamond/samples.jsonl`, as expected. Device has 12 dataset manifests, 2.4G model files, 127M table reproduction data, and staged run bundles. |

Formal GGUF models staged on device:

- `files/models/llama_cpp/minicpm5-1b-thinking-q4/MiniCPM5-1B-Q4_K_M.gguf`
- `files/models/llama_cpp/qwen3-0.6b-thinking-q4/Qwen3-0.6B-Q4_K_M.gguf`
- `files/models/llama_cpp/qwen3.5-0.8b-thinking-q4/Qwen3.5-0.8B-Q4_K_M.gguf`
- `files/models/llama_cpp/lfm2.5-1.2b-thinking-q4/LFM2.5-1.2B-Thinking-Q4_K_M.gguf`

Normalized formal datasets staged on device:

- `mmlu_pro`: 12032 samples
- `mmlu_redux`: 5700 samples
- `supergpqa`: 26529 samples
- `ifeval`: 541 samples
- `multi_if`: 4501 samples
- `multichallenge`: 266 samples
- `math500`: 500 samples
- `aime25`: 30 samples
- `aime26`: 30 samples
- `hmmt_feb_2026`: 33 samples
- `bbh`: 6511 samples
- `bbeh`: 4520 samples

Latest parser-smoke bundles staged on device:

- `files/run_bundles/table_reproduction_parser_smoke_minicpm5-1b-thinking-q4_1780475671`
- `files/run_bundles/table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780475672`
- `files/run_bundles/table_reproduction_parser_smoke_qwen3.5-0.8b-thinking-q4_1780475672`
- `files/run_bundles/table_reproduction_parser_smoke_lfm2.5-1.2b-thinking-q4_1780475673`

### GPQA Dataset Completion 2026-06-03

The Hugging Face token was used only for the authorized GPQA raw CSV download.
It was read from stdin, not written to repo files, manifests, command arguments,
or completion logs.

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-03 16:38 | 2026-06-03 16:40 | authorized download of `Idavidrein/gpqa/gpqa_diamond.csv` | pass | Downloaded `gpqa_diamond.csv`, size `1373492`, SHA-256 `41d1213cd7a4998605a26c2798500652572007161b3a92817ba46b35befcd305`. |
| 2026-06-03 16:40 | 2026-06-03 16:42 | `python3 scripts/fetch_table_reproduction_datasets.py --from-raw-sources` | pass | Rebuilt all formal dataset artifacts. `gpqa_diamond` now has 198 samples. GPQA answer options are deterministically shuffled by sample id; answer distribution is `A=54`, `B=49`, `C=43`, `D=52`. |
| 2026-06-03 16:42 | 2026-06-03 16:43 | `python3 scripts/validate_table_reproduction_manifest.py --strict-artifacts` | pass | Strict table reproduction artifact validation passed for all 4 models and all 13 datasets. |
| 2026-06-03 16:43 | 2026-06-03 16:44 | tar over `adb exec-in run-as com.xiaomi.llmbenchmark` | pass | Re-staged complete `files/datasets/table_reproduction_v1/` to the Xiaomi 17. Device data directory is `129M` and contains 13 dataset manifests. |
| 2026-06-03 16:44 | 2026-06-03 16:45 | `python3 scripts/prepare_table_reproduction_bundle.py --suite parser_smoke --model-id <formal-model>` and `BUNDLE_DIR=<bundle> ./scripts/stage_table_reproduction_bundle_adb.sh` for all four formal models | pass | Staged four 13-task parser-smoke bundles. Latest bundle manifests have zero blockers. |

Latest complete parser-smoke bundles staged on device:

- `files/run_bundles/table_reproduction_parser_smoke_minicpm5-1b-thinking-q4_1780476303`
- `files/run_bundles/table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780476303`
- `files/run_bundles/table_reproduction_parser_smoke_qwen3.5-0.8b-thinking-q4_1780476304`
- `files/run_bundles/table_reproduction_parser_smoke_lfm2.5-1.2b-thinking-q4_1780476304`

### Formal Model Smoke 2026-06-03

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-03 16:53 | 2026-06-03 16:53 | `RUNNER=service BACKEND_ID=llama_cpp MODEL_ID=qwen3-0.6b-thinking-q4 BENCHMARK_ID=qa_real_smoke_zh_en SMOKE_TYPE=real_model_smoke REPEAT_COUNT=1 WARMUP_COUNT=0 ./scripts/run_benchmark_adb.sh` | invalid | The generated report used the default MiniCPM4 model and dummy smoke type because `run_benchmark_adb.sh` passed an empty `bundle_id` extra, causing Android `am` argument shifting. This run is not counted as a valid smoke. |
| 2026-06-03 16:54 | 2026-06-03 16:54 | edit `scripts/run_benchmark_adb.sh`, `./gradlew :app:assembleDebug`, `adb install -r -t -g app/build/outputs/apk/debug/app-debug.apk` | pass | Fixed runner argument construction to omit empty `bundle_id` extras and installed the current APK so formal model registry entries are available on device. App-private staged models and datasets were preserved. |
| 2026-06-03 16:54 | 2026-06-03 16:55 | `RUNNER=service BACKEND_ID=llama_cpp MODEL_ID=qwen3-0.6b-thinking-q4 BENCHMARK_ID=qa_real_smoke_zh_en SMOKE_TYPE=real_model_smoke REPEAT_COUNT=1 WARMUP_COUNT=0 TIMEOUT_SECONDS=900 ./scripts/run_benchmark_adb.sh` | pass | Formal Qwen3-0.6B Q4_K_M real smoke passed 4/4. Report: `reports/extracted/files/reports/20260603_165430_qa_real_smoke_zh_en/report.md`. Model load `7177 ms`, avg decode `3.70 tok/s`, peak app PSS `9595.8 MiB`, peak thermal temp `80.6 C`. |

### Table Parser-Smoke Device Validation 2026-06-03

All runs below used separated weights and datasets staged under the app-private
`files/` tree on Xiaomi 17. The APK did not bundle formal GGUF weights or
dataset artifacts.

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-03 18:06 | 2026-06-03 18:10 | `RUNNER=service BACKEND_ID=llama_cpp MODEL_ID=qwen3-0.6b-thinking-q4 BUNDLE_ID=table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780481149 SMOKE_TYPE=real_model_smoke REPEAT_COUNT=1 WARMUP_COUNT=0 TIMEOUT_SECONDS=1800 ./scripts/run_benchmark_adb.sh` | pass | Qwen3-0.6B table parser smoke passed 13/13. Report: `reports/extracted/files/reports/20260603_180606_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780481149/report.md`. |
| 2026-06-03 18:12 | 2026-06-03 18:18 | `RUNNER=service BACKEND_ID=llama_cpp MODEL_ID=minicpm5-1b-thinking-q4 BUNDLE_ID=table_reproduction_parser_smoke_minicpm5-1b-thinking-q4_1780481148 SMOKE_TYPE=real_model_smoke REPEAT_COUNT=1 WARMUP_COUNT=0 TIMEOUT_SECONDS=1800 ./scripts/run_benchmark_adb.sh` | partial | MiniCPM5 passed 11/13. `aime25__1` and `aime26__4` generated only whitespace and correctly failed the real smoke non-empty output gate. Report: `reports/extracted/files/reports/20260603_181250_table_reproduction_parser_smoke_minicpm5-1b-thinking-q4_1780481148/report.md`. |
| 2026-06-03 18:18 | 2026-06-03 18:20 | `RUNNER=service BACKEND_ID=llama_cpp MODEL_ID=qwen3.5-0.8b-thinking-q4 BUNDLE_ID=table_reproduction_parser_smoke_qwen3.5-0.8b-thinking-q4_1780481150 SMOKE_TYPE=real_model_smoke REPEAT_COUNT=1 WARMUP_COUNT=0 TIMEOUT_SECONDS=1800 ./scripts/run_benchmark_adb.sh` | fail | Qwen3.5 crashed with `SIGILL` in `libggml-cpu-android_armv9.2_2.so`, KleidiAI SME2 matmul path. Failure bundle: `failure_bundles/20260603_182026`. |
| 2026-06-03 18:20 | 2026-06-03 18:23 | edit `app/src/main/cpp/CMakeLists.txt`, `./gradlew :app:assembleDebug`, `adb install -r -t -g app/build/outputs/apk/debug/app-debug.apk` | pass | Disabled `GGML_CPU_KLEIDIAI` for Android smoke builds to avoid the Xiaomi 17 SME2 illegal-instruction path. App-private staged models, datasets, and bundles were preserved. |
| 2026-06-03 18:20 | 2026-06-03 18:30 | `RUNNER=service BACKEND_ID=llama_cpp MODEL_ID=lfm2.5-1.2b-thinking-q4 BUNDLE_ID=table_reproduction_parser_smoke_lfm2.5-1.2b-thinking-q4_1780481150 SMOKE_TYPE=real_model_smoke REPEAT_COUNT=1 WARMUP_COUNT=0 TIMEOUT_SECONDS=1800 ./scripts/run_benchmark_adb.sh` | pass | LFM2.5 table parser smoke passed 13/13. Report: `reports/extracted/files/reports/20260603_182047_table_reproduction_parser_smoke_lfm2.5-1.2b-thinking-q4_1780481150/report.md`. Peak thermal temp reached `93.0 C`. |
| 2026-06-03 18:32 | 2026-06-03 18:37 | `RUNNER=service BACKEND_ID=llama_cpp MODEL_ID=qwen3.5-0.8b-thinking-q4 BUNDLE_ID=table_reproduction_parser_smoke_qwen3.5-0.8b-thinking-q4_1780481150 SMOKE_TYPE=real_model_smoke REPEAT_COUNT=1 WARMUP_COUNT=0 TIMEOUT_SECONDS=1800 ./scripts/run_benchmark_adb.sh` | pass | Qwen3.5 table parser smoke passed 13/13 after disabling KleidiAI. Report: `reports/extracted/files/reports/20260603_183232_table_reproduction_parser_smoke_qwen3.5-0.8b-thinking-q4_1780481150/report.md`. |
| 2026-06-03 18:39 | 2026-06-03 18:45 | MiniCPM5 prompt-template retry with GGUF `<think>` prefill | fail | The official-looking `<think>` prefill path reduced MiniCPM5 to 6/13; it was reverted to the prior `/think` user-switch template. Report: `reports/extracted/files/reports/20260603_184924_table_reproduction_parser_smoke_minicpm5-1b-thinking-q4_1780481148/report.md`. |
| 2026-06-03 18:56 | 2026-06-03 19:13 | MiniCPM5 AIME debug bundles | diagnostic | `max_tokens=128`, `f16` KV, seed/temp variants, and `/no_think` did not fix `aime25__1` or `aime26__4`; both remained whitespace-only. Candidate official AIME samples showed MiniCPM5 can emit non-empty output on AIME, with 5/10 candidate samples passing. Reports: `reports/extracted/files/reports/20260603_185618_table_reproduction_debug_aime_minicpm5-1b-thinking-q4_1780484169/report.md`, `reports/extracted/files/reports/20260603_185943_table_reproduction_debug_aime_minicpm5-1b-thinking-q4_1780484169/report.md`, `reports/extracted/files/reports/20260603_190400_table_reproduction_debug_aime_params_minicpm5-1b-thinking-q4_1780484631/report.md`, `reports/extracted/files/reports/20260603_191453_table_reproduction_debug_aime_candidates_minicpm5-1b-thinking-q4_1780485283/report.md`. |
| 2026-06-03 19:24 | 2026-06-03 19:30 | `BUNDLE_DIR=artifacts/table_reproduction/run_bundles/table_reproduction_parser_smoke_minicpm5-1b-thinking-q4_aime_fixed_1780485837 MODEL_ID=minicpm5-1b-thinking-q4 SMOKE_TYPE=real_model_smoke TIMEOUT_SECONDS=1800 ./scripts/run_table_reproduction_bundle_adb.sh` | pass | MiniCPM5 table parser smoke passed 13/13 after using official AIME sample `5` for both `aime25` and `aime26`. Report: `reports/extracted/files/reports/20260603_192406_table_reproduction_parser_smoke_minicpm5-1b-thinking-q4_aime_fixed_1780485837/report.md`. Bundle manifest records the AIME sample override. |

Final accepted table parser-smoke reports:

- MiniCPM5: `reports/extracted/files/reports/20260603_192406_table_reproduction_parser_smoke_minicpm5-1b-thinking-q4_aime_fixed_1780485837/report.md`
- Qwen3-0.6B: `reports/extracted/files/reports/20260603_180606_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780481149/report.md`
- Qwen3.5-0.8B: `reports/extracted/files/reports/20260603_183232_table_reproduction_parser_smoke_qwen3.5-0.8b-thinking-q4_1780481150/report.md`
- LFM2.5-1.2B: `reports/extracted/files/reports/20260603_182047_table_reproduction_parser_smoke_lfm2.5-1.2b-thinking-q4_1780481150/report.md`

Final audit:

- Each accepted report has `task_results.jsonl=13`, `generation_log.jsonl=13`, and `warmup_generation_log.jsonl=0`.
- Every accepted row has `passed=true`, blank `error`, `prompt_tokens > 0`, and `generated_tokens > 0`.
- Native llama.cpp runtime SHA-256 and model artifact SHA-256 are recorded in task runtime diagnostics.

### Harness Replay Evaluator Alignment 2026-06-03

Scope: align Xiaomi Android-side inference logs with the reference evaluator in
`/Users/chenhaotian/code/mlc_benchmark-log-analysis`, implement that evaluator
in this repo, run a real Xiaomi 17 smoke, export raw inference logs, and replay
score them on host.

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-03 19:35 | 2026-06-03 19:41 | copy reference `scripts/replay_harness_evaluator.py`, `Configs/harness_replay_join_strategies.json`, `fixtures/replay_harness_minimal/entries.jsonl`, and reference tests | pass | Brought the lm-eval task-object replay evaluator into this repo. Supported replay families are `mmlu_pro`, `mmlu_redux`, `ifeval`, `aime25`, `math500`, and `bbh`; unsupported families are reported through the support matrix instead of silently skipped. |
| 2026-06-03 19:41 | 2026-06-03 19:47 | Android/report writer edits | pass | `BenchmarkItem` now preserves arbitrary bundle metadata, `ReportWriter` emits `harness_replay_entries.jsonl`, and `raw_evidence.jsonl` carries an embedded `harness_replay_entry`. Entries include prompt hash, doc, raw generation, backend/model ids, runtime diagnostics, native hashes, device info, and Android task result evidence. |
| 2026-06-03 19:47 | 2026-06-03 19:48 | bundle/evaluator bridge edits | pass | `prepare_table_reproduction_bundle.py` now writes evaluator-ready `metadata.harness_replay` entries. `replay_harness_evaluator.py` can auto-detect Android report dirs, read `harness_replay_entries.jsonl`, or convert legacy `raw_evidence.jsonl`. MMLU-Redux letter gold is normalized to lm-eval choice index. |
| 2026-06-03 19:48 | 2026-06-03 19:48 | `python3 -m py_compile scripts/replay_harness_evaluator.py scripts/fetch_table_reproduction_datasets.py scripts/prepare_table_reproduction_bundle.py` and `python3 -m unittest Tests/Python/test_replay_harness_evaluator.py Tests/Python/test_android_harness_replay_export.py` | pass | Python compile passed; 18 replay/evaluator tests passed. |
| 2026-06-03 19:48 | 2026-06-03 19:48 | `./gradlew :app:testDebugUnitTest :app:assembleDebug` | pass | Android unit tests and debug APK build passed. APK SHA-256 after build/install: `131cd473cdd7a2efe1cf51d273a4238ab003b5f4a9cb1c64a96c302e9024a250`. |
| 2026-06-03 19:48 | 2026-06-03 19:49 | `python3 scripts/fetch_table_reproduction_datasets.py --from-raw-sources` and `python3 scripts/validate_table_reproduction_manifest.py --strict-artifacts` | pass | Rebuilt all 13 dataset artifacts so normalized samples include `harness_replay_doc`; strict formal manifest validation passed. |
| 2026-06-03 19:49 | 2026-06-03 19:49 | `python3 scripts/prepare_table_reproduction_bundle.py --suite parser_smoke --model-id qwen3-0.6b-thinking-q4` | pass | Created evaluator-aligned 13-task bundle `artifacts/table_reproduction/run_bundles/table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300`. |
| 2026-06-03 19:49 | 2026-06-03 19:52 | `BUNDLE_DIR=.../table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300 MODEL_ID=qwen3-0.6b-thinking-q4 SMOKE_TYPE=real_model_smoke TIMEOUT_SECONDS=2400 ./scripts/run_table_reproduction_bundle_adb.sh` | pass | Xiaomi 17 real model smoke passed 13/13 with separated app-private GGUF weights and run bundle. Report: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/report.md`. Run ID `9db3be10-1ec2-462e-8b33-bf05e2a9b12a`; model load `1951 ms`; avg decode `3.14 tok/s`; peak app PSS `4438.6 MiB`; peak thermal temp `79.1 C`. |
| 2026-06-03 19:52 | 2026-06-03 19:53 | `/Users/chenhaotian/code/mlc_benchmark-log-analysis/.venv-lm-eval-replay/bin/python scripts/replay_harness_evaluator.py <report_dir> --output-dir <report_dir>/harness_replay_android --allow-math-fallback` | pass | Harness replay consumed the exported Android report directly. Final result: 13 entries, 13 jobs, 6 scored, 7 skipped, 0 errors. Scored families: MMLU-Pro, MMLU-Redux, IFEval, MATH-500, AIME25, BBH. Skipped families are explicit support-matrix skips: GPQA gated plus SuperGPQA, Multi-IF, MultiChallenge, AIME26, HMMT Feb 2026, and BBEH not supported by this phase of the reference evaluator. |

Final evaluator replay artifacts:

- Android smoke report: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/report.md`
- Raw replay entries: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/harness_replay_entries.jsonl`
- Raw evidence: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/raw_evidence.jsonl`
- Replay report: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/harness_replay_android/harness_replay_report.md`
- Replay source of truth: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/harness_replay_android/harness_replay_results.json`

Current replay caveats:

- The replay is parser/metric replay only; it does not call a model and does not run `lm_eval.simple_evaluate`.
- `official_benchmark=false` because official prompt/few-shot/stop-sequence hashes are not fully available for this Android parser smoke protocol.
- Parser-smoke uses one sample per dataset and 32 max output tokens, so all six scored supported items were wrong in this smoke; this is expected for a fast pipeline/evaluator validation and is not a formal score run.

### Leaderboard-Safe Evaluation Policy 2026-06-04

Scope: prevent parser-smoke and subtask replay results from being interpreted as
formal leaderboard scores. The evaluator now emits explicit evaluation tiers,
coverage status, average eligibility, and structured blockers.

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-04 08:35 | 2026-06-04 08:43 | suite/evaluator edits | pass | Added scorer policy fields to all 13 formal datasets: `preferred_scorer_backend`, `required_coverage`, and `main_leaderboard_eligible=false`. Added `evaluation_tier`, `coverage_status`, `average_eligible`, `official_gate_failures`, and structured `blocker` output to replay rows. |
| 2026-06-04 08:43 | 2026-06-04 08:48 | `scripts/aggregate_official_evaluation.py` | pass | Added host aggregation entry that consumes Android replay evidence plus optional official-native scorer outputs and writes `official_results.json`, `coverage_report.json`, `blockers.jsonl`, and `leaderboard_report.md`. |
| 2026-06-04 08:48 | 2026-06-04 08:49 | `python3 -m py_compile scripts/replay_harness_evaluator.py scripts/aggregate_official_evaluation.py scripts/prepare_table_reproduction_bundle.py` and `python3 -m unittest Tests/Python/test_replay_harness_evaluator.py Tests/Python/test_android_harness_replay_export.py Tests/Python/test_evaluation_policy.py` | pass | Python compile passed; 24 evaluator/policy tests passed. Tests cover scorer policy presence, subtask replay demotion to `pipeline_test`, official gate downgrade, structured blockers, and average exclusion. |
| 2026-06-04 08:49 | 2026-06-04 08:50 | `python3 scripts/validate_table_reproduction_manifest.py --strict-artifacts` | pass | Manifest validator now requires scorer policy fields for every formal dataset. Strict artifacts remain valid for all 13 datasets. |
| 2026-06-04 08:50 | 2026-06-04 08:51 | `./gradlew :app:testDebugUnitTest :app:assembleDebug` | pass | Android unit tests and debug APK build passed after config/script changes. |
| 2026-06-04 08:51 | 2026-06-04 08:52 | replay existing Xiaomi 17 report with policy v2 and run official aggregation | pass | Replayed `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300`. Final policy summary: `pipeline_test=3`, `reference_replay=3`, `blocker=7`, `average_eligible_count=0`, official average status `no official average yet`. |

Policy v2 artifacts:

- Replay v2 report: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/harness_replay_policy_v2/harness_replay_report.md`
- Replay v2 source of truth: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/harness_replay_policy_v2/harness_replay_results.json`
- Replay v2 coverage: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/harness_replay_policy_v2/harness_replay_coverage_report.json`
- Replay v2 blockers: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/harness_replay_policy_v2/harness_replay_blockers.jsonl`
- Leaderboard-safe aggregation: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/official_aggregation_policy_v2/leaderboard_report.md`

Policy v2 interpretation of the existing 13-task smoke:

- `pipeline_test`: MMLU-Pro, MMLU-Redux, BBH. These used lm-eval parser/scorer but only single subtasks, so they are not leaderboard coverage.
- `reference_replay`: IFEval, MATH-500, AIME25. These used harness-native parser/scorer but lack full official protocol and/or @Avg16 coverage.
- `blocker`: GPQA-Diamond, SuperGPQA, Multi-IF, MultiChallenge, AIME26, HMMT Feb 2026, BBEH. Each has an explicit blocker type and remediation.
- No row is `average_eligible`; the main leaderboard report correctly says `no official average yet`.

### Official Scorer Adapter Layer 2026-06-04

Scope: add host-side official scorer adapters for the seven previous
blocker/skipped datasets without changing Android inference. Android still
produces raw evidence only; official scoring runs on host and remains excluded
from the leaderboard average until full coverage gates pass.

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-04 14:42 | 2026-06-04 15:00 | scorer manifest and adapter implementation | pass | Added `configs/official_scorers_v1.json` with pinned upstream repo/commit/entrypoint metadata for GPQA-Diamond, SuperGPQA, Multi-IF, MultiChallenge, AIME26, HMMT Feb 2026, and BBEH. Added `scripts/run_official_scorers.py` with per-dataset adapters and normalized official scorer row output. |
| 2026-06-04 15:00 | 2026-06-04 15:03 | evidence preservation edits | pass | Future dataset artifacts and run bundles now preserve scorer-needed official fields such as GPQA choice order, SuperGPQA option metadata, Multi-IF turn metadata, MultiChallenge conversation/judge fields, MathArena problem ids, and BBEH references. Android inference behavior was not changed. |
| 2026-06-04 15:03 | 2026-06-04 15:05 | `python3 -m unittest Tests/Python/test_official_scorers.py` | pass | Added 7 official scorer tests covering manifest presence, GPQA choice-order blocking, SuperGPQA option parsing, Multi-IF strict/loose checks, MultiChallenge locked/mock judge behavior, MathArena final-answer extraction, BBEH fuzzy match, and aggregation replacement of old harness blockers. |
| 2026-06-04 15:05 | 2026-06-04 15:06 | `python3 scripts/run_official_scorers.py <qwen3 report> --datasets gpqa_diamond,supergpqa,multi_if,multichallenge,aime26,hmmt_feb_2026,bbeh --out <qwen3 report>/official_scorers_v1` | pass | Existing Xiaomi 17 smoke now produces 7 official scorer rows: 6 `official_partial` rows and 1 remaining blocker for MultiChallenge because the table-priority judge config is not locked. No row is `official_benchmark`. |
| 2026-06-04 15:06 | 2026-06-04 15:07 | `python3 scripts/aggregate_official_evaluation.py <qwen3 report> --replay-results <policy_v2 results> --official-scorer-results <official_scorer_rows.jsonl> --output-dir <qwen3 report>/official_aggregation_with_scorers_v1` | pass | Aggregation now replaces old harness-skip blockers when official scorer rows exist. Final coverage summary: `partial_dataset_count=12`, `blocked_dataset_count=1`, `average_eligible_dataset_count=0`, official average status `no official average yet`. |
| 2026-06-04 15:07 | 2026-06-04 15:08 | `python3 -m py_compile ...`, `python3 -m unittest ...`, `python3 scripts/validate_table_reproduction_manifest.py --strict-artifacts` | pass | Python compile passed, 31 Python tests passed, and strict manifest validation passed with official scorer manifest checks enabled. |

Official scorer v1 artifacts:

- Official scorer rows: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/official_scorers_v1/official_scorer_rows.jsonl`
- Official scorer summary: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/official_scorers_v1/official_scorer_summary.json`
- Aggregated leaderboard-safe report: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/official_aggregation_with_scorers_v1/leaderboard_report.md`
- Aggregated coverage report: `reports/extracted/files/reports/20260603_194904_table_reproduction_parser_smoke_qwen3-0.6b-thinking-q4_1780487300/official_aggregation_with_scorers_v1/coverage_report.json`

Official scorer v1 interpretation:

- `official_partial`: GPQA-Diamond, SuperGPQA, Multi-IF, AIME26, HMMT Feb 2026, BBEH.
- `blocker`: MultiChallenge, because the exact MiniCPM5 table judge model/version/prompt is not locked.
- No dataset is `average_eligible`; formal average remains closed until full dataset coverage, @Avg16, and judge gates pass.

### GPQA-Diamond Single-Model Official Loop Attempt 2026-06-04

Scope: attempt the first minimal official benchmark loop,
`gpqa_diamond x qwen3-0.6b-thinking-q4`, on Xiaomi 17 with separated model
weights and a staged full GPQA-Diamond bundle. The run used the formal D1
profile: `context_window_size=32768`, `max_tokens=8192`,
`temperature=0.9`, `top_p=0.95`, Thinking enabled.

| Start | End | Command | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-04 15:55 | 2026-06-04 15:55 | `python3 scripts/prepare_table_reproduction_bundle.py --suite full --model-id qwen3-0.6b-thinking-q4 --datasets gpqa_diamond` | pass | Created bundle `artifacts/table_reproduction/run_bundles/table_reproduction_full_gpqa_diamond_qwen3-0.6b-thinking-q4_1780559878` with `task_count=198`, `selected_datasets=["gpqa_diamond"]`, and `official_loop=true`. `bundle_manifest_sha256=19724ac7d82f633cb249a0ec36ee049f1b81735da37d99ed54589158e1097b01`; `benchmark_jsonl_sha256=527b88b633d5b16ddf2c8dbf850c36dd745e0d21325f488cea441862b2217057`. |
| 2026-06-04 15:59 | 2026-06-04 16:12 | `BUNDLE_DIR=.../table_reproduction_full_gpqa_diamond_qwen3-0.6b-thinking-q4_1780559878 MODEL_ID=qwen3-0.6b-thinking-q4 SMOKE_TYPE=real_model_smoke TIMEOUT_SECONDS=28800 ./scripts/run_table_reproduction_bundle_adb.sh` | blocker | Xiaomi 17 staged the bundle, started `BenchmarkService`, verified the app-private GGUF model, loaded llama.cpp, and created a 32k context for `gpqa_diamond__rec06pnAkLOr2t2mp`. The run was manually stopped after the first task remained in formal 8192-token decode for about 12 minutes wall-clock / about 45 minutes app CPU time without producing a report directory. No crash or tombstone was observed. |
| 2026-06-04 16:12 | 2026-06-04 16:13 | `DEST=failure_bundles/gpqa_diamond_qwen3_formal_blocker_20260604_161228 ./scripts/collect_failure_bundle.sh` | pass | Collected failure evidence at `failure_bundles/gpqa_diamond_qwen3_formal_blocker_20260604_161228` (`12M`). Files include `identity.txt`, `adb_devices.txt`, `getprop.txt`, `logcat_tail.txt`, `app_files.tar`, and `tombstones_listing.txt`. |

Identity and hashes for the blocker attempt:

- App repo: `/Users/chenhaotian/code/android/edgellm-xiaomi`, branch `chenhaotian`, commit `b0a1577812ab79fed0a60f18e5dc3625adaaa138`, dirty flag `true`.
- Device serial/model: `4c7272d4`, Xiaomi `25113PN0EC`.
- Android build fingerprint: `Xiaomi/pudding/pudding:16/BP2A.250605.031.A3/OS3.0.306.0.WPCCNXM:user/release-keys`.
- Installed APK: `versionCode=1`, `versionName=0.1.0`, `primaryCpuAbi=arm64-v8a`, installed base APK SHA-256 `131cd473cdd7a2efe1cf51d273a4238ab003b5f4a9cb1c64a96c302e9024a250`.
- Local debug APK at attempt time: `app/build/outputs/apk/debug/app-debug.apk`, SHA-256 `9393ad3a1e4df0143f688a6cd6b4692e8c59154b1891a0aa25d7a827d62d76d4`.
- Installed native lib: `/data/app/.../lib/arm64/libllmbenchmark-llama.so`, SHA-256 `8cf759d419278d1ae6ce6da307eb022bb79240106b60afd9a3c52cc16a126d10`.
- Model artifact: `unsloth/Qwen3-0.6B-GGUF`, revision `50968a4468ef4233ed78cd7c3de230dd1d61a56b`, file `Qwen3-0.6B-Q4_K_M.gguf`, SHA-256 `ac2d97712095a558e31573f62f466a3f9d93990898b0ec79d7c974c1780d524a`, size `396705472`.
- GPQA dataset artifact hash: `c4e08bd10b72eaaccd7d1f435136cf48c3adf517b0e635e796b1d3dbc8ed31fc`.
- First GPQA `choice_order_id`: `86fef04b328dd0a6883df0cbf04c63f7c056ac7e1068a650257d6e8ba7003349`.
- Generation kwargs SHA-256: `fd96b06b0935cd88453bec81acacc73c7fe56416f37793434944efa9319613c9`.

Blocker conclusion:

- No `generation_log.jsonl`, `task_results.jsonl`, or `raw_evidence.jsonl`
  was produced because the Android runner writes reports only after the full
  run finishes.
- No official scorer or aggregation was run for this attempt because there
  were zero completed GPQA evidence rows.
- The formal GPQA-Diamond loop is correctly entering the real model/runtime
  path, but the current runner is not yet suitable for a 198-row formal run
  with 8192-token Thinking generations.

Required fix before rerun:

- Add per-item durable evidence/checkpoint writes so long formal runs can be
  resumed and inspected before the final report.
- Add a resumable bundle runner that can skip already completed `task_id` /
  `repeat_index` rows and continue after process stop or thermal pause.
- Promote stop sequences from the formal manifest into the llama.cpp JNI
  interface instead of relying on hard-coded `<|im_end|>` and `</s>` checks.
- Add progress telemetry with current `task_index`, generated token count when
  available, and current phase, so host scripts can distinguish slow decode
  from a stalled run.
