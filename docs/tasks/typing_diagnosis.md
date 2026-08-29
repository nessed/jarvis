# WhatsApp typing-indicator diagnosis

## Scope

Find why the native WhatsApp typing cue is not visible after an inbound
message, using the existing Meta Cloud API client and webhook handler. Verify
the current official Meta request contract and inspect local code, tests, and
safe logs. Correct only an evidenced implementation defect.

## Relevant design

`bus/whatsapp_client.py` sends the Graph API status update. The webhook handler
must issue it before slow reply routing, without making a Graph feedback
failure block the actual text reply. Meta ties the cue to the inbound WhatsApp
message ID; no alternate provider or client is in scope.

## Owned paths

- `bus/whatsapp_client.py`
- `executor/handlers/whatsapp.py`
- typing-focused tests under `tests/bus/` and `tests/executor/`
- `docs/state.md`

## Acceptance

The emitted request agrees with current official Meta documentation, is made
early enough to be observable, remains best-effort, and is covered by focused
tests. A live visual check remains the user's confirmation.

## Result

The source request matches Meta's current documented `POST /messages` typing
and read-receipt payload. No source defect was found. The active executor was
started before this source was written: its log last updated at 17:25 on 29 Aug
2026, while the client, handler, and tests were modified at 17:42. It must be
restarted to load the feature; then send a new inbound text and verify the
typing cue before the reply arrives.

## Runtime remediation

The project launcher started a fresh http2 Quick Tunnel and bus. Meta's
read-back callback is the new tunnel URL, and Meta's verification handshake
reached the fresh bus. The executor log was recreated after startup, so it
imports the typing-indicator source written beforehand. Local and public DNS
lookups for the Quick Tunnel timed out on this network; the verified Meta
callback and its successful handshake are the authoritative deployment check.
