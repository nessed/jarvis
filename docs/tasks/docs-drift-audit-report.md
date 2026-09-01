# Docs drift audit — `docs-drift-audit`, 1 September 2026

One-time, by-hand execution of what `facts-check-job` would do. Every
falsifiable claim in `docs/state.md`, `docs/plan.md`, `docs/context.md`
(hand-written part) and `docs/blueprint.md` (tree-factual claims only), checked
against the tree. **This report changes nothing.** Findings are written down,
not fixed.

`docs/history/` was deliberately not audited: it is append-only and preserves
superseded conclusions on purpose.

**Content audited** (three of these files are under concurrent CORE edit; these
are the md5s of what was read):

```
4fe61d4293276dee156fbfc8c73e94c0  docs/state.md
68cfb82455f47cad3fa3c281f420b752  docs/plan.md
6290cbc9a671b78f3fefd7ba97bc090d  docs/context.md
2460a8d0296325c026bb1b1ed9ee85aa  docs/blueprint.md
```

HEAD is `52e2c03`. `.pytest_cache/` and `.pytest-typing-diagnosis/` are
unreadable at the repo root (`Permission denied`) — expected, not a finding.

---

## Worst drift first

These are the claims that would send someone into wrong work.

### 1. `docs/state.md` says the executor topology is not live. It has been.

| field | content |
|---|---|
| where | `docs/state.md`, Built and working → Executor topology: "Focused tests pass. **It is not live: Quick Tunnel startup currently fails before worker launch or Meta verification.**" |
| status | **DRIFTED** |

Evidence:

```
$ ls -la tools/*.log
-rw-r--r-- 1 Ali 197121 484830 Aug 31 01:53 tools/background-worker.out.log
-rw-r--r-- 1 Ali 197121   3445 Aug 31 00:20 tools/bus.out.log
-rw-r--r-- 1 Ali 197121   8944 Aug 31 03:30 tools/cloudflared.log
-rw-r--r-- 1 Ali 197121 219335 Aug 31 01:53 tools/whatsapp-worker.out.log
-rw-r--r-- 1 Ali 197121   2790 Aug 31 00:19 tools/whisper-server.out.log

$ wc -l tools/whatsapp-worker.out.log tools/background-worker.out.log
whatsapp-worker lines: 1570
background-worker lines: 2990
```

Both kind-filtered workers ran, for thousands of log lines, on 31 August —
after the bus and after the tunnel. `docs/state.md`'s own "WhatsApp voice
wiring" row says the same thing from the other direction ("**Live-verified,
30 Aug 2026**"), so the file contradicts itself.

**Consequence:** a reader picking up the executor-topology work debugs a
Quick Tunnel that demonstrably came up, and treats the two-poller split as
unproven when it has run in production for two nights.

---

### 2. The background worker does **not** claim "every other registered kind". Four job kinds have no consumer.

| field | content |
|---|---|
| where | `docs/blueprint.md` §3 Always-on presence: "a separate background poller which **claims every other registered kind**, including `distill_memory`" |
| status | **DRIFTED** |

Evidence:

```
$ sed -n '498,532p' tools/start_jarvis.py
        supervisor.spawn(
            "whatsapp-worker",
            [python, "-m", "executor.poller", "--kind", "whatsapp_webhook",
             "--no-heartbeat", "--interval", str(args.interval)], ...)
        supervisor.spawn(
            "background-worker",
            [python, "-m", "executor.poller", "--kind", "distill_memory",
             "--interval", str(args.interval)], ...)

$ sed -n '258,262p' executor/poller.py
    parser.add_argument(
        "--kind",
        choices=tuple(DEFAULT_HANDLERS),
        help="claim only this registered job kind",
    )

$ grep -n "DEFAULT_HANDLERS" -A 10 executor/poller.py
94:DEFAULT_HANDLERS: dict[str, HandlerRegistration] = {
95-    WHATSAPP_JOB_KIND: HandlerRegistration(build_whatsapp_webhook_handler()),
96-    "flp_sort": HandlerRegistration(build_flp_sort_handler()),
97-    "system_control": HandlerRegistration(build_system_control_handler()),
98-    ZOOM_JOIN_MEETING_JOB_KIND: HandlerRegistration(_app_automation_handler),
99-    WHATSAPP_DESKTOP_SEND_MESSAGE_JOB_KIND: HandlerRegistration(_app_automation_handler),
100-    DISTILL_JOB_KIND: HandlerRegistration(
101-        build_distill_memory_handler(), timeout_seconds=DISTILL_TIMEOUT_SECONDS
102-    ),
103-}
```

