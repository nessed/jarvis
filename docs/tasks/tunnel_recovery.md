# Tunnel recovery lane

## Ownership

Own only this brief. Do not edit repository source, context, requirements, or
other task files. Do not commit.

## Task

Read-only diagnose the currently running Cloudflare Quick Tunnel and FastAPI
listener. Report whether the tunnel has a healthy Cloudflare connection, which
local port FastAPI is listening on, and the exact safe recovery sequence needed
to replace the failed Quick Tunnel. Do not print environment values or tokens.
Do not restart or stop any process: the orchestrator will do that.

## Context

The prior Quick Tunnel callback was set to a Meta WhatsApp webhook. Its log now
shows repeated Cloudflare control-stream failures. A replacement must target
the existing local FastAPI bus and will require one later user Meta Save click.
