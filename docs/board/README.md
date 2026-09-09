# JARVIS work board

**This directory is the only task source.** `docs/plan.md` is a rules
reference (exclusive resources, hot files, cross-lane test doubles) — it no
longer lists work. If a task is not on this board, it is not work; if you
think it should be, add it via the `board-audit` task, don't freelance it.

Built 1 Sep 2026 from `docs/blueprint.md` vs the tree at `bf15f79`, the
1 Sep docs-drift audit, and the 27 Aug blueprint-drift audit
(`docs/audit/blueprint-drift.md`).

## The loop — run this instead of asking

An agent with a free hand does this, forever, without asking the user
anything:

1. Walk the **NEXT** list below, top to bottom. Open each
   `docs/board/tasks/<id>.md`; take the first with `status: ready`.
2. Re-verify the task's premise against the tree (statuses here can drift;
   a task whose premise is gone gets marked `done` or `parked` with evidence,
   and you move on).
3. Claim the task file **and** every file/resource its frontmatter lists:
   `python tools/work_board_claim.py claim --role <CORE|BUILD> --work-item <id> --file docs/board/tasks/<id>.md --file <each file> [--resource <each>]`
   Claiming the task file is what makes task pickup mutually exclusive.
   A claim conflict on the *task file* means someone has it — go back to
   step 1. A conflict on one of its *other* files means a peer holds
   something you need: **message them, do not wait and do not touch it.**
   `python tools/work_board_claim.py message --to <lane> "<what you need
   and the one-line fix you propose>"` (or `SendMessage` if `ListAgents`
   shows them). They apply it or release the file; if you two disagree on
   the fix, either runs `tools/consult.py` with both positions attached and
   both act on the verdict. Meanwhile take the next task.
   (`--role` is `CORE` or `BUILD` only — a task's `lane:` field is an
   autonomy category, never a claim role; only literal `CORE` may claim
   `git-commit`.)
4. Flip `status: ready` → `in-progress`. Execute the task's Steps.
5. Verify. Append a dated `## Log` entry to the task file with the exact
   command(s) and output that prove completion.
6. Flip to `done`, update `docs/state.md` / `docs/context.md` per the
   where-a-fact-goes rules, release the claim.
7. **Go back to step 1. Do not stop, do not ask "what next".**

Stop only when: (a) every remaining task is `blocked` or `USER` — then run
`board-audit` once, and if it finds nothing, write the batched handoff to
`docs/board/HANDOFF.md`, send **one** `PushNotification` saying it exists,
and stop; or (b) you hit a genuine Class C wall not already covered by
`QUESTIONS.md` — add it there with a recommendation, mark the task
`blocked`, and continue with the next task.

## The loop is a mechanism, not a request

Since 2 Sep 2026 the hooks in `.claude/hooks/` run this loop for you:

- **Start:** every session is registered as a lane (`lane-1`, `lane-2`, …)
  and told which peers are alive, what they hold, and whether the previous
  session in this terminal died holding claims — those are inherited, so
  after a crash the user only reopens the terminal and says `resume`.
- **`go` / `resume`:** the only words that switch loop mode on. Any other
  prompt switches it off, so a session the user is talking to is never
  dragged into the board.
- **Stop:** in loop mode, trying to end the turn while a task is `ready`
  and unclaimed hands you that task instead (README order; a task a dead
  lane left `in-progress` comes first; a task handed to you three times
  without progress is skipped — mark it `blocked`). Inbox messages from
  peers are delivered before any task.
- **Every edit:** a write to a file a *live* peer has claimed is refused
  with the holder's lane and the message command. `git commit` needs the
  `git-commit` resource; `git stash` is refused outright.
- **`python tools/work_board_claim.py status`** answers "what is every
  terminal doing" in plain text. A third terminal opened just to ask that
  is a lane too, but stays out of the loop unless told `go`.

Parallel work: independent `ready` tasks may be dispatched to subagent
lanes per `agents.md` (disjoint claims, briefs in `docs/tasks/`, BUILD does
not commit). Ali's standing instruction (1 Sep 2026): **subagent lanes run
on Opus 5.**

## Statuses