`--kind` takes exactly one value. Six kinds are registered; the launcher's two
workers cover two of them. `flp_sort`, `system_control`, `zoom_join_meeting`
and `whatsapp_desktop_send_message` are consumed by **nothing** under
`start-jarvis.bat`.

`docs/state.md` and `docs/plan.md` both describe these four as "registered
handlers with no producer". That is true and it is only half the problem: they
also have no consumer in the launched topology.

**Consequence:** whoever builds `enqueue-classifier` — the named producer for
exactly these kinds — ships a producer whose jobs sit in `queued` forever,
because no running poller claims them. The doc says the background worker will
pick them up. It will not.

---

### 3. "The only `enqueue()` call site in the tree is `bus/main.py:112`" is false, in two documents.

| field | content |
|---|---|
| where | `docs/state.md`, Desktop system control row: "**Nothing enqueues it** — the only `enqueue()` call site in the tree is `bus/main.py:112`'s `whatsapp_webhook`." And `docs/plan.md`: "The only `enqueue()` call site in the tree is `bus/main.py:112` (`whatsapp_webhook`)." |
| status | **DRIFTED** |

Evidence:

```
$ grep -rn "enqueue(" --include=*.py bus/ executor/ router/ memory/ db/ tools/ voice/ | grep -v "def enqueue"
bus/main.py:112:        job = enqueue("whatsapp_webhook", payload, repository=repository)
executor/handlers/distill.py:223:    raw_schedule = enqueue_successor or _repository_successor_enqueue(repository)
executor/handlers/distill.py:469:    return enqueue(
db/jobs.py:321:    return _repository_or_default(repository).enqueue(kind, payload, run_after, max_attempts)

$ sed -n '466,474p' executor/handlers/distill.py
    run_after = _utcnow() + timedelta(seconds=max(0.0, delay_seconds))
    return enqueue(
        DISTILL_JOB_KIND,
        {"reason": reason},
        run_after,
        max_attempts=DISTILL_MAX_ATTEMPTS,
        repository=repository,
    )
```

`bus/main.py:112` is exactly right as a line citation. The claim of
*uniqueness* is not: `executor/handlers/distill.py:469` is a second producer,
writing `distill_memory` rows on a self-re-enqueuing chain.

**Consequence:** an agent reasoning about queue ordering, dedup, retention or a
live schema migration concludes the queue has exactly one writer and misses the
one that writes continuously and unattended. `docs/state.md`'s own Batch
distillation row describes that chain in detail, so the tree contradicts the
doc's summary, not the doc's detail.

---

### 4. `docs/context.md`'s FL Studio audit numbers are both wrong.

| field | content |
|---|---|
| where | `docs/context.md`, Now: "**24 of Ali's real projects were read** (`docs/tasks/flp-audit-data.json`…)" and "**18 of 24 projects parse**; the rest are PyFLP bugs, all loud." |
| status | **DRIFTED** |

Evidence:

```
$ python -c "import json,collections; d=json.load(open('docs/tasks/flp-audit-data.json')); \
             print('entries:',len(d)); print(collections.Counter(v.get('status') for v in d.values()))"
entries: 26
status counts: Counter({'OK': 17, 'PARTIAL': 7, 'PARSE_FAIL': 2})
playlist_readable counts: Counter({'True': 17, 'False': 7, 'None': 2})

$ python -c "... print(failed)"
parsed: 24 failed: 2 ['outroforest', 'prayon']
failed sample: {'file': 'outroforest__outroforest.flp', 'kb': 182,
                'status': 'PARSE_FAIL', 'error': 'UnicodeDecodeError'}
```

26 entries, one of which (`FL 20.8.4`) is PyFLP's own upstream fixture, not
Ali's — so 25 of his projects were read, not 24. Only **2 of 26 fail to
parse**. 17 are fully clean, 7 partial. No reading of the file yields 18/24.

**Consequence:** the sentence reads as "PyFLP chokes on a quarter of his
library". The real hard-failure rate is under 8%. That number is what a reader
would use to judge whether the writing half of FL Studio work is viable.

---

### 5. `executor/handlers/whatsapp.py:160` is cited twice in `docs/plan.md` and points at the wrong code.

