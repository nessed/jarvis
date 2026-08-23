"""Initial FastAPI application; Phase 0 integration adds protected routes."""

from fastapi import FastAPI

app = FastAPI(title="JARVIS bus")


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a minimal liveness response."""
    return {"status": "ok"}
