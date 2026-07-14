"""Inicializador local: abre o navegador assim que o servidor responder ao health check."""

from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser

import uvicorn


HOST = "127.0.0.1"
PREFERRED_PORT = 8000


def find_available_port() -> int:
    for port in range(PREFERRED_PORT, PREFERRED_PORT + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            try:
                connection.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError("Nenhuma porta local disponível foi encontrada para iniciar o MAGISTERIA.")


def open_browser_soon(app_url: str, delay: float = 1.0) -> None:
    time.sleep(delay)
    if os.getenv("MAGISTERIA_NO_BROWSER") != "1":
        webbrowser.open(app_url)


def main() -> None:
    port = find_available_port()
    app_url = f"http://{HOST}:{port}"
    browser_thread = threading.Thread(target=open_browser_soon, args=(app_url,), daemon=True)
    browser_thread.start()
    uvicorn.run("app:app", host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