| field | content |
|---|---|
| where | `docs/plan.md`, `poller-dead-request-completion` and `router-deepseek-defer-not-skip`: "the only executor caller, `executor/handlers/whatsapp.py:160`, always passes `urgent=True`" |
| status | **DRIFTED** (line number; the underlying reasoning is correct) |

Evidence:

```
$ sed -n '155,165p' executor/handlers/whatsapp.py
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SeenMessageStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

$ grep -rn "urgent=" --include=*.py bus/ executor/ router/ tools/ voice/
executor/handlers/whatsapp.py:227:        return asyncio.run(route(task_profile, messages, urgent=True))
executor/poller.py:344:    return await route(task_profile, messages, urgent=urgent)
router/routing.py:186:            and self._deepseek_allowed(provider, urgent=urgent)
router/routing.py:207:        candidates = self.ordered_providers(task_profile, urgent=urgent, emergency=emergency)
router/routing.py:394:    return await ProviderRouter().route(task_profile, messages, urgent=urgent, **request_options)
```

The real line is **227**. Line 160 is inside `SeenMessageStore.__exit__`.

The *conclusion* both rows draw is still sound and was re-verified: nothing in
production calls `route()` with `urgent=False`, and `request_completion` has
zero non-test callers:

```
$ grep -rn "request_completion" --include=*.py bus executor router tools voice tests
executor/poller.py:340:async def request_completion(
tests/executor/test_poller.py:635:def test_request_completion_delegates_to_router_route_with_matching_arguments
tests/executor/test_poller.py:646:    result = asyncio.run(poller.request_completion("batch", messages))
tests/executor/test_poller.py:652:def test_request_completion_passes_urgent_through
tests/executor/test_poller.py:661:    asyncio.run(poller.request_completion("latency", [], urgent=True))
```

**Consequence:** the two rows that hold the router work back rest on a pointer
that lands on unrelated code. A reader who follows it and finds nothing may
conclude the "not yet buildable" note is stale and start building.

---

### 6. `docs/plan.md`'s cross-lane test-double index has rotted — the one section written to prevent a red tree.

| field | content |
|---|---|
| where | `docs/plan.md`, "Cross-lane test doubles": `tests/executor/test_poller.py:30`; `TurnStore` / `FactExtractor` / `ConversationMemory` doubles "live in … `tests/executor/test_whatsapp_handler.py:117,375,398`" |
| status | **DRIFTED** |

Evidence — each cited line, printed:

```
tests/db/test_jobs.py:27                    class InMemoryJobsRepository:          OK
tests/test_integration.py:11                class FakeJobs:                        OK
tests/test_integration.py:18                    return Job("job-1", kind, ...)     OK
tests/executor/test_poller.py:30            )                                      WRONG
tests/executor/test_distill_handler.py:59   class FakeQueue:                       OK
tests/executor/test_distill_handler.py:186  class FakeTurns:                       OK
tests/executor/test_distill_handler.py:210  class FakeExtractor:                   OK
tests/executor/test_whatsapp_handler.py:117 def test_extracts_sender_text_and_...  WRONG
tests/executor/test_whatsapp_handler.py:375 )                                      WRONG
tests/executor/test_whatsapp_handler.py:398 )                                      WRONG
executor/handlers/distill.py:112            class ChainQueue(Protocol):            OK
```

Actual locations:

```
$ grep -n "class Fake" tests/executor/test_poller.py
33:class FakeJobs:

$ grep -n "class .*:" tests/executor/test_whatsapp_handler.py
179:class FakeFact:
186:class FakeMemory:
208:class FakeSeenStore:
```

**Consequence:** this section exists because widening a `Protocol` once stranded
a double in a file no lane owned and shipped a red tree behind a green focused
run — the reason `.githooks/pre-commit` was written. Four of eleven pointers now
land on a closing paren or an unrelated test class. A lane following them
concludes the double is gone and does not update it.

---

### 7. Seven `docs/plan.md` rows still say "Done, **uncommitted**". All of it landed on 29 August.

| field | content |
|---|---|
| where | `docs/plan.md` lines 204, 205, 206, 352, 371, 398, 414, 419 |
| status | **DRIFTED** |

Evidence:

