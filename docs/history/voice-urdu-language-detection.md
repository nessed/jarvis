# Urdu speech-to-text: two encoding bugs and one unsolved tradeoff — 29 Aug 2026

Frozen record. Append-only.

## Summary

Ali reported "urdu is bad english is accurate asf" after first trying local
speech-to-text. Two of the three causes were bugs in this repo, not the model.
The third is a real, still-open design decision.

## Bug 1 — the transcript was destroyed after a successful transcription

`subprocess.run(..., text=True)` decodes with the locale codec. On this machine
that is **cp1252**, which cannot represent Urdu, Arabic, or any non-Latin script.
whisper.cpp emits UTF-8.

Symptom, from Ali's terminal:

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x81 in position 71
  --------------------------------------------------------------
  (nothing recognised)
```

The NPU had already finished and produced Urdu text. The decode blew up on the
way back and the CLI reported `(nothing recognised)` — indistinguishable, to the
user, from the model failing. **Urdu had been working and was never seen.**

Fixed in both runners by passing `encoding="utf-8", errors="replace"`:

- `voice/whisper/local_backend.py` `LocalWhisperBackend._run`
- `voice/benchmark_stt.py` `WhisperCppBackend._run`

## Bug 2 — printing the transcript failed the same way

Fixing the read exposed the mirror-image bug on the write side: a correct Urdu
string still raised `UnicodeEncodeError` at `print()`, because the console
encoding is also cp1252. Found by testing with real Urdu rather than assuming
bug 1 was the whole story.

Fixed by `_force_utf8_console()` in `voice/try_stt.py`, which reconfigures
stdout/stderr to UTF-8 and tolerates an already-wrapped or redirected stream.
Verified:

```
EXTRACTED: میں ٹھیک ہوں شکریہ
```

**Both bugs are the same root cause seen twice.** Any future code that moves a
transcript between a process and a terminal on this machine has to state its
encoding explicitly. The locale default is wrong for the languages this project
exists to handle.

## The real finding — auto-detect silently deletes Urdu

With both bugs fixed, one 10-second clip of Ali speaking mixed Urdu/English,
transcribed three ways from the **same recording**:

| setting | result |
|---|---|
| auto-detect | `Is that like the manufacturing process?` |
| forced Urdu (`-l ur`) | `تو پھر لیکن اس کو کیا لگانی ہے؟ اس کا منیفیکشن پروسیس ہے؟` |
| forced English (`-l en`) | `Is that like the manufacturing process?` |

Auto-detect classified a predominantly Urdu clip as English, kept the two
English words, and **dropped the entire Urdu sentence**. Forced Urdu recovered
the whole utterance, transliterating the English term into Urdu script.

Whisper commits to one language per clip. Ali code-switches mid-sentence, which
is the case that breaks.

## Why forcing Urdu is not simply the answer

The same forced-`ur` setting on a pure-English clip (whisper.cpp's own
`samples/jfk.wav`) does not transcribe — it *translates*, and degenerates into a
repetition loop:

```
اور اسی طرح میرے امریکیانوں میں اسی طرح میرے امریکیانوں میں اسی طرح ...
```

versus the correct `-l en` / auto result on the identical file:

```
And so my fellow Americans, ask not what your country can do for you,
ask what you can do for your country.
```

So:

| | Urdu speech | English speech |
|---|---|---|
| `auto` | deletes it | correct |
| `-l ur` | correct | garbage |

Neither default is right for a bilingual speaker. **The default was left at
`auto`** — unchanged, deliberately, because changing it trades one failure for
another and the choice depends on how Ali actually speaks to JARVIS.

## Open decision — Ali's, not an agent's

Asked and not yet answered: *when you talk to JARVIS, will it be mixed Urdu and
English like that clip, or mostly English?*

- **Mostly mixed Urdu** -> default `-l ur` and accept degraded pure-English.
- **Mostly English** -> keep `auto` and accept that Urdu-heavy clips lose content.
- **Genuinely both** -> the retry heuristic sketched below.

**Proposed heuristic, designed but NOT built:** transcribe on `auto`, then
compare the transcript's word count against the clip duration. Auto returned six
words for ten seconds of continuous speech, which is the signature of dropped
content. Below a threshold, retry with `-l ur` and keep that result. It costs a
second pass only when the first is probably wrong, and both failure modes are
loud enough to detect. It is a heuristic, not a fix, and it should not be built
until Ali answers the question above — building it first would be substituting
an interpretation for his answer.

## Also recorded

`voice/try_stt.py` was added this session: record from the mic, transcribe on
the NPU, print. Flags `--language` and `--compare` exist specifically because of
this investigation — `--compare` runs one recording through auto, Urdu and
English so the language hint is the only variable, rather than comparing two
different takes of a sentence.

Timings observed, unoptimised, with other work running on the machine: ~22s
forced-language, ~30s auto, ~2.9x real time on a 10s clip. Most of that is model
reload per invocation; `whisper-server` exists and was not wired up.
