"""Bypass entrypoint for MLC LLM subcommands."""

import importlib
import sys


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m mlc_llm <subcommand> [args...]")
    subcommand = sys.argv[1]
    module = importlib.import_module(f"mlc_llm.cli.{subcommand}")
    module.main(sys.argv[2:])


if __name__ == "__main__":
    main()