```
$ git log --oneline -1 -- tests/tools/test_distill_memory.py
c6565c0 Add coverage for distill_memory's CLI, start_jarvis's uncovered paths, and request_completion
$ git log --oneline -1 -- tools/context_status.py
a88dd21 Fix context_status --check being unreachable through main()
$ git log --oneline -1 -- bus/webhook_dedup.py
77c07e5 Stop a Meta webhook redelivery from enqueueing a second job
$ git log --oneline -1 -- bus/status.py
e4f15a7 Make queue_depths and retry_health O(1) queries, add distill-chain liveness
$ git log --oneline -1 -- tests/flp/test_flp_real.py
4f39697 Land the voice runtime, the fact-review path, and an FLP project inspector
$ git log --oneline -1 -- executor/flp/sort.py
ed08e62 Wire flp_sort's write-path guard and diff report, and fix stale docstrings
$ git status --short
 M docs/blockers/tool-result-injection.md
 M docs/context.md
 M docs/plan.md
 M docs/state.md
 M tests/db/test_jobs_integration.py
 M voice/audition_voices.py
 M voice/listen_wakeword.py
 M voice/try_stt.py
```

Nothing on that list is uncommitted. The only uncommitted code in the tree
belongs to the two lanes currently claimed on the board.

**Consequence:** CORE reads a backlog of unintegrated work that does not exist,
and may re-verify or redo it. `agents.md` names hand-maintained "still
uncommitted" claims as a specific banned category; these are the surviving ones.

---

### 8. `ProviderRouter` is instantiated in two places, not one — and `docs/plan.md` contradicts itself about it.

| field | content |
|---|---|
| where | `docs/plan.md`, `poller-dead-request-completion`: "`ProviderRouter` is only instantiated in `bus/main.py`" |
| status | **DRIFTED** |

Evidence:

```
$ grep -rn "ProviderRouter(" --include=*.py bus executor router tools voice
bus/main.py:85:    app.state.provider_router = provider_router or ProviderRouter()
router/routing.py:394:    return await ProviderRouter().route(task_profile, messages, urgent=urgent, **request_options)
```

