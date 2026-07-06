"""Envia a base documental local ao Volume do MAGISTERIA em blocos."""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import build_opener, HTTPCookieProcessor, Request


CHUNK_SIZE = 4 * 1024 * 1024


def request(opener, url: str, *, data: bytes = b"", headers: dict | None = None):
    try:
        with opener.open(Request(url, data=data, headers=headers or {}), timeout=120) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Falha HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://magisteria-production.up.railway.app")
    parser.add_argument("--senha", default="DIVINA")
    parser.add_argument("--documentos", type=Path, default=Path(__file__).parent / "Documentos")
    args = parser.parse_args()
    base_url = args.url.rstrip("/")
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    for attempt in range(36):
        try:
            request(
                opener,
                f"{base_url}/login",
                data=urlencode({"senha": args.senha}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            break
        except RuntimeError:
            if attempt == 35:
                raise
            print("Aguardando o novo deploy ficar disponivel...")
            time.sleep(10)
    files = sorted(
        path for path in args.documentos.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pdf", ".docx", ".txt"}
    )
    print(f"Enviando {len(files)} documentos...")
    for position, path in enumerate(files, 1):
        offset = 0
        size = path.stat().st_size
        with path.open("rb") as source:
            while chunk := source.read(CHUNK_SIZE):
                complete = offset + len(chunk) == size
                result = request(
                    opener,
                    f"{base_url}/admin/upload-chunk",
                    data=chunk,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "X-Filename": quote(path.name),
                        "X-Offset": str(offset),
                        "X-Complete": "1" if complete else "0",
                    },
                )
                offset += len(chunk)
        print(f"[{position}/{len(files)}] {path.name} ({offset / 1024 / 1024:.1f} MB)")
    result = json.loads(request(opener, f"{base_url}/indexar", data=b"{}", headers={"Content-Type": "application/json"}))
    print(f"Base atualizada: {result['status']['documentos']} documentos, {result['status']['trechos']} trechos.")


if __name__ == "__main__":
    main()
