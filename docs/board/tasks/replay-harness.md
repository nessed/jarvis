---
id: replay-harness
status: ready
lane: AUTO
priority: 1
phase: 0
blocked-on: none
files: tools/replay_job.py, tests/tools/test_replay_job.py
resources: none (offline; live replay claims ollama-embed)
---

# replay-harness — replay real job payloads through real handlers

## Goal

`docs/scalability-review.md` and the blueprint-drift audit both recommend
this into the standard toolkit — it found all three live WhatsApp bugs —
and it still doesn't exist. Build `tools/replay_job.py`: feed a captured
job payload (JSON file or a job id fetched from the queue) through the
**real** handler with only the outbound side faked.

## Steps

1. `build_whatsapp_webhook_handler` already takes its outbound seam as a
   parameter (`executor/handlers/whatsapp.py`) — that is the injection
   point. Fake `send_text_message`/`send_voice_note`/typing-cue with
   printers that show exactly what would have been sent.
2. Input modes: `--payload-file p.json` (offline), `--job-id UUID`
   (fetches the row read-only from the live queue — no claim, no status
   change). Default handler: `whatsapp_webhook`; `--kind` selects others
   as they gain producers.
3. Memory side: default `--no-memory-writes` (recall real, store faked);
   `--memory-writes` opts in. Real recall touches Ollama embeds — note the
   resource in `--help`.
4. Print the full decision trail: dedup verdict, recall hits, routed
   provider, reply text. UTF-8 explicit on stdout (cp1252 machine).
5. Tests against fakes, mirroring `tests/tools/test_run_backfill.py`'s
   pattern for CLI coverage.

## Verification

Full offline suite green; a replay of a synthetic voice-note payload and a
text payload each print a correct trail with sends faked (cite output).

## Done when

Tool + tests landed, `docs/state.md` process-tooling row mentions it.

## Log

_(empty)_
