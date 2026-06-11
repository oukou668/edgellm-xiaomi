#!/usr/bin/env python3
"""Run MLC LLM package while bypassing the top-level mlc_llm import.

The current macOS arm64 nightly wheel imports serving modules from
``mlc_llm.__init__`` and can fail before the packaging CLI is reached when
native runtime libraries are mismatched. The package command itself can be
loaded by treating the installed ``mlc_llm`` directory as a namespace package.
"""

import importlib
import importlib.util
import hashlib
import json
import os
import site
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

_HF_ENDPOINT = "https://hf-mirror.com"
_PACKAGE_MODEL_META = {}


def find_mlc_llm_package() -> Path:
    explicit = os.environ.get("MLC_LLM_PYTHON_PACKAGE_DIR")
    if explicit:
        package_dir = Path(explicit)
        if (package_dir / "cli" / "package.py").is_file():
            return package_dir
        raise RuntimeError(f"MLC_LLM_PYTHON_PACKAGE_DIR is not a package dir: {package_dir}")
    spec = importlib.util.find_spec("mlc_llm")
    if spec is not None and spec.submodule_search_locations:
        package_dir = Path(next(iter(spec.submodule_search_locations)))
        if (package_dir / "cli" / "package.py").is_file():
            return package_dir
    candidates = []
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        candidates.append(Path(base) / "mlc_llm")
    for candidate in candidates:
        if (candidate / "cli" / "package.py").is_file():
            return candidate
    raise RuntimeError("Could not locate installed mlc_llm package.")


def main() -> None:
    load_package_model_meta(sys.argv[1:])
    package_dir = find_mlc_llm_package()
    mlc_module = types.ModuleType("mlc_llm")
    mlc_module.__path__ = [str(package_dir)]
    mlc_module.__file__ = str(package_dir / "__init__.py")
    sys.modules["mlc_llm"] = mlc_module
    cli_package = importlib.import_module("mlc_llm.cli.package")
    patch_huggingface_endpoint()
    patch_nested_hf_model_dirs()
    cli_package.main(sys.argv[1:])


def load_package_model_meta(argv) -> None:
    package_config = ""
    for index, arg in enumerate(argv):
        if arg == "--package-config" and index + 1 < len(argv):
            package_config = argv[index + 1]
            break
        if arg.startswith("--package-config="):
            package_config = arg.split("=", 1)[1]
            break
    if not package_config:
        return
    path = Path(package_config)
    if not path.is_file():
        return
    config = json.loads(path.read_text(encoding="utf-8"))
    for entry in config.get("model_list", []):
        if not isinstance(entry, dict):
            continue
        model = str(entry.get("model") or "")
        if not model:
            continue
        meta = {
            "hf_revision": str(entry.get("hf_revision") or ""),
            "model_subdir": str(entry.get("model_subdir") or ""),
        }
        _PACKAGE_MODEL_META[model] = meta
        if model.startswith("HF://"):
            _PACKAGE_MODEL_META[model[len("HF://") :]] = meta


def rewrite_hf_url(url: str) -> str:
    return url.replace("https://huggingface.co", _HF_ENDPOINT)


def mirror_download_file(url, destination, md5sum):
    import requests

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rewritten_url = rewrite_hf_url(url)
    with requests.get(rewritten_url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with destination.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)
    if md5sum is not None:
        hash_md5 = hashlib.md5()
        with destination.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                hash_md5.update(chunk)
        file_md5 = hash_md5.hexdigest()
        if file_md5 != md5sum:
            raise ValueError(
                f"MD5 checksum mismatch for downloaded file: {destination}. "
                f"Expected {md5sum}, got {file_md5}"
            )
    return rewritten_url, destination


