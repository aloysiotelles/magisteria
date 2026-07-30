from __future__ import annotations

import asyncio
import base64
from email.message import EmailMessage
import html
import time
from urllib.parse import quote

import httpx


class GmailAPIError(RuntimeError):
    """Falha de autenticação ou entrega pela API oficial do Gmail."""


class EmailService:
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        sender_email: str,
        public_url: str,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.refresh_token = refresh_token.strip()
        self.sender_email = sender_email.strip()
        self.public_url = public_url.strip().rstrip("/")
        self._access_token = ""
        self._access_token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return all((
            self.client_id,
            self.client_secret,
            self.refresh_token,
            self.sender_email,
            self.public_url,
        ))

    async def _get_access_token(self) -> str:
        if self._access_token and time.monotonic() < self._access_token_expires_at:
            return self._access_token
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._access_token_expires_at:
                return self._access_token
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    self.TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": self.refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            if response.is_error:
                raise GmailAPIError(f"Falha ao renovar a autorizacao do Gmail ({response.status_code}).")
            payload = response.json()
            self._access_token = str(payload.get("access_token") or "")
            if not self._access_token:
                raise GmailAPIError("O Google nao retornou um token de acesso do Gmail.")
            expires_in = max(60, int(payload.get("expires_in") or 3600))
            self._access_token_expires_at = time.monotonic() + expires_in - 60
            return self._access_token

    async def send_password_reset(self, full_name: str, recipient: str, token: str) -> None:
        if not self.configured:
            raise GmailAPIError("O envio de email ainda nao esta configurado.")
        reset_url = f"{self.public_url}/redefinir-senha?token={quote(token, safe='')}"
        message = EmailMessage()
        message["To"] = recipient.strip()
        message["From"] = f"MAGISTERIA <{self.sender_email}>"
        message["Reply-To"] = self.sender_email
        message["Subject"] = "Redefina sua senha do MAGISTERIA"
        message.set_content(
            f"Ola, {full_name.strip()}!\n\n"
            "Recebemos um pedido para redefinir sua senha. Este link expira em 30 minutos:\n"
            f"{reset_url}\n\n"
            "Se voce nao solicitou a alteracao, ignore esta mensagem."
        )
        safe_name = html.escape(full_name.strip())
        safe_url = html.escape(reset_url, quote=True)
        message.add_alternative(
            f"<p>Olá, <strong>{safe_name}</strong>!</p>"
            "<p>Recebemos um pedido para redefinir sua senha.</p>"
            f'<p><a href="{safe_url}">Criar uma nova senha</a></p>'
            "<p>O link expira em 30 minutos. Se você não solicitou a alteração, ignore esta mensagem.</p>",
            subtype="html",
        )
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        access_token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                self.SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": encoded},
            )
        if response.is_error:
            raise GmailAPIError(f"O Gmail recusou o envio da mensagem ({response.status_code}).")
