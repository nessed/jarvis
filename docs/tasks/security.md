# Wave B3: bus security primitives

## Ownership

Only edit `bus/security.py`, `bus/logging.py`, `bus/status.py`,
`tests/security/`, and `docs/tasks/deps-security.txt`. Do not touch
`bus/main.py`, commit, or modify other paths.

## Objective

Export clean functions, route helpers, and middleware that the integration lane
can mount. Implement HMAC-SHA256 validation for Meta `X-Hub-Signature-256`
using `META_APP_SECRET`, always comparing with `hmac.compare_digest`; an absent
or malformed/bad signature must become 403 and emit a structured log line.
Provide a GET webhook verification handler that compares `hub.verify_token` to
`META_VERIFY_TOKEN` safely and echoes `hub.challenge` when valid.

Provide bearer authentication middleware for every non-webhook route based on
`BUS_BEARER_TOKEN`; unauthorized access receives 401. Provide JSON-lines
structured logging with one request ID on every line. Implement a `/status`
helper response containing queue depth by status, the last job, and per-provider
health. It must receive dependencies/callables rather than hard-wire the final
app or external service.

Write tests for a valid signature, bad signature/403, absent signature/403,
unauthed status/401, and successful handshake challenge echo. Do not print or
log any secrets. Add needed dependencies only to `docs/tasks/deps-security.txt`.
