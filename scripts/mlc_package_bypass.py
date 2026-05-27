#!/usr/bin/env python3
"""Run MLC LLM package while bypassing the top-level mlc_llm import.

The current macOS arm64 nightly wheel imports serving modules from
``mlc_llm.__init__`` and can fail before the packaging CLI is reached when
native runtime libraries are mismatched. The package command itself can be
loaded by treating the installed ``mlc_llm`` directory as a namespace package.
"""

import importlib
import hashlib
import os
import site
import sys
import types
from pathlib import Path

_HF_ENDPOINT = "https://hf-mirror.com"


def find_mlc_llm_package() -> Path:
    candidates = []
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        candidates.append(Path(base) / "mlc_llm")
    for candidate in candidates:
        if (candidate / "cli" / "package.py").is_file():
            return candidate
    raise RuntimeError("Could not locate installed mlc_llm package.")


def main() -> None:
    package_dir = find_mlc_llm_package()
    mlc_module = types.ModuleType("mlc_llm")
    mlc_module.__path__ = [str(package_dir)]
    mlc_module.__file__ = str(package_dir / "__init__.py")
    sys.modules["mlc_llm"] = mlc_module
    cli_package = importlib.import_module("mlc_llm.cli.package")
    patch_huggingface_endpoint()
    cli_package.main(sys.argv[1:])


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


if __name__ == "__main__":
    main()
