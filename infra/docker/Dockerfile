# The bus + router, and nothing else.
#
# Built for linux/arm64: the target is an Oracle Ampere A1. Building this on an
# x86 laptop needs `docker buildx build --platform linux/arm64`, or it silently
# produces an image the VPS cannot run. The runbook says so at the step where
# it matters.
FROM python:3.12-slim-bookworm AS base

# ---------------------------------------------------------------------------
# Why this image installs six packages and not requirements.txt
#
# The repo's requirements.txt carries the whole laptop stack -- torch,
# torchaudio, kokoro, openwakeword, pipecat, sounddevice, pyflp, psutil,
# pywinauto. None of it is importable from bus/, router/ or db/ (checked: no
# import in those packages reaches any of it), all of it is executor-side, and
# torch alone is over a gigabyte. On a 12 GB Always Free box with a 100 GB boot
# volume that is not a rounding error.
#
# The cost of this choice is a second list that can drift from requirements.txt.
# That is why the versions below are pinned to exactly the lines
# requirements.txt already pins, and why bus-offbox-packaging is the task that
# should replace this with a proper extras split rather than a copy.
# ---------------------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY infra/docker/requirements-bus.txt /tmp/requirements-bus.txt
RUN pip install --no-cache-dir -r /tmp/requirements-bus.txt

# Only the three packages the bus actually runs on. Copying the whole repo
# would drag voice/, the 3 GB whisper build tree and Ali's wake-word clips into
# an image that goes on a public-ish host. .dockerignore is the second guard.
COPY bus/ /app/bus/
COPY router/ /app/router/
COPY db/ /app/db/

# Writable state: the webhook dedup sqlite file. Mounted as a volume in
# compose so a redeploy does not make Meta's redeliveries look new again.
RUN mkdir -p /app/state && useradd --create-home --uid 10001 jarvis \
    && chown -R jarvis:jarvis /app
USER jarvis

ENV JARVIS_WEBHOOK_DEDUP_DB_PATH=/app/state/webhook.seen-messages.db

EXPOSE 8000

# No --reload, one worker. The bus's job is to verify, enqueue and return in
# milliseconds; concurrency lives in the executor, and a second worker would
# mean two processes racing on the same dedup sqlite file.
CMD ["uvicorn", "bus.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
