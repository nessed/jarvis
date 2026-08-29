# WhatsApp native typing indicator

## Scope

Add WhatsApp Cloud API's native animated typing indicator to the existing
`whatsapp_webhook` reply flow. Do not send a text placeholder and do not add a
dependency.

## Provider contract verified

Meta's official WhatsApp Cloud API collection documents a `POST` to the
existing `/{phone-number-id}/messages` endpoint with the inbound
`message_id`, `status: "read"`, and `typing_indicator: {"type": "text"}`.
The response is `{"success": true}`. It is a combined read receipt and
typing indicator; WhatsApp dismisses it on a reply or after 25 seconds.

## Implementation

1. Add a `WhatsAppClient` method that posts the documented status payload,
   validates the inbound message id, and keeps errors token-safe.
2. Invoke it best-effort after recall and immediately before routing, using the
   inbound Meta message ID. A failed visual cue must never prevent a real
   reply or cause a job retry.
3. Cover the exact API payload and handler ordering/failure behavior with
   offline tests.

## Owned paths

- `bus/whatsapp_client.py`
- `executor/handlers/whatsapp.py`
- `tests/bus/test_whatsapp_client.py`
- `tests/executor/test_whatsapp_handler.py`
- `docs/state.md`

