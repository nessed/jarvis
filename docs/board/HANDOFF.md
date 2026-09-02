# Handoff — 3 September 2026

Nine board tasks landed in one session. The board has nothing `ready` left
except the recurring audit, which ran this session. **Everything else is
waiting on you: four actions and two decisions.**

---

## Do these four, in this order

**U13 — one line, and it unblocks everything else you touch.** Every `git`
command in this repo fails outright:

```
fatal: detected dubious ownership in repository at 'C:/Users/Ali/Desktop/Projects/Code/jarvis'
'.../.git' is owned by: DESKTOP-68UQJNR/CodexSandboxOffline
but the current user is: DESKTOP-68UQJNR/Ali
```

The fix:

```
git config --global --add safe.directory C:/Users/Ali/Desktop/Projects/Code/jarvis
```

`agents.md` puts global git config on the ask-first list, so it is yours to
run. It also fails four `test_context_status.py` tests, and it is why
`.pytest_cache` is unwritable — one fault, three symptoms. **Worth knowing
why `.git` changed owner if you can tell.** A repo another account can write
is a bigger question than the warning.

**U14 — send one WhatsApp message** (1 min, needs `start-jarvis.bat` running).

> what wifi interfaces does this laptop have?

You should get **two** replies a few seconds apart:

```
On it: list wifi interfaces. Queued as job a8b4785b.
Done: list wifi interfaces. Wi-Fi (connected).
```

The machine half is proved live end to end. The half with your thumb in it
is not, and no test can prove it.

**U2 — paste three model IDs into `.env`.** This is no longer a guess. The
router now reports what it is refusing and why:

```
groq      no model: its default_model placeholder is unset in .env
cerebras  no model: its default_model placeholder is unset in .env
gemini    no model: its default_model placeholder is unset in .env
```

That leaves `openrouter, mistral, deepseek` as your entire ladder. Your own
values from Q5 are in `docs/state.md`.

**U12 — fill `SUPABASE_DB_PASSWORD`.** Unblocks `db-maintenance`'s live half.
The runner, its ledger and migration `0003` are all built, tested and
committed; the key is in `.env` and empty.

---

## Decide these two

**Q12 — drop Pipecat from the desk loop?** Recommendation filed: yes, keep
Silero VAD. Five of six stages become custom code either way. Blocks
`voice-loop` and `voice-command-ingress` behind it.

**Q11 — how long is the router's verification window?** Recommendation:
"24h + eligible-but-last". It is the last of §3.3's five clauses the code
does not implement; the other four shipped this session.

Two more questions are filed and block nothing: **Q13** (what to do with 98
dead-lettered rows — recommendation: leave them) and **Q14**, below.

---

## What landed

**Memory was down and is running.** It had been dead since 30 August. Two
causes, neither in the chain's own logic: Ollama stopped at 00:35 on 31 Aug,
and the `background-worker` process was killed at 01:53 and never restarted.
Seven live jobs have completed since, seven turns distilled, zero failures.

The 98 dead-lettered rows carried no work — the payload is scheduling
metadata and the real backlog is local — so nothing was lost and there is
nothing to re-queue. The re-seed loop that turned one outage into 84 rows in
78 minutes is now rate-limited.

**An action tells you whether it worked.** A WhatsApp command used to say
"queued as job X" and then nothing, whether it succeeded, failed, or
dead-lettered. The outcome now comes back as a second message, including on
failure — which is the case where silence was worst.

**Four router tasks, all of §3.3 except the verification window.**

- A denied rung (401/402/403) no longer quietly falls through to one that
  costs money.
- Three rungs that sat at the front of every request unserved are now
  excluded, with the env var that would fix each named.
- The ladder orders by cost class first, then by measured latency inside a
  class. Cerebras is `trial`, not `free`, since its free tier became a $5
  credit.
- `state.md`'s provider lists are generated, not typed.

**Two things that were quietly costing time.**

`pytest -q` works bare now. The flags moved into config, and a fixed
`--basetemp` was dropped entirely — two sessions running the suite at once
were deleting each other's temp files, which reads exactly like a flaky
suite. Proved both ways.

And the "offline" suite was reaching the internet: five tests built a live
Supabase client they never used, so a wifi blip turned the commit gate red.
A guard now refuses any non-loopback connection. **The suite went from 77s to
42s** — nearly half its runtime was network it should never have touched.

---

## Two things worth your attention

**Q14 — the backfill is stuck between two of your own answers, 49 minutes
apart.** On 2 Sep at 01:53 you amended blueprint §1.3 to say fact extraction
uses `json_object` with pydantic validation, *not* constrained JSON-schema
decoding — "that is what shipped and what the code does". At 02:42 a blocker
was filed arguing the opposite, and quoting §1.3's *pre-amendment* text as
its justification.

The measurements in that blocker are good: unconstrained decoding produced
invalid JSON twice at real chunk sizes and aborted the run, while constrained
held at every size tested. But the fix it recommends is now a request to
change the spec back, which is yours. Recommendation: re-amend and file the
task.

**`backfill-run` was invisible on the board.** Nine task files are blocked;
NEXT listed eight. It had been missing since the 2 Sep rebuild, so nobody
would have picked it up even after its gate cleared. Now listed.

---

## Numbers

```
Nine commits, bf9efc5..ba80f71
Board: 18 done, 9 blocked, 1 ready (the recurring audit)

.venv\Scripts\python.exe -m pytest -q
1367 passed, 9 deselected in 42.38s

.venv\Scripts\python.exe -m pytest -q -m live tests/live
1 passed, 1 warning in 29.97s
```

Three design decisions were consulted rather than guessed, and each verdict's
flip-conditions were checked against the tree rather than accepted on trust:
`docs/consults/2026-09-02-action-outcome-reply-shape/`,
`-router-denial-surfacing-reading/`, `-router-p50-storage-scope/`.

**Not done, and deliberately:** `backfill-run` (Q14), `voice-loop` (Q12),
`router-eligibility-window` (Q11), `db-maintenance` (U12), `live-routing-probe`
(U2), and the four Phase 4 tasks behind U7/U8. The FLP writing half stays
unbuilt per `PARKED.md`.
