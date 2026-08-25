# Prompt: external review of the JARVIS agent workflow

Paste the text below into the external model. Attach, in this order:
`docs/workflow_overview.md`, `agents.md`, `docs/blueprint.md`, `docs/context.md`,
and a listing of `docs/tasks/` (filenames + word counts is enough).

---

You are reviewing the operating process of a solo-developer project that is
built almost entirely by AI agents. Your job is not to review the code. Your job
is to review **how the work gets done** and to redesign it so it needs less of
the human's time without losing any of its correctness guarantees.

## What you're looking at

JARVIS is a personal assistant built on a durable command bus: a FastAPI
webhook takes WhatsApp messages, enqueues them in Supabase Postgres, and a
laptop-resident pull executor claims and runs them. There's a multi-provider LLM
router and a local-first memory subsystem (Ollama + sqlite-vec + SQLite, wrapped
by self-hosted Mem0). It's mid-Phase 1 of a six-phase build.

The work is performed by a CLI orchestrator agent that decomposes tasks into
file-disjoint lanes, writes a brief per lane, dispatches subagents, verifies
their output by running real commands, and commits. The rules are in
`agents.md`. The build state ledger is `docs/context.md`. The attached
`docs/workflow_overview.md` is an objective description of the whole process,
with measurements.

**Treat `workflow_overview.md` as evidence, not as truth.** It was written by an
agent operating inside the system it describes, so it will have blind spots and
may frame its own conventions as more necessary than they are. Challenge it.

## The problem to solve

The human's involvement is currently in the wrong places. His words:

> "I understand my involvement is needed, but not in dumb-ass things where I'm
> just posting one LLM to another or pushing buttons."

Two kinds of human involvement exist here and they need to be told apart
ruthlessly:

**Legitimate — must stay human.** Taste and judgment calls only he can make;
whether a remembered fact about his life is actually right; which personal data
is allowed into the system at all; passwords, 2FA, card entry; sensory checks
(does the TTS sound right, did FL Studio actually edit cleanly); final approval
on anything irreversible or outward-facing.

**Illegitimate — pure mechanism, must be automated away.** Everything where he
is acting as a transport layer or a button. The clearest example, documented in
§5 of the overview: when the terminal agent's answer isn't good enough, he
copies terminal output into a separate Claude web session with a stronger model,
gets a better answer, and pastes it back. He is the network hop between two
models. The project's own blueprint already specifies this escalation as an
automatable routing rung (`claude -p`, subscription-backed headless runs). Other
examples: re-pointing a webhook URL after every ephemeral tunnel restart;
arbitrating stop-and-report halts that had one defensible answer given evidence
the agent had already gathered; being asked to choose between options the agent
could have decided.

Your output should move as much as possible from the second category to zero,
while leaving the first category untouched or even strengthened.

## Constraints that cannot be traded away

These are load-bearing. A proposal that weakens any of them is a failed
proposal, no matter how much time it saves. §10 of the overview lists them in
full; the core:

1. Secrets are never printed, echoed, logged, committed, or requested.
2. No personal corpus is read or ingested without explicit opt-in.
3. Memory extraction and embeddings are loopback-only and fail closed — no
   hosted fallback. (Rationale: one free provider is geo-blocked from Pakistan,
   another may train on prompts; neither may see private content.)
4. No silent model or embedding-dimension drift.
5. Every completion claim must cite the command that produced it and its literal
   output. A subagent that returns nothing is a failed verification, not a
   result.
6. Specified architectural components are decisions, not suggestions — an agent
   that thinks one is wrong stops and reports rather than substituting.
7. Destructive operations need explicit human approval.

Note the tension you have to resolve: rules 5 and 6 are exactly what makes this
system trustworthy, **and** they are the direct cause of most of the halts that
waste the human's time. Do not resolve it by loosening them. Resolve it by
making the system able to satisfy them without a human in the loop for every
instance — for example, by giving the agent a way to obtain a high-quality
second opinion autonomously, and by defining which classes of stop have a single
evidence-determined answer versus which are genuine preference calls.

## Specific things to examine

- The escalation loop (§5). Design the automated replacement end to end: what
  triggers it, what context gets passed, what comes back, how it's recorded in
  the audit trail, and what human review checkpoint replaces the current manual
  relay.
- Empty polling (§7.1) — ~13 consecutive check-ins in one transcript that
  returned no information.
- The stop-and-report rule. Propose a taxonomy: which halts are genuinely
  user-only, which can be resolved by the agent escalating to a stronger model,
  which are decidable from evidence already in hand.
- Recovery overhead (§7.4) — ~16% of lane briefs are about re-establishing state
  rather than advancing the build. Why does state keep getting lost?
- Session context-reload cost (§7.2) and whether the current handoff ledger is
  the right mechanism.
- Live probes (§4.2) are run manually and ad hoc while unit tests are automated
  and green. The phase's actual success criterion has never been executed
  successfully. Address the structural gap between "tests pass" and "the thing
  works."
- Phase ordering (§7.5): a component scheduled for Phase 4 (a named tunnel)
  would eliminate a recurring manual task in Phase 1 today. Look for other
  instances of the same pattern.
- Blocked-item handling: one browser-automation task has been retried across
  multiple sessions against a reproducible failure without ever escalating to
  "hand this to the human once and move on."

## What I want back

Concrete and implementable, not principles. For each proposed change:

- What specifically changes — the rule text, the script, the config, the hook,
  the file. If it's a change to `agents.md`, write the replacement wording. If
  it's a script or a wrapper, sketch its interface and behavior.
- Which human touchpoint it removes, and roughly how much time that recovers.
- Which of the seven constraints it touches, and how it stays compliant.
- How you'd know it worked — the observable signal.
- What it risks breaking.

Rank everything by (time recovered) ÷ (effort + risk). Say plainly which two or
three changes matter most and which are marginal. If you think a piece of the
current process is ceremony that produces no correctness benefit, say so
directly and argue it.

Also flag anything the overview document failed to notice — sources of waste,
fragility, or human dependency that an agent describing its own process would be
unlikely to see.

Write plainly. No status-report formatting, no restating the plan before giving
it.
