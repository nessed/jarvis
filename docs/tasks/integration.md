# Wave C: integration and webhook handoff

## Ownership

The orchestrator integrates Wave B after all lanes return. Merge all
`docs/tasks/deps-*.txt` exact pins into `requirements.txt`, resolve any
conflicts, and reinstall in `.venv`.

## Objective

Mount the security lane's HMAC verification, webhook handshake, bearer
middleware, JSON logging, and status helper into `bus/main.py`. The WhatsApp
POST webhook must validate its Meta signature and only enqueue through B1's
job client; it never does work inline. Expose executor access to B2's
`route()` entry point. Exercise all suites together and fix interface seams
without weakening authentication, atomic claiming, secret handling, or the
runtime-header/cooldown routing behavior.

Start the bus and a Cloudflare tunnel, collect its HTTPS URL, then navigate to
Meta Developers → app → WhatsApp → Configuration. Fill Callback URL as
`<tunnel>/webhook` and enter the locally held `META_VERIFY_TOKEN`. Stop before
Save: the user reviews and presses Save. Observe the verification handshake
logs with the user. Never reveal the local verify token or read `.env` values.

Commit the integrated Phase 0 work once tests pass and `.env` remains ignored.

## Acceptance handoff

Ask the user to close the lid, message the WhatsApp test line, wake the laptop,
and observe queued → running → done. Ask them to POST `{}` to the webhook
without a signature and expect 403. Ask whether both passed, then stop.
