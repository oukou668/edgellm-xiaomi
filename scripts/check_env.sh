#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"
SDK_ROOT="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
APP_NDK_VERSION="${APP_NDK_VERSION:-28.2.13676358}"
MLC_NDK_VERSION="${MLC_NDK_VERSION:-27.3.13750724}"
MLC_SOURCE_DIR="${MLC_LLM_SOURCE_DIR:-/Users/chenhaotian/code/iPhone/mlc-llm}"
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-/Users/chenhaotian/code/llama_benchmark/third_party/llama.cpp}"
SKIP_DEVICE_CHECK="${SKIP_DEVICE_CHECK:-0}"

if [[ -z "${JAVA_HOME:-}" ]] && command -v brew >/dev/null 2>&1 && brew --prefix openjdk@17 >/dev/null 2>&1; then
  export JAVA_HOME="$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home"
  export PATH="$JAVA_HOME/bin:$PATH"
fi

export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="$SDK_ROOT/cmdline-tools/latest/bin:$SDK_ROOT/platform-tools:$PATH"

failures=0

section() {
  printf '\n== %s ==\n' "$1"
}

check_file() {
  if [[ -e "$1" ]]; then
    printf 'ok: %s\n' "$1"
  else
    printf 'missing: %s\n' "$1"
    failures=$((failures + 1))
  fi
}

check_cmd() {
  if command -v "$1" >/dev/null 2>&1; then
    printf 'ok: %s -> %s\n' "$1" "$(command -v "$1")"
  else
    printf 'missing command: %s\n' "$1"
    failures=$((failures + 1))
  fi
}

section "Host"
df -h "$ROOT" || true
uname -a || true

section "Java"
if command -v java >/dev/null 2>&1; then
  java -version 2>&1 | head -3 || failures=$((failures + 1))
else
  printf 'missing command: java\n'
  failures=$((failures + 1))
fi

section "Android SDK"
printf 'ANDROID_HOME=%s\n' "$SDK_ROOT"
check_file "$SDK_ROOT/platform-tools/adb"
check_file "$SDK_ROOT/platforms/android-36/android.jar"
check_file "$SDK_ROOT/build-tools/36.0.0/aapt2"
check_file "$SDK_ROOT/ndk/$APP_NDK_VERSION/source.properties"
check_file "$SDK_ROOT/ndk/$MLC_NDK_VERSION/source.properties"
check_file "$SDK_ROOT/cmake/3.31.6/bin/cmake"

section "Commands"
check_cmd cmake
check_cmd ninja
check_cmd git
check_cmd python3
if command -v "$ADB" >/dev/null 2>&1; then
  "$ADB" version || true
else
  check_cmd "$ADB"
fi

section "Gradle"
if [[ -x "$ROOT/gradlew" ]]; then
  "$ROOT/gradlew" --version | sed -n '1,12p' || failures=$((failures + 1))
else
  printf 'missing gradlew\n'
  failures=$((failures + 1))
fi

section "Source Identity"
git -C "$ROOT" status --short --branch || true
git -C "$ROOT" rev-parse HEAD || true
if [[ -d "$MLC_SOURCE_DIR/.git" ]]; then
  printf 'MLC_LLM_SOURCE_DIR=%s\n' "$MLC_SOURCE_DIR"
  git -C "$MLC_SOURCE_DIR" rev-parse HEAD || true
  git -C "$MLC_SOURCE_DIR" status --short --branch || true
else
  printf 'missing MLC_LLM_SOURCE_DIR git checkout: %s\n' "$MLC_SOURCE_DIR"
  failures=$((failures + 1))
fi
if [[ -d "$LLAMA_CPP_DIR" ]]; then
  printf 'LLAMA_CPP_DIR=%s\n' "$LLAMA_CPP_DIR"
  git -C "$LLAMA_CPP_DIR" rev-parse HEAD 2>/dev/null || true
else
  printf 'missing llama.cpp checkout: %s\n' "$LLAMA_CPP_DIR"
  failures=$((failures + 1))
fi

section "ADB Device"
if command -v "$ADB" >/dev/null 2>&1; then
  "$ADB" devices -l || true
  if [[ "$SKIP_DEVICE_CHECK" == "1" ]]; then
    printf 'device check skipped with SKIP_DEVICE_CHECK=1\n'
  else
    device_count="$("$ADB" devices | awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }')"
    if [[ "$device_count" != "1" ]]; then
      printf 'expected exactly one connected Android device, found %s\n' "$device_count"
      failures=$((failures + 1))
    else
      model="$("$ADB" shell getprop ro.product.model 2>/dev/null | tr -d '\r')"
      marketname="$("$ADB" shell getprop ro.product.marketname 2>/dev/null | tr -d '\r')"
      fingerprint="$("$ADB" shell getprop ro.build.fingerprint 2>/dev/null | tr -d '\r')"
      sdk="$("$ADB" shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r')"
      abis="$("$ADB" shell getprop ro.product.cpu.abilist 2>/dev/null | tr -d '\r')"
      printf 'model=%s\n' "$model"
      printf 'marketname=%s\n' "$marketname"
      printf 'fingerprint=%s\n' "$fingerprint"
      printf 'sdk=%s\n' "$sdk"
      printf 'abis=%s\n' "$abis"
      if [[ "$model" != *"Xiaomi 17"* && "$model" != *"xiaomi 17"* && "$marketname" != *"Xiaomi 17"* && "$marketname" != *"xiaomi 17"* ]]; then
        printf 'expected Xiaomi 17 model or marketname, got: model=%s marketname=%s\n' "$model" "$marketname"
        failures=$((failures + 1))
      fi
      if [[ "$sdk" != "36" ]]; then
        printf 'expected Android API 36, got: %s\n' "$sdk"
        failures=$((failures + 1))
      fi
      if [[ "$abis" != *"arm64-v8a"* ]]; then
        printf 'expected arm64-v8a ABI, got: %s\n' "$abis"
        failures=$((failures + 1))
      fi
    fi
  fi
fi

if (( failures > 0 )); then
  printf '\ncheck_env failed with %d missing/invalid item(s).\n' "$failures" >&2
  exit 1
fi

printf '\ncheck_env passed.\n'
