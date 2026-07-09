"""Atalho para levar um anexo permitido para o repositório e publicar a base."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


ALLOWED_EXTENSIONS = {".md", ".txt", ".docx", ".pdf"}
ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("arquivo", type=Path, nargs="?")
    args = parser.parse_args()

    arquivo = None
    if args.arquivo is not None:
        candidato = args.arquivo.expanduser().resolve()
        if candidato.exists() and candidato.suffix.lower() in ALLOWED_EXTENSIONS:
            arquivo = candidato

    if arquivo is None:
        search_roots = [
            ROOT,
            ROOT / "Documentos",
            Path(os.environ.get("USERPROFILE", "")),
            Path(os.environ.get("USERPROFILE", "")) / "Downloads",
            Path(os.environ.get("TEMP", "")),
        ]
        encontrados: list[Path] = []
        for root in search_roots:
            if root and root.exists():
                for item in root.rglob("*"):
                    if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
                        encontrados.append(item)
        if encontrados:
            arquivo = max(encontrados, key=lambda item: item.stat().st_mtime)

    if arquivo is None:
        raise SystemExit("Nenhum anexo compatível foi encontrado. Use um arquivo .md, .txt, .docx ou .pdf.")

    documentos = ROOT / "Documentos"
    documentos.mkdir(exist_ok=True)
    destino = documentos / arquivo.name
    if arquivo.resolve() != destino.resolve():
        shutil.copy2(arquivo, destino)

    subprocess.run(["git", "add", destino.relative_to(ROOT).as_posix()], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"docs: adicionar {destino.name}"], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
