r"""Phase 4 baseline probe: how long one real text reply actually takes.

This does not assert a threshold. It **records** one. Every task in the
September latency batch claims to make the reply path faster, and the number
they are all measured against has to come from the real path — real queue,
real recall, real provider, real Graph API send — not from a unit test with
the slow parts faked out. Turning the recorded numbers into pass/fail
assertions is `live-latency-acceptance`, which is gated on Q17-D13; do not add
a threshold here.

Run it explicitly (the default suite excludes ``live``):

    .venv\Scripts\python.exe -m pytest -q -m live tests/live/test_text_reply_latency.py -s

Requires, all at once:

- the stack up (``.venv\Scripts\python.exe tools/start_jarvis.py``), or at
  minimum the ``whatsapp-worker`` poller plus loopback Ollama;
- ``JARVIS_LIVE_WHATSAPP_TO`` set to a number on the Meta app's test-recipient
  allow-list. It is deliberately not stored in the repo: a phone number is
  personal data and this file is committed.

**It sends one real WhatsApp message.** The probe enqueues a
``whatsapp_webhook`` job as if that number had messaged the bot, so the reply
goes back to that number for real. The text is synthetic — no personal
content is used to measure latency.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest

from tools.reply_latency import parse_line

ROOT = Path(__file__).resolve().parents[2]
WORKER_LOG = ROOT / "tools" / "whatsapp-worker.out.log"

RECIPIENT_ENV = "JARVIS_LIVE_WHATSAPP_TO"

# A question with an answer, so the model produces a normal-length reply
# rather than a one-word acknowledgement that would flatter the model stage.
PROBE_TEXT = "In one sentence, what is the boiling point of water at sea level?"

# The 4 Sep audit measured ~10 s for a text reply. 180 s is not a threshold;
# it is the point past which the probe has clearly not been picked up at all.
REPLY_TIMEOUT_SECONDS = 180
POLL_SECONDS = 2.0

# If the worker log has not been written to in this long, nothing is polling
# the queue and the probe would enqueue a job that sits there until someone
# starts the stack.
WORKER_IDLE_SECONDS = 300


def _probe_payload(sender: str, message_id: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": sender,
                                    "id": message_id,
                                    "type": "text",
                                    "text": {"body": PROBE_TEXT},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def _latency_line(job_id: str) -> str | None:
    if not WORKER_LOG.exists():
        return None
    with WORKER_LOG.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "reply-latency" in line and f"job={job_id}" in line:
                return line.strip()
    return None


@pytest.mark.live
def test_one_real_text_reply_reports_its_stages(record_property) -> None:
    recipient = os.environ.get(RECIPIENT_ENV, "").strip()
    if not recipient:
        pytest.skip(
            f"{RECIPIENT_ENV} is not set. It must be a number on the Meta app's "
            "test-recipient allow-list; it is not stored in the repo on purpose."
        )
    if not WORKER_LOG.exists() or time.time() - WORKER_LOG.stat().st_mtime > WORKER_IDLE_SECONDS:
        pytest.skip(
            f"{WORKER_LOG.name} has not been written to in {WORKER_IDLE_SECONDS}s — "
            "the whatsapp worker is not running, so the probe job would never be claimed."
        )

    from db.jobs import enqueue

    message_id = f"wamid.latency-probe.{uuid.uuid4().hex[:12]}"
    job = enqueue("whatsapp_webhook", _probe_payload(recipient, message_id))

    deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
    line = None
    while time.monotonic() < deadline:
        line = _latency_line(job.id)
        if line is not None:
            break
        time.sleep(POLL_SECONDS)

    assert line is not None, (
        f"no reply-latency line for job {job.id} within {REPLY_TIMEOUT_SECONDS}s. "
        f"Check {WORKER_LOG} for what the handler did instead."
    )

    record = parse_line(line)
    assert record is not None, f"the latency line did not parse: {line!r}"

    for stage, milliseconds in sorted(record.items()):
        if isinstance(milliseconds, int):
            record_property(f"reply_latency_{stage}_ms", milliseconds)
    record_property("reply_latency_line", line)

    # Printed, not asserted. This is the baseline every later task in the
    # batch is compared against, and it belongs in the run's output where a
    # log entry can be quoted into a task's Log.
    print(f"\nBASELINE {line}")
    for stage, milliseconds in record.items():
        if isinstance(milliseconds, int):
            print(f"  {stage:<12}{milliseconds / 1000:.2f}s")
