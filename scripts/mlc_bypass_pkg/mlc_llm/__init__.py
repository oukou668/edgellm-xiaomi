"""Namespace shim that avoids importing mlc_llm serving modules at startup."""

import site
from pathlib import Path

for base in site.getsitepackages() + [site.getusersitepackages()]:
    candidate = Path(base) / "mlc_llm"
    if (candidate / "cli").is_dir() and str(candidate) not in __path__:
        __path__.append(str(candidate))

