---
id: state-facts-refresh
status: done
lane: AUTO
priority: 3
phase: meta
blocked-on: none (docs only — good parallel lane)
files: docs/state.md, docs/board/QUESTIONS.md (append blueprint deltas under Q17.3 only)
resources: none
---

# state-facts-refresh — absorb the 8 Sep provider/speech facts

## Why

Fable's review §3 ("Facts that moved, verified 8 Sep 2026") is a table of
provider, hosting and speech facts read from official pages that day.
`docs/state.md` and parts of the blueprint predate it. Corrections, not
proposals — Q10a precedent.

## Steps

1. For each row of that table, find the matching claim in
   `docs/state.md` (provider rungs, voice, hosting, account state) and
   update it with the date. Rows include: Groq Llama rungs dead since
   16 Aug / free lane is `openai/gpt-oss-120b` with its limits; Groq
   Whisper turbo limits; Cerebras context 65K/131K (not 8K); Gemini free
   tier trains / paid does not; OpenRouter 50 RPD, $10 → 1,000 RPD;
   DeepSeek V4-Flash thinking on by default; NIM Pakistan-blocked; Claude
   promo dates; `claude -p` still on subscription; Remote Control not
   scriptable; Routines `/fire` bills Max; Codex `codex exec` on plan
   auth; Oracle idle-reclaim rule; Hetzner cost-optimised unavailable;
   Lightsail $5 tier; **Kokoro has no Urdu**; Whisper alternatives omit
   Urdu; Deepgram/Speechmatics for Urdu STT; Inworld/Azure `ur-PK` for
   TTS; ZDR providers (Groq, Fireworks).
2. Where `state.md`'s provider tables are **generated**
   (`provider-status-generator`), do not hand-edit those blocks — put the
   fact in the hand-written section beside them and say the generator is
   the source for reachability.
3. Any row whose home is `docs/blueprint.md` (Cerebras context, NIM as
   "VPS candidate", Kokoro as the voice, Hetzner as fallback): **do not
   edit the blueprint.** Append the list under Q17.3 in `QUESTIONS.md` as
   "blueprint deltas from state-facts-refresh" for Ali's blanket yes.
4. `python tools/context_status.py --check` still passes.

## Done when

`state.md` carries every row with a date; the blueprint delta list is
under Q17.3; Log cites the check command.

## Log

### 2026-09-09 — done (lane-1)

**Source table**: `docs/history/architecture-review-fable-2026-09-08.md` §3
("Facts that moved, verified 8 Sep 2026"), all 20 rows.

**Regenerated the machine-written block first.** `tools/provider_status.py
--write` — it was still dated 2 Sep and listed `groq`/`gemini` as
"configured but not routable" (unset `.env` placeholders), which the
`provider-ladder` work landed 9 Sep had already fixed in `.env` but not yet
in this stale snapshot. Now dated 9 Sep, `groq`/`gemini` correctly routable.
Not hand-edited — ran the generator per step 2's instruction.

**Absorbed into `docs/state.md`'s hand-written sections** (not the generated
block): a new paragraph under "Provider rungs" covering Groq's dead Llama
rungs and its gpt-oss-120b replacement limits, Cerebras' real context caps,
Gemini's free/paid training distinction, OpenRouter's $10→1,000 RPD lift,
DeepSeek V4-Flash's default thinking, the five Claude/Codex facts (promo
lapse date, `claude -p` still subscription-only, Remote Control not
scriptable, Routines `/fire` billing Max, Codex plan-auth), ZDR provider
status (Groq/Fireworks qualify, Anthropic/Gemini-free/DeepSeek-direct
don't), the hosting re-pricing (Oracle idle-reclaim, Hetzner unavailable,
AWS Lightsail's $5 tier and credit terms, Fly.io, Cloudflare Durable
Objects), the full Urdu speech-vendor menu (STT: Deepgram/Speechmatics;
TTS: Inworld/Cartesia/Azure ur-PK/Gemini; realtime: Gemini Live only), and
local extraction's real constraint (Radeon 860M invisible to Ollama on
Windows, Qwen3-4B/llama.cpp/Vulkan as the alternative). Groq Whisper
turbo's rate limits (20 RPM, 2K RPD, 28,800 audio-sec/day, $0.04/hr paid,
no streaming) folded into the existing "Cloud STT fallback" row rather than
duplicated. "Kokoro has no Urdu" was **already** current (existing WhatsApp
voice wiring row, dated 30 Aug) — confirmed, not re-added.

**Blueprint deltas appended under `QUESTIONS.md` Q17.3** (not hand-edited in
`docs/blueprint.md` itself, per step 3): Cerebras' 8K-context claim (two
locations named), NVIDIA NIM as a routing/VPS candidate (should drop
entirely, not just from extraction), Hetzner CX22 as a real fallback (three
locations named), and a drift-prevention note that the blueprint should say
Kokoro has no Urdu rather than leaving that only in `state.md`/code comments.
Labeled "for one blanket yes," matching Q10a's precedent this task cites.

**Verification.**

```
$ .venv/Scripts/python.exe tools/context_status.py --check
(exit 0)
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1661 passed, 10 deselected in 56.16s
```

Docs-only change; test count unchanged from before this task.
