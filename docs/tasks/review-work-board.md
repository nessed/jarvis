# Review docs/plan.md, independently

## Why this exists

`docs/plan.md` (98 jobs) was just built by the orchestrator that is asking for
this review, from five parallel read-only mapping lanes over the whole repo at
commit `628b6ea`. The builder cannot grade its own work — that is the entire
point of this brief. Come at it fresh. Do not read any prior conversation about
how it was built; judge the artifact against the repo as it stands.

## What you are checking

`docs/plan.md` claims to be a work-parallelism board: a fifth doc tier
(alongside `context.md`/`state.md`/`history/`/`blueprint.md`) that lets two
orchestrators — one on Claude Max, one on Codex — work this repo at once
without the user manually relaying screenshots between sessions, which is the
problem it exists to solve. It asserts things about which files collide, which
jobs must never run concurrently, and what blocks what.

**Your job: verify those assertions against the actual repo, not against the
document's own confidence.** A board that is wrong is worse than no board,
because it will be trusted.

## How to review it — spot-check, don't re-derive

You do not have budget to redo the five mapping lanes from scratch. Instead:

1. **Read `docs/plan.md` in full.** Note every concrete, falsifiable claim: a
   file path, a line number, a "job X writes file Y," a "job A blocks job B," a
   resource claim ("Ollama is single-serial").
2. **Pick 10-15 claims spread across the document** — favor the ones that, if
   wrong, would cause real damage (a claimed-safe parallel pair that actually
   collides; a claimed-hot file that isn't; an ordering claim that's backwards).
3. **Verify each against the live repo**: read the actual file, grep for the
   actual usage, check the actual test double. Cite what you found.
4. **Check the structural claims specifically:**
   - The "five hot files" plus the two sixth/seventh additions
     (`bus/whatsapp_client.py`, `memory/store.py`, `tests/router/test_routing.py`)
     — are these really the contention points, or did the mapping miss one?
   - The Protocol/test-double section — do `JobRepository` and `ChainQueue`
     really diverge the way it says, and are the named implementers (with line
     numbers) actually there?
   - The "ordering, not just collision" section — for each pair, is the stated
     order actually required, or is it invented caution?
   - The "Available now — zero collision risk" list — pick 5 of these and
     confirm they genuinely touch no existing file, and genuinely have no
     hidden resource conflict (Ollama, live Supabase, git, a physical device).
   - The Decisions section — are these genuinely Class C (the user's call), or
     did the builder push a judgment call there that an agent could safely make?
5. **Judge the design, not just the content:**
   - Is a single 700-line markdown file actually usable by an agent mid-session,
     or is it too long to load reliably? Would a different shape (per-area
     files, a generated index) serve better?
   - Is the `Claimed` / `Requests to CORE` mechanism (agents hand-editing two
     blocks at the top/bottom of the file) going to survive two agents editing
     concurrently, or does it need a lock, a script, or a different medium
     entirely?
   - Does the CORE/BUILD role split actually cover the repo, or are there files
     that belong to neither and would fall through the cracks?
   - Is anything in the "resources" framing (Ollama tiers, provider quota,
     machine-saturation, physical I/O) actually enforceable by an agent reading
     a markdown file, or does it require a mechanism (a hook, a lock file) that
     doesn't exist yet — in which case the document is describing a rule
     nobody will follow, the same failure mode `.githooks/pre-commit`'s own
     comments warn about.
6. **Look for what's missing**: any job class in the repo that didn't get
   mapped (check against `docs/audit/blueprint-drift.md`, which was the primary
   input), any collision type not covered, any area of the repo the five lanes
   didn't touch.

## A second, smaller pending decision to weigh in on

A follow-up change was proposed but **not yet applied**: adding roughly six
lines to `CLAUDE.md` telling an agent to state its role (CORE or BUILD) at
session start, read `docs/plan.md`'s `Claimed` block before writing anything,
add its own claim line, and never touch a file another role currently holds.

Say whether that's the right amount of ceremony for `CLAUDE.md` — which per
this repo's own rules is loaded into every session automatically — or whether
it's over-specifying a process that will rot the way the old 469-line
`context.md` rotted, per `agents.md`'s own stated lesson. If you think it's
right, say so plainly; this brief is not fishing for problems, it's asking for
an honest verdict either way.

## Output

Do not edit `docs/plan.md`, `CLAUDE.md`, or anything else. This is a review,
not a fix. Report:

1. **Verdict**: is this board net-positive to adopt as-is, adopt with changes,
   or wrong enough to discard? One paragraph, lead with the answer.
2. **Confirmed claims**: which of the 10-15 you checked held up, briefly.
3. **Wrong or unverifiable claims**: which didn't, with the specific file/line
   that contradicts it. This is the section that matters most.
4. **Structural verdict**: answer the five design questions in step 5 above.
5. **Gaps**: anything load-bearing that the board is missing.
6. **The CLAUDE.md question**: a plain yes/no/modify with one sentence why.

Lead every section with the answer. Evidence after. No summary of what you
read.