def patch_huggingface_endpoint() -> None:
    global _HF_ENDPOINT
    endpoint = os.environ.get("MLC_HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
    _HF_ENDPOINT = endpoint
    if endpoint == "https://huggingface.co":
        return

    download_cache = importlib.import_module("mlc_llm.support.download_cache")
    original_git_clone = download_cache.git_clone

    def git_clone(url, destination, ignore_lfs):
        return original_git_clone(rewrite_hf_url(url), destination, ignore_lfs)

    def git_lfs_pull(repo_dir, ignore_extensions=None):
        import subprocess

        filenames = (
            subprocess.check_output(
                ["git", "-C", str(repo_dir), "lfs", "ls-files", "-n"],
                stderr=subprocess.STDOUT,
            )
            .decode("utf-8")
            .splitlines()
        )
        if ignore_extensions is not None:
            filenames = [
                filename
                for filename in filenames
                if not any(filename.endswith(extension) for extension in ignore_extensions)
            ]
        remote_url = (
            subprocess.check_output(["git", "-C", str(repo_dir), "remote", "get-url", "origin"])
            .decode("utf-8")
            .strip()
        )
        repo = remote_url.replace("https://huggingface.co/", "").replace(endpoint + "/", "")
        repo = repo.removesuffix(".git")
        for filename in filenames:
            url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
            mirror_download_file(url, Path(repo_dir) / filename, None)

    download_cache.git_clone = git_clone
    download_cache.download_file = mirror_download_file
    download_cache.git_lfs_pull = git_lfs_pull


def patch_nested_hf_model_dirs() -> None:
    download_cache = importlib.import_module("mlc_llm.support.download_cache")
    original_get_or_download_model = download_cache.get_or_download_model

    def get_or_download_model(model: str):
        meta = _PACKAGE_MODEL_META.get(model)
        if meta is None and model.startswith("HF://"):
            meta = _PACKAGE_MODEL_META.get(model[len("HF://") :])
        if model.startswith("HF://") and meta and meta.get("model_subdir"):
            return download_nested_hf_model(download_cache, model, meta)
        return original_get_or_download_model(model)

    download_cache.get_or_download_model = get_or_download_model


def download_nested_hf_model(download_cache, model: str, meta: dict) -> Path:
    repo = model[len("HF://") :]
    if repo.count("/") != 1:
        raise ValueError(f"Invalid HF model URL for nested MLC model: {model}")
    user, name = repo.split("/")
    revision = meta.get("hf_revision") or "main"
    subdir = meta["model_subdir"].strip("/")
    cache_dir = download_cache.MLC_LLM_HOME / "model_weights" / "hf" / user / name
    revision_marker = cache_dir / ".mlc_bypass_revision"
    model_dir = cache_dir / subdir
    if (
        model_dir.is_dir()
        and (model_dir / "mlc-chat-config.json").is_file()
        and revision_marker.is_file()
        and revision_marker.read_text(encoding="utf-8").strip() == revision
    ):
        return model_dir

    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_parent = getattr(download_cache, "MLC_TEMP_DIR", None)
    if temp_parent:
        Path(temp_parent).mkdir(parents=True, exist_ok=True)
    temp_kwargs = {"dir": str(temp_parent)} if temp_parent else {}
    with tempfile.TemporaryDirectory(**temp_kwargs) as temp_root:
        checkout = Path(temp_root) / "repo"
        clone_url = f"{_HF_ENDPOINT}/{repo}"
        subprocess.run(["git", "clone", clone_url, str(checkout)], check=True)
        if revision and revision != "main":
            subprocess.run(["git", "-C", str(checkout), "checkout", revision], check=True)
        subprocess.run(["git", "-C", str(checkout), "lfs", "pull"], check=True)
        if not (checkout / subdir / "mlc-chat-config.json").is_file():
            raise FileNotFoundError(
                f"Cannot find nested MLC config {subdir}/mlc-chat-config.json in {model}@{revision}"
            )
        shutil.rmtree(checkout / ".git", ignore_errors=True)
        shutil.move(str(checkout), str(cache_dir))
    revision_marker.write_text(revision + "\n", encoding="utf-8")
    return model_dir


if __name__ == "__main__":
    main()
