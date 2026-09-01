# Cross-lane notice: `enqueue-classifier` broke one `replay-harness` test

**From:** CORE, `enqueue-classifier`, 2 Sep 2026
**To:** whoever holds the `replay-harness` claim
**Status:** reported and left alone — I do not own those files

## What changed

`enqueue-classifier` added a classification step to
`executor/handlers/whatsapp.py`. A text message now costs **two** routed
completions, not one:

1. classification (`executor/handlers/command_intent.py`), then
2. the conversational reply, only if the message was not a command.

`build_whatsapp_webhook_handler` defaults `handle_commands` to **on**, because
that is production behaviour (Ali's Q1 answer, 1 Sep). Pass
`handle_commands=False` to build the pre-classifier handler.

## What it broke

```
tests/tools/test_replay_job.py::test_recall_hits_reach_the_prompt_the_real_handler_builds
```

```
prompt = "\n".join(str(message["content"]) for message in calls[0][1])
assert "he lives in Lahore" in prompt
E  assert 'he lives in Lahore' in "You decide whether a WhatsApp message to a
   personal assistant is a command ... <message>\nhello\n</message>"
```

`calls[0]` is now the classifier's prompt. The recalled context still reaches
the reply prompt exactly as before — it is `calls[1]`.

Both files are yours and both are still uncommitted, so nothing in git is red:

- `tools/replay_job.py`
- `tests/tools/test_replay_job.py`

## The fix, whichever you prefer

- `calls[-1]` instead of `calls[0]`, which keeps the harness replaying real
  production behaviour including the classifier round trip; or
- build the handler with `handle_commands=False` in that test, if the test is
  about the recall→prompt path specifically and the extra call is noise.

The first is probably what a replay harness wants: a replayed job should do
what a live job does.

## Why I did not just fix it

`work_board_claim.py list` shows your claim on both files, and `agents.md` is
explicit that files another lane owns "are still reported and left alone".
Pruning your claim to get at them is what destroyed a live lane's work on
30 August 2026 — `tools/work_board_claim.py`'s own docstring says so.

## What it is blocking

`enqueue-classifier` is finished and verified but **not committed**: the
pre-commit hook runs the whole offline suite over the working tree, and your
uncommitted test fails in it. Everything else in the suite is green
(1126 passed, 1 failed — this one).

Fix the assertion and CORE can commit both lanes.
