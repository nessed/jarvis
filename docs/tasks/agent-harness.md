# agent-harness — make the multi-session workflow enforce itself

**Lane:** CORE, 2 Sep 2026. **Trigger:** Ali asked for the parallel-agent
setup to need nothing from him beyond opening a terminal in the folder and
typing `go` or `resume`, and for the two panes to be able to talk when they
collide.

## What was wrong

Every rule in `agents.md`, `docs/plan.md` and the board was a convention the
model had to remember. The evidence from one evening of two panes:

- Ali had to tell a pane "ur running w another agent side by side", paste a
  screenshot of the other pane, and type "it crashed". He was the discovery
  mechanism three times.
- Both panes were CORE and committed into one tree; it serialised by luck.
- The suite "flake" was two panes sharing `--basetemp=.pytest-basetemp`; the
  pre-commit hook hardcoded it too.
- The claim tool recorded a dead PID, so liveness was a 24h timer; a lane
  guessed a peer was alive from file mtimes.
- A cross-lane note (`docs/tasks/enqueue-classifier-crosslane-note.md`) was
  written correctly and never delivered; a finished lane waited on it.
- "Do not stop, go back to step 1" was a sentence, not a mechanism.

## What landed

`.claude/hooks/` (stdlib-only, no project imports; copy this directory plus
`tools/work_board_claim.py` and the `hooks` block of `.claude/settings.json`
into any repo to reuse the whole thing):

| hook | event | does |
|---|---|---|
| `harness_session_start.py` | SessionStart | registers the session as `lane-N`, exports `JARVIS_SESSION_ID`/`JARVIS_LANE` via `CLAUDE_ENV_FILE`, reports peers + orphaned claims + inbox; a session in the same terminal pane as a dead one inherits its claims and lane |
| `harness_guard.py` | PreToolUse (Edit/Write/MultiEdit/NotebookEdit/Bash) | heartbeats the session; denies writes (including `>`/`tee`/`sed -i`/`mv`/`cp`/`rm` targets in Bash) to files a live peer holds; gates `git commit` on `git-commit`; refuses `git stash` |
| `harness_prompt.py` | UserPromptSubmit | `go`/`resume`/`continue` switch loop mode on, anything else off; injects peers + inbox |
| `harness_stop.py` | Stop | in loop mode, blocks the stop with the next task (README order, abandoned in-progress first, 3-strike skip); inbox first |

`tools/work_board_claim.py` gained: session registry (`sessions/`), inbox
(`message`, `inbox`), `sessions`, `whoami`, `status`, `adopt`, pane
inheritance, and liveness-based pruning for session-attributed claims
(legacy claims keep the age rule and are not enforced by the guard, so
pre-harness panes are never locked out of their own files).

Per-lane pytest scratch: `--basetemp=.pytest-basetemp-$JARVIS_LANE` in
CLAUDE.md and the pre-commit hook.

## Verified

- `tests/tools/test_harness_hooks.py` (see the commit's suite line).
- Real headless run: `claude -p "... whoami"` in a scratch state dir
  registered `lane-1` with pane `e2e-tab`, the nested session's shell saw
  its own `JARVIS_SESSION_ID`, and `last_seen` advanced after tool calls —
  i.e. `$CLAUDE_PROJECT_DIR` expands and all hooks fire on Windows.

## Not done / limits

- Bash write detection is best-effort. A Python heredoc that opens a file
  for writing is not seen. The claim tool's own conflict check still
  applies whenever the lane claims first, which the loop requires.
- Resource claims other than `git-commit` (Ollama tiers, mic, tunnel) are
  still convention.
- Hooks configured in `.claude/settings.json` reach a running session only
  when it restarts; the two panes alive when this landed keep working
  under the old rules until they are reopened.
- Auto-restart after a crash is not a wrapper: the user reopens the
  terminal and says `resume`; pane inheritance does the rest.
