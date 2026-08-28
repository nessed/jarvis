# Noninteractive consult CLI produces no response

## Resolved 2026-08-29

The CLI is answering noninteractive `claude -p` consults again — see
`docs/consults/2026-08-29-laptop-hp-next-action/` for a full prompt/response/
verdict cycle, and `docs/consults/2026-08-27-class-b-review-verdict-a-309/`
for evidence this session's own consult calls succeeded later the same day.
Nothing in this repo changed to fix it; the transport itself (the CLI
session state described below) recovered on its own or was restored by the
user out of band. Kept as-written below because the reproduction and
diagnosis are the record of what a future recurrence should check first.

## Reproduction

From the repository root on 27 August 2026, run:

```text
.venv\Scripts\python.exe tools\consult.py "Class B review verdict: ..." --slug review-work-board-retry --timeout 90
```

The tool writes `prompt.md` and prints `consulting opus (...)`, then produces no
`response.md` or `verdict.json`. Its `subprocess.run(..., timeout=90)` did not
return after 120 seconds of polling. Interrupting the process ended the terminal
session with exit code 1 and no output.

The preceding attempt, using the same tool and a different review question,
also wrote only `prompt.md` and no response or verdict.

## What failed

`tools/consult.py` successfully found and launched the Claude CLI, but no
noninteractive response was returned. The stdin transport fix is present at
`tools/consult.py:312-331`, so this is not the previously fixed argv truncation
failure.

## Already tried

1. Ran the original review consult; it stalled after the startup line and left
   only `docs/consults/2026-08-27-class-b-review-verdict-a-309/prompt.md`.
2. Retried with a shorter, attachment-free question, a distinct output slug,
   and `--timeout 90`; it stalled identically and was interrupted after more
   than 120 seconds.

## Unblock

The user must restore a Claude CLI session that can complete a noninteractive
`claude -p` request (for example, any required account login, entitlement, or
network action). Do not provide credentials to an agent.
