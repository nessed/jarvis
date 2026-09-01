---
id: replay-harness
status: done
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

**2 Sep 2026 — done.**

`tools/replay_job.py` + `tests/tools/test_replay_job.py`. The real handler
runs; only what leaves the machine or mutates durable state is faked.

Two refusals were added beyond the Steps, both load-bearing:

- **A replay never marks a message as sent.** `mark_sent` is a no-op. Without
  that, replaying a real message would teach the live executor to skip it.
- **Dedup is reported, then bypassed.** The interesting replay is almost
  always of a message that *already* got a reply — that is what reproducing a
  bug means here — and honouring dedup would make the handler return
  immediately and print nothing. `--respect-dedup` restores production
  behaviour, and the trail states which happened.

Step 2's `--kind` is parsed but refuses twice, on purpose: without
`--allow-side-effects` because those handlers have no fakeable outbound seam
and would really move files or drive apps, and then again because they are not
wired. Consent is not capability, and the second message says which.

### Offline suite

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp
1023 passed, 9 deselected, 2 warnings in 54.96s
```

993 before this task; +30 tests here.

### Text payload, real recall and real routing

Ollama was not running, so it was started first
(`ollama serve`); `ollama-embed` was claimed for the duration and released
after. Synthetic payload, `wamid.REPLAY-TEXT-1`:

```
job        replay-from-file  (whatsapp_webhook)
dedup      not seen before
typing     cue sent (faked)
recall     10 hit(s) for 'what is my name'
           - User asked for the assistant's name on August 29, 2026
           - Assistant confirmed that the user is Ali
           - Assistant's name is JARVIS
           ...
routed     openrouter / openrouter/free
reply      'Your name is Ali.'
send       text to 923001234567 -- faked, nothing left this machine
remember   user: 'what is my name' -- dropped (--memory-writes to store)
remember   assistant: 'Your name is Ali.' -- dropped (--memory-writes to store)
```

Recall, routing and the reply are real. The send is not.

### Voice payload

`--audio-file` stands in for the Graph API download, `--transcript` for
whisper-server (which was not running; the NPU is never needed by this tool):

```
job        replay-from-file  (whatsapp_webhook)
dedup      not seen before
typing     cue sent (faked)
media      1102 bytes from --audio-file
transcript 'mera naam kya hai'
recall     10 hit(s) for 'mera naam kya hai'
           - Ali is a 19-year-old Shia Muslim who lives in DHA Phase 3, Lahore...
           - Ali is 19 years old
           ...
routed     openrouter / openrouter/free
reply      "I don't know your name."
send       voice note to 923001234567 -- faked, nothing left this machine
```

### It found something on its first real run

That voice trail is a discrepancy, not a clean pass. Recall returned ten hits
naming Ali repeatedly, and the reply was *"I don't know your name."* The same
question over the text path, one minute earlier, answered *"Your name is
Ali."* The two runs differ in exactly one thing: the voice path appends
`VOICE_REPLY_LANGUAGE_NOTE` to the system prompt, and the query was Roman Urdu
rather than English.

Not chased here — `executor/handlers/whatsapp.py` is claimed by the
`enqueue-classifier` lane, and this task does not own it. Raised for the
board; this is the class of bug the harness exists to make visible.

### Scope note: `db/jobs.py` wants a public single-row read

`--job-id` needs one read-only `SELECT`. `db/jobs.py` has no public one —
`status_of_job` returns only the status column and everything else mutates —
so `SupabaseJobSource.from_env` goes through the repository's client. The
query is a plain select and cannot claim, complete or fail anything.
A public `fetch_job` on `SupabaseJobsRepository` is the better home;
`db/jobs.py` is not in this task's `files:` and was not edited.

### Specified but not done

`docs/state.md`'s process-tooling row. `docs/state.md` was claimed by the
`enqueue-classifier` lane for the whole of this task; the row is one line and
is handed to whoever holds it next.

### Addendum, same day — the classifier call

`enqueue-classifier` landed mid-task and put a command-classifier completion
in front of the reply completion, through the same injected seam. Two
consequences, both handled here:

- `tests/tools/test_replay_job.py` asserted on `calls[0]`, which is now the
  classifier rather than the reply. It asserts on `calls[-1]`.
- The trail recorded only the last routed call, which would have hidden a
  provider call the reader is paying for and may be debugging. It now records
  every routed completion in order and labels the last one `(reply)`.

Surfacing the classifier's *verdict* — the allowlisted kind it chose, or that
it chose conversation — would be a better trail still, but the `classify` seam
lives in `executor/handlers/whatsapp.py`, which this lane does not own and
which was in flight. Left for whoever owns it.
