"""Outbound WhatsApp Cloud API client — the only place access tokens are used."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

import httpx

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE_URL = "https://graph.facebook.com"


class WhatsAppSendError(RuntimeError):
    """Raised when an outbound WhatsApp message cannot be sent."""


@dataclass(frozen=True)
class WhatsAppClientConfig:
    """Explicit configuration for sending through Meta's WhatsApp Cloud API."""

    phone_number_id: str
    access_token: str
    base_url: str = GRAPH_API_BASE_URL
    timeout_seconds: float = 10.0

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "WhatsAppClientConfig":
        settings = os.environ if environ is None else environ
        phone_number_id = settings.get("META_PHONE_NUMBER_ID", "").strip()
        access_token = settings.get("META_ACCESS_TOKEN", "").strip()
        if not phone_number_id or not access_token:
            raise WhatsAppSendError(
                "Outbound WhatsApp is not configured: set META_PHONE_NUMBER_ID and META_ACCESS_TOKEN."
            )
        return cls(phone_number_id=phone_number_id, access_token=access_token)


class WhatsAppClient:
    """Synchronous adapter for Meta's ``POST /{phone_number_id}/messages`` endpoint."""

    def __init__(self, config: WhatsAppClientConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self._config = config
        self._transport = transport

    def send_text_message(self, *, to: str, text: str) -> str:
        """Send a text message and return the provider-assigned message id."""
        recipient = to.strip()
        if not recipient:
            raise WhatsAppSendError("Recipient phone number is required.")
        if not text.strip():
            raise WhatsAppSendError("Message text must not be empty.")

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": text},
        }
        try:
            with httpx.Client(
                base_url=self._config.base_url.rstrip("/"),
                timeout=httpx.Timeout(self._config.timeout_seconds),
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"/{GRAPH_API_VERSION}/{self._config.phone_number_id}/messages",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._config.access_token}"},
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise WhatsAppSendError("WhatsApp send timed out. Confirm the Graph API is reachable.") from exc
        except httpx.ConnectError as exc:
            raise WhatsAppSendError("WhatsApp send failed: could not reach the Graph API.") from exc
        except httpx.HTTPStatusError as exc:
            raise WhatsAppSendError(
                f"WhatsApp send failed with HTTP {exc.response.status_code}: {_safe_error_summary(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise WhatsAppSendError("WhatsApp send failed. Confirm the Graph API is reachable.") from exc

        data = response.json()
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError, TypeError) as exc:
            raise WhatsAppSendError("WhatsApp send returned an unexpected response shape.") from exc


def _safe_error_summary(response: httpx.Response) -> str:
    """Surface Graph API's own error code/message only — never the request body or token."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return "non-JSON error body"
    return f"code={error.get('code')} message={error.get('message')}"
