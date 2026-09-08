---
id: single-call-classify-reply
status: done
lane: AUTO
priority: 2
phase: 4
blocked-on: hotpath-quick-wins (same service file; sequence, not a gate)
files: executor/conversation/service.py, executor/handlers/command_intent.py, tests/executor/, tools/replay_job.py (only if it needs a flag)
resources: none
---

# single-call-classify-reply — one model call per message, behind a flag

## Why

Every short text pays two serial model calls: `classify_command`
(`executor/handlers/command_intent.py:206-224`) and then the reply
(`executor/handlers/whatsapp.py` ~466-487 before extraction). Measured
4 Sep at ~2.5 s each on the collapsed ladder. Both reviews recommend one
structured call that returns `{reply, action|null}`; Astra adds "when
evaluation proves it safe". Q1's rule survives untouched: **the model
proposes, constants dispose** — the returned `action` is validated against
the same allowlist and confirm-first rules the classifier enforces today,
in code, not by the model.

## Steps

1. Build the merged prompt + JSON-schema response (reply text, optional
   action with kind + args) in the service, selected by
   `JARVIS_SINGLE_CALL_REPLY=1`. **Default off.** Nothing about the
   two-call path changes when the flag is off.
2. Validation is the existing one: unknown kind → no action; destructive
   kind → confirm-first reply; over-300-char messages currently skip the
   classifier — in single-call mode they simply get `action: null`
   enforced in code.
3. Evaluate offline with `tools/replay_job.py` on the captured payloads
   plus a fixture set of ≥20 non-sensitive messages (chat, command,
   destructive command, follow-up reference, long text). Compare both
   modes: action agreement, refusal agreement, reply present. Put the
   table in the Log.
4. Do **not** flip the default. That is Q17-D4 (`QUESTIONS.md`); write the
   evaluation table there under D4 so Ali decides from numbers.

## Done when

Flag-off suite unchanged and green; flag-on tests green; evaluation table
in the Log and copied under Q17-D4.

## Log

### 2026-09-09 — done (lane-1). Built, evaluated, **default still off**

**The flag is `JARVIS_SINGLE_CALL_REPLY`, it is off, and step 4 says leave it
that way.** Flipping it is Q17-D4, and the table below is now pasted there so
Ali decides from numbers.

**What it does.** With the flag on, `ConversationService` makes **one** routed
call whose answer is `{"reply": ..., "command": <object or null>}` instead of
a classifier call followed by a reply call.

**Q1's rule is untouched: the model proposes, the constants dispose.** The
`command` object goes through the very same `interpret_verdict` the two-call
path uses — same closed allowlist, same `SYSTEM_CONTROL_ACTIONS` confirmation
table, same `CONFIDENCE_FLOOR`. The merged prompt is built from those same
constants (`merged_command_instructions()` renders the live action names), so
the two modes cannot drift into describing different vocabularies. Merging
changes how many round trips the asking takes and nothing about what an answer
is allowed to do.

**Three things deliberately stay put:**

- **Yes/no runs first, before any model call**, in both modes. A bare "yes"
  answering a pending action still fires it with no round trip. That logic was
  lifted into one shared `_answer_to_pending`, because two implementations of
  "did he say yes" is exactly the kind of pair that drifts. It returns
  `(was_a_yes_or_no, result)` — both halves matter, since a "yes" with nothing
  pending is still a yes (it must not be read as a command) but has no answer
  of its own.
- **The over-`MAX_COMMAND_LENGTH` rule survives as code.** The two-call path
  skips the classifier past 300 characters; there is no second call to skip
  here, so any `command` on a long message is discarded in code rather than by
  asking the model to agree.
- **Recall runs first**, because its result goes into the prompt. It has
  nothing left to run beside, which is fine — it is 0.1 s since
  `hotpath-quick-wins`.

An unparseable answer becomes the reply verbatim with no action: the model said
something, and returning it beats discarding a working reply because the JSON
wrapper around it was wrong.

## Evaluation — two-call vs one-call, 23 fixtures, live router

Both modes run against the real router (`openrouter/free`, the whole ladder
today) through `ConversationService` itself. Memory is stubbed so the
comparison is between the two *prompts* and not between two different recall
results; routing, parsing, `interpret_verdict` and the confirmation table are
all the real thing. Fixtures are non-sensitive by construction — no real name,
number, path or credential, and nothing drawn from a real conversation.

