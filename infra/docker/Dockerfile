# The brain: bus + router + conversation service + memory, on linux/amd64.
#
# Rewritten by bus-offbox-packaging (9 Sep 2026). The target moved from an
# Oracle Ampere A1 (arm64) to a rented x86 box (U17), and the image itself
# grew from "webhook that enqueues" to "webhook that can actually answer" --
# conversation-inline-reply means the bus now runs ConversationService
# in-process, which needs memory/ (recall + remember) and the slice of
# executor/ that service imports. No buildx platform flag is needed for the
# common case (building on the x86 box itself, or in x86 CI); the explicit
# --platform pin below is only insurance against someone building this on an
# arm64 laptop by habit, left over from the Oracle era.
FROM --platform=linux/amd64 python:3.12-slim-bookworm AS base

# ---------------------------------------------------------------------------
# Why this image installs requirements-brain.txt and not requirements.txt
#
# The repo's requirements.txt carries the whole laptop stack -- torch,
# torchaudio, kokoro, openwakeword, pipecat, sounddevice, pyflp, psutil,
# pywinauto. None of it is importable from anything this image copies
# (tests/infra/test_image_contents.py greps every copied file for those
# imports and fails the offline suite if one appears), all of it is
# executor-side, and torch alone is over a gigabyte -- real weight on a 2 GB
# box that also runs the ollama sidecar.
#
# The cost of this choice is a second list that can drift from
# requirements.txt. That is why every version below is pinned to exactly the
# line requirements.txt already pins for it, and why that file is the one to
# diff against when either changes.
# ---------------------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY infra/docker/requirements-brain.txt /tmp/requirements-brain.txt
RUN pip install --no-cache-dir -r /tmp/requirements-brain.txt

# Selective copies, not `COPY executor/`: the service uses a handful of
# executor modules (classify/enqueue-shape/latency/notify) and nothing else
# in that package should ride along -- flp/, system_control/, voice-adjacent
# handlers and their heavier imports stay off the box entirely rather than
# depending on nobody calling them. .dockerignore is the second guard, for
# everything not listed here at all (voice/, tests/, .venv/, ...).
COPY bus/ /app/bus/
COPY router/ /app/router/
COPY db/ /app/db/
COPY memory/ /app/memory/
COPY executor/__init__.py /app/executor/__init__.py
COPY executor/latency.py /app/executor/latency.py
COPY executor/notify.py /app/executor/notify.py
COPY executor/conversation/ /app/executor/conversation/
COPY executor/handlers/__init__.py /app/executor/handlers/__init__.py
COPY executor/handlers/command_intent.py /app/executor/handlers/command_intent.py
COPY executor/handlers/outcome.py /app/executor/handlers/outcome.py
COPY executor/handlers/whatsapp.py /app/executor/handlers/whatsapp.py

# Writable state: the webhook dedup sqlite file, the conversation memory
# database (sqlite + sqlite-vec), and the pending-confirmations sqlite file
# `command_intent.py` derives from the same MEMORY_DB_PATH. All three live
# under one directory so one volume (`brain-state` in compose.yaml) covers
# them; losing any of them on redeploy means either Meta's redeliveries look
# new again or Ali's memory resets, not a crash.
RUN mkdir -p /app/state && useradd --create-home --uid 10001 jarvis \
    && chown -R jarvis:jarvis /app
USER jarvis

ENV JARVIS_WEBHOOK_DEDUP_DB_PATH=/app/state/webhook.seen-messages.db \
    MEMORY_DB_PATH=/app/state/memory.db

EXPOSE 8000

# No --reload, one worker. Recall/remember now run inside this process
# (conversation-inline-reply), against sqlite handles opened per request --
# a second worker would mean two processes racing on the same memory and
# dedup sqlite files, the same reason the old enqueue-only image pinned one.
CMD ["uvicorn", "bus.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
