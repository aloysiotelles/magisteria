"""Atalho para publicar o aplicativo via GitHub e Railway."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", "deploy: atualizar app"])
    run(["git", "push", "origin", "HEAD"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
