"""Inicializador local: aguarda o servidor ficar pronto antes de abrir o navegador."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import uvicorn


EXPECTED_VERSION = "0.5.1"
HOST = "127.0.0.1"
PREFERRED_PORT = 8000


def read_json(url: str) -> dict | None:
    try:
        with urlopen(url, timeout=1) as response:
            return json.loads(response.read().decode("utf-8")) if response.status == 200 else None
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def app_is_ready(app_url: str) -> bool:
    status = read_json(f"{app_url}/status")
    version = read_json(f"{app_url}/versao")
    return bool(
        status
        and "documentos" in status
        and "trechos" in status
        and version
        and version.get("versao") == EXPECTED_VERSION
    )


def find_available_port() -> int:
    for port in range(PREFERRED_PORT, PREFERRED_PORT + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            try:
                connection.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError("Nenhuma porta local disponível foi encontrada para iniciar o MAGISTERIA.")


def open_browser_when_ready(app_url: str, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app_is_ready(app_url):
            if os.getenv("MAGISTERIA_NO_BROWSER") != "1":
                webbrowser.open(app_url)
            return
        time.sleep(0.4)


def main() -> None:
    preferred_url = f"http://{HOST}:{PREFERRED_PORT}"
    # Uma segunda execução abre a instância atual somente se ela tiver a mesma versão.
    if app_is_ready(preferred_url):
        if os.getenv("MAGISTERIA_NO_BROWSER") != "1":
            webbrowser.open(preferred_url)
        return

    port = find_available_port()
    app_url = f"http://{HOST}:{port}"
    browser_thread = threading.Thread(target=open_browser_when_ready, args=(app_url,), daemon=True)
    browser_thread.start()
    uvicorn.run("app:app", host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()
