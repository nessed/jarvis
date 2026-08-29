"""Outbound WhatsApp Cloud API client — the only place access tokens are used."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

import httpx

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE_URL = "https://graph.facebook.com"

# WhatsApp plays OGG/Opus inline as a voice note. Other audio types arrive
# as file attachments instead, so this is load-bearing, not a default.
VOICE_NOTE_MIME_TYPE = "audio/ogg"


class WhatsAppSendError(RuntimeError):
    """Raised when an outbound WhatsApp message cannot be sent."""


@dataclass(frozen=True)
class WhatsAppClientConfig:
    """Explicit configuration for sending through Meta's WhatsApp Cloud API."""

    phone_number_id: str
    access_token: str
    base_url: str = GRAPH_API_BASE_URL
    timeout_seconds: float = 10.0
    # A multipart audio upload is a bigger request than a text POST and
    # 10s is tight for it on this network.
    media_timeout_seconds: float = 30.0

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

    def show_typing_indicator(self, *, message_id: str) -> None:
        """Mark an inbound message read and show WhatsApp's native typing cue.

        Cloud API combines the read receipt and typing indicator in one status
        request. The indicator dismisses itself once a reply is sent (or after
        Meta's short display window), so callers should invoke this only while
        preparing a reply to the supplied inbound message.
        """
        inbound_message_id = message_id.strip()
        if not inbound_message_id:
            raise WhatsAppSendError("Inbound WhatsApp message id is required for a typing indicator.")

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": inbound_message_id,
            "typing_indicator": {"type": "text"},
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
            raise WhatsAppSendError("WhatsApp typing indicator timed out. Confirm the Graph API is reachable.") from exc
        except httpx.ConnectError as exc:
            raise WhatsAppSendError("WhatsApp typing indicator failed: could not reach the Graph API.") from exc
        except httpx.HTTPStatusError as exc:
            raise WhatsAppSendError(
                f"WhatsApp typing indicator failed with HTTP {exc.response.status_code}: "
                f"{_safe_error_summary(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise WhatsAppSendError("WhatsApp typing indicator failed. Confirm the Graph API is reachable.") from exc

        try:
            if response.json()["success"] is True:
                return
        except (KeyError, TypeError, ValueError):
            pass
        raise WhatsAppSendError("WhatsApp typing indicator returned an unexpected response shape.")


    def upload_media(self, *, content: bytes, mime_type: str, filename: str) -> str:
        """Upload media to Meta and return the reusable media id.

        Sending audio is two calls, not one: media is uploaded to
        ``POST /{phone_number_id}/media`` first, and the id it returns is what
        the message references. Meta holds an uploaded asset for 30 days, so a
        caller that sends the same clip twice should reuse the id rather than
        upload again.

        This is a multipart form post, not JSON, which is why it does not share
        the request body shape of the other methods here.
        """
        if not content:
            raise WhatsAppSendError("Media upload requires non-empty content.")
        if not mime_type.strip():
            raise WhatsAppSendError("Media upload requires a MIME type.")

        try:
            with httpx.Client(
                base_url=self._config.base_url.rstrip("/"),
                timeout=httpx.Timeout(self._config.media_timeout_seconds),
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"/{GRAPH_API_VERSION}/{self._config.phone_number_id}/media",
                    files={"file": (filename, content, mime_type)},
                    data={"messaging_product": "whatsapp", "type": mime_type},
                    headers={"Authorization": f"Bearer {self._config.access_token}"},
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise WhatsAppSendError(
                "WhatsApp media upload timed out. Confirm the Graph API is reachable."
            ) from exc
        except httpx.ConnectError as exc:
            raise WhatsAppSendError(
                "WhatsApp media upload failed: could not reach the Graph API."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise WhatsAppSendError(
                f"WhatsApp media upload failed with HTTP {exc.response.status_code}: "
                f"{_safe_error_summary(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(
                "WhatsApp media upload failed. Confirm the Graph API is reachable."
            ) from exc

        try:
            media_id = response.json()["id"]
        except (KeyError, TypeError, ValueError) as exc:
            raise WhatsAppSendError(
                "WhatsApp media upload returned an unexpected response shape."
            ) from exc
        if not media_id:
            raise WhatsAppSendError("WhatsApp media upload returned an empty media id.")
        return media_id

    def send_voice_note(self, *, to: str, audio: bytes, filename: str = "reply.ogg") -> str:
        """Upload OGG/Opus audio and send it as a playable voice note.

        ``audio`` must be OGG/Opus. WhatsApp renders that inline with a waveform
        and a play button; other audio formats arrive as a file attachment
        instead, which is a different and worse thing. ``voice/speak.py``
        produces the right format.
        """
        recipient = to.strip()
        if not recipient:
            raise WhatsAppSendError("Recipient phone number is required.")

        media_id = self.upload_media(
            content=audio, mime_type=VOICE_NOTE_MIME_TYPE, filename=filename
        )

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "audio",
            # `voice: True` is what makes it render as a voice note rather than
            # an audio file attachment.
            "audio": {"id": media_id, "voice": True},
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
            raise WhatsAppSendError(
                "WhatsApp voice note timed out. Confirm the Graph API is reachable."
            ) from exc
        except httpx.ConnectError as exc:
            raise WhatsAppSendError(
                "WhatsApp voice note failed: could not reach the Graph API."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise WhatsAppSendError(
                f"WhatsApp voice note failed with HTTP {exc.response.status_code}: "
                f"{_safe_error_summary(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(
                "WhatsApp voice note failed. Confirm the Graph API is reachable."
            ) from exc

        data = response.json()
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError, TypeError) as exc:
            raise WhatsAppSendError(
                "WhatsApp voice note returned an unexpected response shape."
            ) from exc


def _safe_error_summary(response: httpx.Response) -> str:
    """Surface Graph API's own error code/message only — never the request body or token."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return "non-JSON error body"
    return f"code={error.get('code')} message={error.get('message')}"
