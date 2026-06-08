#!/usr/bin/env python3
"""Validate Android MLC package outputs before Gradle consumes them."""

from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_CONFIG = ROOT / "mlc" / "MLCChat" / "mlc-package-config.json"
DIST = ROOT / "mlc" / "dist"
APP_LIBS = ROOT / "app" / "libs"
APP_JNI = ROOT / "app" / "src" / "main" / "jniLibs" / "arm64-v8a"
APP_ASSETS = ROOT / "app" / "src" / "main" / "assets" / "mlc"
SMOKE_MODEL = os.environ.get("MLC_SMOKE_MODEL_ID", "Qwen3-1.7B-q4f16_1-MLC")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}")
    return json.loads(path.read_text())


def is_elf(path: pathlib.Path) -> bool:
    try:
        return path.read_bytes()[:4] == b"\x7fELF"
    except OSError:
        return False


def main() -> None:
    package_config = load_json(PACKAGE_CONFIG)
    input_models = package_config.get("model_list") or []
    if not any(entry.get("model_id") == SMOKE_MODEL for entry in input_models):
        fail(f"{PACKAGE_CONFIG.relative_to(ROOT)} does not contain smoke model {SMOKE_MODEL}")

    if not DIST.exists():
        fail(f"missing package output root {DIST.relative_to(ROOT)}")

    config_candidates = list(DIST.glob("**/mlc-app-config.json"))
    if not config_candidates:
        fail("generated mlc-app-config.json not found under mlc/dist")
    app_config_path = config_candidates[0]
    app_config = load_json(app_config_path)
    notes = str(app_config.get("notes", ""))
    if "placeholder" in notes.lower():
        fail(f"{app_config_path.relative_to(ROOT)} is a placeholder config")

    generated_models = app_config.get("model_list") or []
    generated_smoke = next((entry for entry in generated_models if entry.get("model_id") == SMOKE_MODEL), None)
    if generated_smoke is None:
        fail(f"generated mlc-app-config.json does not contain smoke model {SMOKE_MODEL}")
    model_lib = generated_smoke.get("model_lib")
    if model_lib is not None and not str(model_lib).strip():
        fail(f"generated model_lib for {SMOKE_MODEL} is empty")

    if not APP_LIBS.exists() or not any(APP_LIBS.glob("*.aar")) and not any(APP_LIBS.glob("*.jar")):
        fail("Gradle-consumed app/libs does not contain MLC AAR/JAR artifacts")
    if not APP_ASSETS.exists() or not any(APP_ASSETS.glob("**/mlc-app-config.json")):
        fail("Gradle-consumed app assets do not contain mlc-app-config.json")
    if not APP_JNI.exists():
        fail("Gradle-consumed arm64-v8a native directory is missing")
    so_files = list(APP_JNI.glob("*.so"))
    if not so_files:
        fail("Gradle-consumed arm64-v8a native directory has no .so files")
    bad_elf = [path.name for path in so_files if not is_elf(path)]
    if bad_elf:
        fail("native libraries are not ELF files: " + ", ".join(sorted(bad_elf)))

    print("MLC Android package validation passed.")
    print(f"- input: {PACKAGE_CONFIG.relative_to(ROOT)}")
    print(f"- output: {DIST.relative_to(ROOT)}")
    print(f"- config: {app_config_path.relative_to(ROOT)}")
    print(f"- app libs: {APP_LIBS.relative_to(ROOT)}")
    print(f"- app native: {APP_JNI.relative_to(ROOT)}")
    print(f"- app assets: {APP_ASSETS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