`ready` — claimable now, no missing input.
`blocked` — waiting on a `Q#` (an answer in `QUESTIONS.md`) or `U#` (an
action in `USER-TASKS.md`) or another task. Flip to `ready` the moment the
gate clears — whoever processes Ali's answers does this immediately.
`in-progress` — claimed; check `work_board_claim.py list` before touching.
`done` — finished with cited evidence in its Log.
`parked` — deliberately not being done; see `PARKED.md`. Never re-surface.

## When Ali answers questions

Whoever receives answers (in chat or as edits to `QUESTIONS.md`):
1. Record each answer inline in `QUESTIONS.md` under its question, dated.
2. Flip every task the answer unblocks to `ready`.
3. If the answer amends `docs/blueprint.md`, apply the amendment in the
   same pass and note it in the task.
4. Continue the loop — the newly-ready tasks are usually the top of NEXT.

## NEXT — priority order

Rewritten 9 Sep 2026 (`board-audit`) after nine of the 8 Sep list's eleven
"ready now" tasks landed in one day across two sessions and its blocked
list had drifted (two gates half-cleared without being narrowed, one
cleared entirely). The 8 Sep list's own framing still holds: memory may
live on a rented server Ali controls (CLAUDE.md #3 amended), extraction
stays on the laptop, conversation answers right away instead of waiting on
the queue, hosting is a rented x86 box (U17). The goal for September is
the felt problem — ~10 s text replies, 25-50 s voice, a laptop that
suffers — measured before and after every step.

Ready now:

1. `live-routing-probe` — **unblocked this pass**: U2 is done (`.env` has
   `GROQ_DEFAULT_MODEL`/`GEMINI_DEFAULT_MODEL`; Cerebras/NIM blank is
   intentional, not a gap). Proves the new model IDs actually serve;
   claims `provider-account` (spends real allowance, keep calls tiny)
2. `board-audit` — recurring; the fallback when nothing else is ready

Blocked, in the order they'll matter once unblocked:

1. `vps-harden-deploy` — **U17** (the rented box). `bus-offbox-packaging`
   landed 9 Sep, so this is the only remaining gate. Laptop shut, phone
   gets a reply with `path=inline`
2. `laptop-thin-service` — after 1: laptop runs only the action poller;
   no Ollama/whisper/tunnel at boot
3. `conversation-inline-reply` — **U20**: mechanism landed 9 Sep
   (`JARVIS_INLINE_REPLY`, default on), but no `reply-latency` line has
   been read back from a real Graph send since the stack went down 4 Sep.
   Needs `JARVIS_LIVE_WHATSAPP_TO` + the stack up; same gate as 4 below
4. `live-latency-acceptance` — **Q17-D13**. `latency-spans` landed 8 Sep,
   so this is the only remaining gate. Turn the targets into `tests/live`
   assertions
5. `claude-task-executor` — **Q17-D7**: `claude -p` as the general laptop
   executor; the biggest capability lever, highest blast radius
6. `stt-latency-decision` — **Q15** (both reviews independently say A:
   Groq turbo primary, NPU fallback). One env var
7. `hosted-urdu-tts` — **Q17-D6**: Kokoro cannot speak Urdu. Vendor menu
   (Deepgram/Speechmatics STT, Inworld/Azure `ur-PK`/Gemini TTS) is in
   `docs/state.md`, not yet built against
8. `provider-roster-cleanup` — **Q17-D9** (+ U19, the $10 OpenRouter
   credit)
9. `db-maintenance` — **U12**. Runner, ledger and `0003` are built and
   tested; `SUPABASE_DB_PASSWORD` is empty
10. `voice-loop` — **Q12** (Astra says one more Pipecat spike, Fable says
    drop; Ali's call); `voice-command-ingress` behind it
11. `router-eligibility-window` — **Q11**
12. `cloud-routine-wire` — **U8**. `bus-offbox-packaging` landed 9 Sep, so
    this is the only remaining gate
13. `backfill-run` — **Q14**; `extraction-model-spike` landed 9 Sep
    (`llama3.1:8b`/CPU beat the Qwen3-4B/llama.cpp candidate at every size
    tested — no model switch), so its numbers are available for whoever
    answers Q14, not still pending

USER items live in `USER-TASKS.md`. Decisions live in `QUESTIONS.md`.
Deliberately-not-being-done items live in `PARKED.md` — read it before
proposing work, most "obvious next steps" are in there for a reason.