`router/routing.py:394` is the module-level `route()` helper, and it is the
path `executor/handlers/whatsapp.py:227` takes on every live reply — so the
executor instantiates one per message. `docs/plan.md`'s own Decisions section
says exactly this ("Today `route()` builds a fresh router per call, so the
ledger dies each request"), so the two halves of the file disagree.

**Consequence:** someone scoping `router-shared-cooldown-ledger` from the
`poller-dead-request-completion` row believes there is one long-lived router in
the bus process. There is one throwaway router per reply, in the executor.

---

### 9. The rung count is 9, not 8, and `docs/state.md`'s rung table omits one.

| field | content |
|---|---|
| where | `docs/blueprint.md` Phase 0: "a minimal router module with the **8-rung** fallback chain"; §0.6: "`providers.yaml` with the **8 rungs**". `docs/state.md` Provider rungs table lists 8 rows. |
| status | **DRIFTED** (count) |

Evidence:

```
$ grep -n '"name":\|"priority"' router/providers.yaml
4:      "name": "groq",          7:      "priority": 1,
12:      "name": "cerebras",     15:      "priority": 2,
20:      "name": "nvidia_nim",   23:      "priority": 3,
28:      "name": "gemini",       31:      "priority": 4,
36:      "name": "openrouter",   39:      "priority": 5,
44:      "name": "mistral",      49:      "priority": 6,
54:      "name": "deepseek",     57:      "priority": 7,
63:      "name": "claude_max",   66:      "priority": 8,
73:      "name": "claude_api",   76:      "priority": 9,
```

Mistral was inserted at priority 6, shifting DeepSeek to 7, Claude Max to 8 and
Claude API to 9. `docs/state.md`'s Provider rungs table has rows for Groq,
Gemini, DeepSeek direct, OpenRouter, Cerebras, Mistral, NVIDIA NIM and Claude
Max — **`claude_api` (priority 9, `ANTHROPIC_API_KEY`) is missing entirely.**

This is a count, not an architecture objection: the ladder itself is a
blueprint decision and is not being questioned here.

**Consequence:** anyone reasoning about fallback order below Mistral is off by
one, and a reader of `docs/state.md` does not know a ninth configured rung
exists in `providers.yaml`.

---

### 10. Test counts, four of them wrong.

| field | content |
|---|---|
| where | `docs/state.md`: "**77 offline tests** against fakes" (system control). `docs/context.md`: "`tools/flp_inspect.py` … now has **28 tests**". `docs/plan.md`: "**11 → 28 tests**" (start_jarvis); "**11 new tests**" (webhook dedup). |
| status | **DRIFTED** |

Evidence:

```
$ .venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp=.pytest-basetemp-audit --collect-only -q tests/executor/system_control
80 tests collected in 0.05s

$ ... --collect-only -q tests/tools/test_flp_inspect.py
30 tests collected in 0.03s

$ ... --collect-only -q tests/tools/test_start_jarvis.py
38 tests collected in 0.02s

$ ... --collect-only -q tests/bus/test_webhook_dedup.py
8 tests collected in 0.02s
$ git show 77c07e5 -- tests/ | grep -c "^+.*def test_"
14
```

The system-control number is not staleness — that directory has not been
touched since it landed:

```
$ git log --oneline -- tests/executor/system_control
0391f3f Land desktop automation, the typing-cue fix, and NPU voice STT
```

77 was simply a miscount; the real figure is 80. `flp_inspect` is 30, not 28.
`test_start_jarvis.py` is now 38, past the "→ 28" the row records. The webhook
dedup commit added 14 test functions across two files, not 11.

**Consequence:** low individually. Together they mean no count in these
documents can be cited without recounting — which is the whole reason
`agents.md` forbids hand-maintained test counts.

---

### 11. Minor: `.venv311` is described as "two packages wide". It pins 15.

| field | content |
|---|---|
| where | `docs/state.md`, This machine and network: "`.venv311` … holds only `pyflp` and `pytest` (`requirements-flp.txt`) … that environment is offline, off `PATH`, **two packages wide**" |
| status | **DRIFTED** (precision) |

Evidence:

```
$ grep -v "^#" requirements-flp.txt | grep -v "^$"
pyflp==2.2.1
pytest==9.1.1
arrow==1.4.0            colorama==0.4.6         construct==2.10.70
construct-typing==0.8.1 iniconfig==2.3.0        packaging==26.3
pluggy==1.6.0           Pygments==2.21.0        python-dateutil==2.9.0.post0
six==1.17.0             sortedcontainers==2.4.0 typing_extensions==4.16.0
tzdata==2026.3
```

Two *direct* dependencies, 15 pinned packages. The safety argument
(offline, off `PATH`, reads only the user's own `.flp` copies) is unaffected.

---

## Confirmed accurate

Compact list. These were checked against the tree and hold. No evidence dumps.

**`docs/state.md` — Built and working**

- FastAPI bus: HMAC on the webhook, bearer elsewhere, request-ID JSON logging,
  protected `/status`.
- Migrations `0001` and `0002` exist and contain what the row describes:
  the `jobs` schema, `claim_next_job` ordering `run_after asc, created_at asc`,
  **no priority column**, RLS on with explicit revokes, service-role-only RPCs,
  and `0002`'s `attempts` / `max_attempts` / `dead_letter` / `retry_or_dead_letter_job`.
  (*Applied live* is unverified — see Not checked.)
- `SUPABASE_QUEUE_TIMEOUT_SECONDS`, and `postgrest 1.1.1` under `supabase 2.18.1`.
- Executor topology: `whatsapp-worker` is `--kind whatsapp_webhook`,
  `background-worker` is `--kind distill_memory`, and **only** the latter seeds
  the chain (`seeds_distill = args.kind in (None, DISTILL_JOB_KIND)` in
  `executor/poller.py`). The webhook is enqueue-only. *(The "not live" half of
  that same row is finding 1.)*
- `assert_timeouts_ordered` has both callers claimed: startup at
  `executor/poller.py:249`, per-row at `executor/handlers/distill.py:234`.
- `executor/handlers/distill.py:112 ChainQueue` — exact line, exact name.
- The distill successor's write-site veto and its `may_write` check.
- Batch-tool liveness guards: `tools/run_backfill.py` imports
  `refuse_if_executor_is_live`, has `--force`, and never blocks `--dry-run`.
- Conversation wiring: `<remembered_context>` fence markers exist at
  `executor/handlers/whatsapp.py:363-364`; recalled memory is appended with
  `"role": "user"`; the handler docstring and code confirm
  cue → recall → route → send → remember; both dedup layers exist
  (`bus/webhook_dedup.py` `SeenWebhookMessageStore`, and `SeenMessageStore` in
  the handler).
- `WhatsAppClient` has all five claimed methods: `send_text_message`,
  `show_typing_indicator`, `download_media`, `upload_media`, `send_voice_note`.
- Process tooling: `tools/consult.py` passes the prompt via `input=prompt` on
  stdin with an explicit comment saying never in argv.
- Work-board claim tool exists and runs; `.work-board/` is gitignored.
- `/status` reports `retry_health`, and `_QUEUE_STATUSES` includes `dead_letter`.
- FLP sort: `ReorderNotSupported`, `FlpSortPathOutsideRoot`, `flp_sort_root()`
  reading `JARVIS_FLP_SORT_ROOT`, `write_diff_report()`, registered as
  `flp_sort`, **27 tests** in `tests/executor/test_flp_sort.py` (exact), and
  `test_projects/FL 20.8.4.flp` present.
- Startup: `--protocol http2` with `JARVIS_TUNNEL_PROTOCOL` /
  `DEFAULT_TUNNEL_PROTOCOL = "http2"`.
- Single-instance guard: `DEFAULT_SINGLETON_PORT = 8765`,
  `JARVIS_SINGLETON_PORT`, `netstat -ano` for the holding PID, and an explicit
  "No SO_REUSEADDR here, ever" comment. Confirmed **working in production** —
  `tools/start_jarvis.launch.log` contains a real refusal naming PID 31492 and
  stating nothing was started and no tunnel minted.
- Wake word: `openwakeword 0.6.0` installed and
  `hey_jarvis_v0.1.onnx` / `.tflite` present in its own package resources.
- TTS voice: `DEFAULT_TTS_VOICE = "am_puck"` at `voice/config.py:145`, env
  `JARVIS_TTS_VOICE`.
- STT language: `DEFAULT_WHISPER_LANGUAGE = "ur"` at `voice/config.py:90`.
- Bus logging: `_VERIFY_TOKEN_QUERY_PARAM = re.compile(r"(hub[._]verify_token=)[^&\s\"]+")`
  — matches both spellings, and `hub[._]challenge` is deliberately untouched.
- WhatsApp voice wiring: `voice/audio.py`, `voice/speak.py`,
  `voice/whisper/server_client.py` all exist; the handler transcribes before
  recall, treats a blank transcript as a logged no-op, and appends an
  English-only instruction to the voice reply's prompt only.
- `whisper-server` is spawned `optional=True`, with an explicit comment that a
  dead or never-ready server must degrade rather than take the stack down.
- Desktop app automation: **45 tests, 43 offline, exactly 2 `guiauto`-deselected**
  — matched the claim exactly. Deps `pywinauto==0.6.9`, `comtypes==1.4.16` pinned.
- Pinned deps all match: `soundfile==0.14.0`, `mem0ai==2.0.19`,
  `supabase==2.18.1`, `openwakeword==0.6.0`, `pyflp==2.2.1`.

**`docs/state.md` — Provider rungs**

- The entire `*_DEFAULT_MODEL` gap note is accurate, end to end. All five keys
  (`GROQ_`, `CEREBRAS_`, `NVIDIA_`, `GEMINI_`, `CLAUDE_API_DEFAULT_MODEL`) are
  absent from `.env` — checked by key name only, no values read. `MISTRAL_DEFAULT_MODEL`
  is absent too. `providers.yaml` resolves each of those five via `${VAR}` with
  no literal fallback; OpenRouter (`openrouter/free`) and DeepSeek
  (`deepseek-v4-flash`) are literals, exactly as claimed.
- Both cited line ranges are **exact**: `_configured()` at
  `router/routing.py:246-257` (its `model_env` guard does cover only Mistral),
  and the `if not provider_model` fallthrough at `routing.py:216-218`.
- `tests/live/` does contain exactly one test file,
  `test_memory_roundtrip.py`, and it does not touch routing.

**`docs/state.md` — This machine and network**

- `.venv` is **Python 3.12.10**; `.venv311` is **CPython 3.11.5**. Exact.
- `pytest.ini`'s `addopts` carries only the marker filter, so the documented
  `-p no:cacheprovider --basetemp=…` really is required by hand.
- `memory.db`, `*.seen-messages.db`, `test_projects/`, `.work-board/`, wake-word
  clips and `ingest/data/` (via its own `.gitignore`) are all ignored. `.env` is
  the first line of `.gitignore`.

**`docs/plan.md`**

- **Every commit hash cited resolves.** All 15 checked
  (`1672f8c ae158b9 b9458fb c47d9b4 ed08e62 e4f15a7 1cb18ed c6565c0 49719b9
  14629c0 608dfd7 0391f3f 4f39697 628b6ea 52e2c03`), and each subject line
  matches the work the row describes.
- `router-deepseek-weekday-gate` / `-402-aborts-chain` / `-model-env-validation`
  are genuinely done: `_deepseek_allowed`'s weekend short-circuit is at
  `router/routing.py:296-305` — **the cited range is exact** — and
  `_configured()` has the `model_env` exclusion.
- `poller-dead-request-completion`: `request_completion` still has zero
  production callers. Confirmed.
- `.env.example` batch: the 18 listed variables are present; `SUPABASE_KEY`'s
  only surviving reference is `tests/db/test_jobs.py:227`, asserting it is
  *not* used — exactly as the row says.
- `bus/status.py` batch: `distill_chain_health()` exists at `bus/status.py:103`,
  is wired additively into `status_payload`/`create_status_handler`, has the
  matching `bus/main.py` param, and `tests/status/test_live_queue_status.py`
  collects **9** tests. `QueueStatusReader.from_repository` does reach into
  `repository._client`.
- `tests/tools/test_distill_memory.py` collects **12**. Exact.
- Barrier `pytest-ini-carries-local-flags`: confirmed real — `addopts` is
  `-m "not live and not realflp and not guiauto"` and carries neither flag.
- Barrier `live-schema-drift-guard`: the `--ignore=tests/db/test_jobs_integration.py`
  is present in `.githooks/pre-commit` verbatim, and
  `tests/db/test_jobs_integration.py:114` was `pytest.skip(` **at HEAD** —
  the citation was accurate when written; the in-flight lane is rewriting the
  file right now, which is why the line no longer matches the worktree.
- "In flight, 1 September 2026" is **currently true**: `work_board_claim.py list`
  shows live claims for `voice-cli-tests` and `live-schema-drift-guard`, on
  exactly the paths the table names.
- `voice/try_stt.py` **183** lines, `listen_wakeword.py` **164**,
  `audition_voices.py` **128** at HEAD — all three exact — and every other
  module in `voice/` did have a test file. (Worktree copies are now longer;
  that is the claimed lane working.)
- Every `docs/` path referenced across all four documents exists: 4 history
  files, 4 blockers, 9 task briefs and reports, 2 consult directories,
  `.githooks/pre-commit`, `docs/tasks/flp-audit-data.json`.

**`docs/context.md`**

- `tools/flp_inspect.py` is genuinely read-only — no `.save(`, no write-mode
  `open()`, no `write_text`, no `shutil.copy`, no `os.remove`.
- It did land in `52e2c03`, as claimed.
- `queue-sleep-wake-probe` really does have **no evidence anywhere**: the only
  mentions of it in `docs/` are in `blueprint.md`, `context.md`, `plan.md` and
  one consult prompt. No history file, no test, no log.
- The verify-token redaction fix it describes is in the tree (both spellings).

**`docs/blueprint.md` — tree-factual claims**

- §"routing pattern" rung 7: "implemented 26 August 2026 as `tools/consult.py`"
  — the file exists and is the consult path `agents.md` mandates.
- §0.4's `jobs` schema spec matches `db/migrations/0001_jobs.sql` field for
  field, including the `(status, run_after)` index.
- §0.5's bus hardening list, §3's "launcher supervises both processes
  independently" and "the unfiltered poller CLI remains available" all hold.
- §"Ongoing"'s monthly facts-check job is correctly described everywhere as not
  built; `docs/plan.md` already says so.

**No drift found in:** `docs/state.md`'s *Meta account* section (all of it is
account state that cannot be settled from the tree — see below), and
`docs/context.md`'s *Where facts go* table.

---

## Not checked, and why

Each of these needs a resource this lane did not claim, or is not settleable by
reading the tree.

**Provider capacity — deliberately not spent.** `agents.md` says provider
pricing, rate limits, model names and free tiers are claims to re-verify; the
brief says verifying them spends real allowance on an unclaimed exclusive
resource. **No provider was called.** Unverified as a result:

- `docs/state.md` Provider rungs: every "Working" / `402 payment_required` /
  `403` claim, for Groq, Gemini, DeepSeek direct, OpenRouter, Cerebras, Mistral.
  The `*_DEFAULT_MODEL` gap note directly undermines the Groq and Gemini
  "Working" claims on config grounds alone, and `docs/state.md` already says so.
- The current-model-ID research in the same section (Groq's
  `llama-3.1-8b-instant` deprecated, `gemini-2.0-flash` shut down 1 June 2026).
  Both are dated 2026-08-28 and are now four days old at minimum.
- Every price, rate limit, RPD/TPM/TPD figure and free-tier claim in
  `docs/blueprint.md` — DeepSeek's Aug-16 repricing, Groq's per-model caps,
  Cerebras' 5 RPM / 30K TPM, OpenRouter's 50/day, NIM's ~40 RPM, Mistral's
  ~50K TPM, Oracle Always Free's 2 OCPU/12GB, Hetzner's PKR 1,240, the
  PKR 278/USD rate, and the Agent SDK billing-split pause. **These are exactly
  what `facts-check-job` was specified to re-verify monthly, and it has never
  run.** They are the single largest block of unverified claims in the docs.
- `docs/blueprint.md`'s +50% weekly Claude promo "currently extended through
  ~Aug 31 2026" — that date has now passed. Flagged on its face, not verified.

**Live systems — read-only constraint.**

- "Migrations `0001` and `0002` **applied live**", RLS state, and the live
  `jobs` table's contents. Would require touching the live Supabase project.
- "The callback must be re-pointed after Quick Tunnel recovery; no current
  callback read-back has been verified" — needs a Graph API call and
  `meta-webhook`, neither claimed.
- The entire *Meta account* section (app in development, allow-list, system
  user, token validity and `expires_at: 0`, dashboard paths). All Meta-side
  state; also secret-adjacent.
- "Ollama 0.32.15 and `nomic-embed-text` are active on loopback" — reading the
  version requires talking to the Ollama server, which the brief forbids
  starting.
- "Supabase connectivity is intermittently flaky here" — needs live network
  attempts over time.
- Open blocker 3, "the tunnel is ephemeral" — structurally true and not
  re-provable without minting a tunnel.

**Physical and sensory.**

- The wake-word result (7/7 detections, 0.873–0.993) and the false-positive rate
  — mic, and Ali's ears.
- `am_puck` chosen by ear, and the live voice-note playback confirmation.
- Kokoro's "54 installed packs" — the voice-pack directory was not located
  without importing Kokoro, which pulls a heavy model stack; not worth the
  machine time for a cosmetic count.
- NPU numbers (12.4x encoder speedup, 87.5s → 7.1s, 186.8s vs 32.4s) — would
  require running the NPU build, which the brief excludes.

**Test suites not executed.**

- `tests/flp/test_flp_real.py`'s claimed "4 passed" under `.venv311` — the
  file and its `realflp` marker exist and were confirmed; the suite itself was
  not run, to avoid a second concurrent `.venv311` pytest beside other lanes.
- `tests/live/` — `live`-marked, needs Ollama and Supabase.
- The full offline suite was not run. Two other lanes had uncommitted work in
  the tree throughout this audit, so a suite result here would describe their
  in-progress state, not HEAD. `--collect-only` was used for every count, under
  `--basetemp=.pytest-basetemp-audit`.

**Out of scope by instruction.**

- `docs/history/` — append-only, preserves superseded and wrong conclusions
  deliberately. Not audited, not corrected.
- Every architecture, component and phase-ordering decision in
  `docs/blueprint.md`. Nothing in this report proposes substituting any of them.
  Finding 2 and finding 9 report a *divergence between the doc and the tree*;
  which side should move is not this lane's call.
- `.env` values. Only key *names* were tested, with `grep -c "^KEY="`. No value
  was read, printed or logged.

---

## Scorecard

| document | claims checked | drifted | confirmed |
|---|---|---|---|
| `docs/state.md` | ~55 | 5 | ~50 |
| `docs/plan.md` | ~40 | 5 | ~35 |
| `docs/context.md` | ~10 | 1 (two numbers) | ~9 |
| `docs/blueprint.md` (tree-factual only) | ~10 | 2 | ~8 |

Roughly **88% of what was checkable came back accurate**, and the accurate part
includes every commit hash, every referenced file path, and three of four cited
line ranges in `router/routing.py` down to the exact line. The drift is
concentrated in two places: **counts** (five wrong), and **uniqueness claims**
("the only call site", "only instantiated in", "claims every other kind") —
which are the claims most likely to be true when written and false a week later,
and the ones a reader is least likely to re-check.
