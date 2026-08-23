# JARVIS

Local executor and durable command bus for a personal assistant. Phase 0 builds
the protected FastAPI webhook, queue, and provider routing foundation.

## Local start

1. Create and activate `.venv`.
2. Install `requirements.txt`.
3. Copy `.env.example` to `.env` and fill provider and service values locally.
4. Run `uvicorn bus.main:app --reload`.

The only initial public route is `GET /health`.
