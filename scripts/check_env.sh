#!/usr/bin/env bash
set -euo pipefail

ADB="${ADB:-adb}"

echo "== Host disk =="
df -h "$PWD" || true

echo
echo "== Toolchain =="
command -v java || true
java -version 2>&1 | head -3 || true
command -v cmake || true
command -v mlc_llm || true
command -v python3 || true
python3 --version || true

echo
echo "== ADB =="
"$ADB" version || true
"$ADB" devices -l || true

echo
echo "== Device =="
"$ADB" shell getprop ro.product.model || true
"$ADB" shell getprop ro.build.version.release || true
"$ADB" shell getprop ro.build.version.sdk || true
"$ADB" shell getprop ro.product.cpu.abilist || true
"$ADB" shell getprop ro.hardware.egl || true
"$ADB" shell df -h /data /sdcard 2>/dev/null || true
"$ADB" shell cat /proc/meminfo | head -5 || true