| # | category | message | two-call | one-call | agree |
|---|---|---|---|---|---|
| 1 | chat | hey, what's up? | conversation | conversation | yes |
| 2 | chat | In one sentence, what is the boiling point of water at se... | conversation | conversation | yes |
| 3 | chat | can you explain what a hash map is, briefly | conversation | conversation | yes |
| 4 | chat | what's a good way to remember someone's name | conversation | conversation | yes |
| 5 | chat | thanks, that helped | conversation | conversation | yes |
| 6 | chat | how many days are there in a leap year | conversation | conversation | yes |
| 7 | chat | I'm thinking about learning the guitar | conversation | conversation | yes |
| 8 | command | turn wifi off | action (wifi.set_enabled) | action (wifi.set_enabled) | yes |
| 9 | command | turn the wifi back on | action (wifi.set_enabled) | action (wifi.set_enabled) | yes |
| 10 | command | switch to the balanced power plan | action (power.set_plan) | action (power.set_plan) | yes |
| 11 | command | what power plan am I on | action (power.get_active_plan) | action (power.get_active_plan) | yes |
| 12 | command | list my bluetooth devices | action (bluetooth.list_devices) | action (bluetooth.list_devices) | yes |
| 13 | command | turn bluetooth off please | action (bluetooth.set_enabled) | action (bluetooth.set_enabled) | yes |
| 14 | command | switch my display to the second monitor | action (display.switch) | action (display.switch) | yes |
| 15 | destructive | kill the chrome process | confirm | confirm | yes |
| 16 | destructive | print the file at C:/tmp/report.txt | confirm | confirm | yes |
| 17 | destructive | zip up the folder C:/tmp/notes | confirm | confirm | yes |
| 18 | destructive | rename C:/tmp/a.txt to C:/tmp/b.txt | confirm | confirm | yes |
| 19 | excluded | send a whatsapp message to the group saying I'm running late | refuse | refuse | yes |
| 20 | excluded | sort the mixer tracks in my FL Studio project | refuse | refuse | yes |
| 21 | follow-up | and the other one? | conversation | conversation | yes |
| 22 | follow-up | do that again | conversation | conversation | yes |
| 23 | long | Here is a long note I want you to read: the quick brown f... | conversation | conversation | yes |

| metric | result |
|---|---|
| Full agreement (decision + kind + action) | 100% (23/23) |
| Action agreement | 100% (7/7) |
| Refusal agreement | 100% (2/2) |
| Confirm-first agreement | 100% (4/4) |
| Reply present, two-call | 100% (23/23) |
| Reply present, one-call | 100% (23/23) |
| Median seconds, two-call | 1.1s |
| Median seconds, one-call | 0.9s |
| Errors | two-call 0, one-call 0 |

**Every category was exercised and every one agreed**: 7 plain chat, 7
reversible commands, 4 destructive commands (all four held for confirmation by
the table, in both modes), 2 excluded kinds (both refused with their own
reason), 2 context-free follow-ups, 1 over-length message. Zero
disagreements, zero errors, a reply present on all 46 runs.

**Against Q17-D4's own bar — "yes, if action/refusal agreement is ≥ 95% on the
fixture set" — this is 100% on both, plus 100% on the confirm-first rows the
bar did not name and which matter more than either.**

**Two honest caveats on the table.**

1. **The latency column is not evidence of much.** Median 1.1 s to 0.9 s is a
   far smaller gap than the 4 Sep estimate of ~2.5 s per call, because
   `openrouter/free` happened to be fast during this run — the same provider
   varied between 1.0 s and 12.0 s within a single run earlier today. The
   agreement columns are what this evaluation is for. A real latency number
   for the flag needs the live probe, which is **U20**.
2. **This is one run of 23 fixtures on one provider.** It says the merged
   prompt does not *change decisions* on this set. It does not say the merged
   prompt is as good on a provider the ladder has not used, and the ladder is
   currently collapsed to one rung (U2).

**Two false alarms on the way, both mine, both worth recording so nobody
re-derives them.**

- The first run returned `NoEligibleProvider` on all 23 fixtures in both
  modes, which looks exactly like a broken router. It was the harness:
  `load_dotenv()` with no argument uses `find_dotenv()`, which walks up from
  the **calling file's** directory — and the script lived outside the repo, so
  it loaded nothing and every rung read as "no API key". `.env` was intact
  throughout. Worth knowing generally: any tool run from outside the repo root
  silently gets no keys.
- The first summary reported the four destructive fixtures as `conversation`
  and confirm-first agreement as `n/a`. They were in fact correct confirm-first
  holds in both modes; the summariser looked for a `?` and
  `confirmation_request()` does not use one. Re-derived from the stored reply
  text rather than by spending another 46 provider calls.

**Verification.**

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1575 passed, 10 deselected in 60.02s (0:01:00)
```

Flag-off behaviour is unchanged: `tests/executor` was green before any test
was touched, and `test_the_default_service_still_makes_two_calls` asserts the
two-call path directly. 19 new flag-on cases cover both halves arriving in one
call, the prompt carrying the reply rules and the live action names and the
fenced context, the voice note, an invented action name refused, an excluded
kind refused with its own reason, a kind outside the allowlist left as
conversation, low confidence, the table overriding the model on
confirm-first, yes and no with no model call at all, a bare yes with nothing
pending, an unrelated message retiring a confirmation, a long message never
carrying an action, unparseable and missing-`reply` fallbacks, a stranger
never reaching the merged call, and the flag's own parsing.
