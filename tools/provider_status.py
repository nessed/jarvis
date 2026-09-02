"""Generate `docs/state.md`'s two provider lists instead of hand-writing them.

Blueprint §3.3, Ali's text: the provider lists "are generated from the running
config, not maintained by hand here", and "`docs/state.md` carries two lists:
routable, and configured-but-not-routable with a reason and a date per entry."

`blueprint-corrections` deliberately left them empty on 2 Sep 2026 rather than
type them out, because hand-maintaining a list the spec calls generated breaks
the rule in the act of obeying it. This is what fills them.

Why it earns its keep
---------------------
Twice in one week the same shape of bug went unnoticed: a provider is
configured, cannot actually serve a request, and nothing says so.

- `groq`, `cerebras` and `gemini` sorted to the front of every request and
  were skipped for an unresolvable model. The skip *was* recorded — in a
  failure list rendered only when every provider failed, so the ladder working
  was what hid it.
- `openrouter/free` answered a structured-output prompt with
  `User Safety: safe` on two of four probes.

A generated "configured-but-not-routable, with a reason" list is exactly the
artefact that would have surfaced the first without anyone probing for it.

Sources, and one thing it must never read
-----------------------------------------
Three inputs: `router/providers.yaml`, the environment, and the live health
snapshot `router/health_report.py` publishes.

**Environment key _names_ only.** This tool decides whether a variable is set,
never what it holds, and no value ever reaches the output or a log line. That
is not caution about this tool in particular — it writes into a file that is
committed.

The reason vocabulary is `ProviderRouter.unroutable_reasons()`, so this tool
and the router cannot disagree about why a rung is unusable. Cooldowns are
added here rather than there: a cooling rung *is* routable and merely resting,
which is a distinction the router needs and a status report should still show.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from router import health_report
from router.routing import ProviderRouter, load_providers

BEGIN = "<!-- BEGIN GENERATED: tools/provider_status.py. Do not edit by hand. -->"
END = "<!-- END GENERATED: tools/provider_status.py -->"
STATE_PATH = Path("docs/state.md")


def rows(
    *,
    environ: Mapping[str, str] | None = None,
    snapshot: Mapping[str, Mapping[str, object]] | None = None,
    manifest_path: Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The two lists: routable, and configured-but-not-routable with a reason.

    Returns plain dicts rather than rendered lines so the shape can be tested
    without parsing markdown back out of a document.
    """
    providers = load_providers(manifest_path, environ=environ)
    router = ProviderRouter(providers, environ=environ)
    reasons = router.unroutable_reasons()
    health = dict(snapshot or {})

    routable: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = []
    for provider in providers:
        entry = health.get(provider.name) or {}
        if provider.name in reasons:
            blocked.append(
                {
                    "name": provider.name,
                    "cost_class": provider.cost_class,
                    "reason": reasons[provider.name],
                }
            )
            continue
        routable.append(
            {
                "name": provider.name,
                "cost_class": provider.cost_class,
                "state": _routable_state(entry),
            }
        )
    return routable, blocked


def _routable_state(entry: Mapping[str, object]) -> str:
    """What the live ledger says about a rung that *is* eligible.

    "Never verified" is a real state and the most important one here: a rung
    with a key, a model and no cooldown looks identical to a working rung right
    up until the first request, and §3.3 asks for exactly that distinction.
    """
    if not entry or not entry.get("reported"):
        cooling = 0.0
    else:
        raw = entry.get("cooldown_seconds_remaining")
        cooling = float(raw) if isinstance(raw, (int, float)) else 0.0

    last_status = entry.get("last_status") if entry else None
    if cooling > 0:
        return f"in cooldown, {round(cooling)}s left after HTTP {last_status}"
    if last_status is None:
        return "never verified — no request has reached it in this reporting window"
    if last_status == 200:
        return "verified, last call HTTP 200"
    return f"eligible, last call HTTP {last_status}"


def render(
    *,
    environ: Mapping[str, str] | None = None,
    snapshot: Mapping[str, Mapping[str, object]] | None = None,
    manifest_path: Path | None = None,
    today: str | None = None,
) -> str:
    """The generated block, markers included."""
    routable, blocked = rows(environ=environ, snapshot=snapshot, manifest_path=manifest_path)
    stamp = today or datetime.now(UTC).strftime("%Y-%m-%d")

    lines = [BEGIN, "", f"_Generated by `tools/provider_status.py` on {stamp}._", ""]

    lines += ["**Routable**", ""]
    if routable:
        lines += ["| Rung | Cost class | State |", "|---|---|---|"]
        lines += [f"| `{r['name']}` | {r['cost_class']} | {r['state']} |" for r in routable]
    else:
        lines.append("_None. Every rung in the manifest is blocked; see below._")
    lines.append("")

    lines += ["**Configured but not routable**", ""]
    if blocked:
        lines += ["| Rung | Cost class | Reason | As of |", "|---|---|---|---|"]
        lines += [
            f"| `{b['name']}` | {b['cost_class']} | {b['reason']} | {stamp} |" for b in blocked
        ]
    else:
        lines.append("_None. Every rung in the manifest is routable._")

    lines += ["", END]
    return "\n".join(lines)


def splice(text: str, block: str) -> str:
    """Replace the generated block, refusing to guess where it goes.

    Same discipline as ``tools/context_status.py``: the markers must already be
    in the file. A generator that inserts its own block on first run would put
    it wherever the code happened to look, and nobody would notice until the
    document read strangely.
    """
    start = text.find(BEGIN)
    end = text.find(END)
    if start == -1 or end == -1:
        raise SystemExit(
            f"{STATE_PATH} has no generated provider block. Add the BEGIN and "
            "END markers before running this."
        )
    return text[:start] + block + text[end + len(END) :]


def check(current: str) -> int:
    """Is the block present and machine-written?

    Deliberately weaker than a byte comparison against a fresh render. The
    block's content depends on the live health snapshot, which changes between
    requests, so demanding equality would fail constantly and teach everyone to
    ignore it — the failure ``tools/context_status.py`` documents at length.
    What is checked is that the block exists and still has the shape this tool
    produces, which catches the thing that actually goes wrong: someone editing
    it by hand.
    """
    if BEGIN not in current or END not in current:
        print(f"{STATE_PATH} has no generated provider block", file=sys.stderr)
        return 1
    block = current.split(BEGIN, 1)[1].split(END, 1)[0]
    for required in ("_Generated by `tools/provider_status.py` on", "**Routable**",
                     "**Configured but not routable**"):
        if required not in block:
            print(
                f"the generated provider block is missing {required!r}; it was hand-edited",
                file=sys.stderr,
            )
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="splice into docs/state.md")
    parser.add_argument("--check", action="store_true", help="is the block present and machine-written")
    args = parser.parse_args(argv)

    if args.check:
        return check(STATE_PATH.read_text(encoding="utf-8"))

    # Only in main(): `render` and `rows` take their environment explicitly so
    # the tests stay hermetic and cannot be coloured by whatever is in `.env`
    # on the machine running them.
    from dotenv import load_dotenv

    load_dotenv()

    block = render(snapshot=health_report.read() or {})
    if not args.write:
        print(block)
        return 0

    text = STATE_PATH.read_text(encoding="utf-8")
    STATE_PATH.write_text(splice(text, block), encoding="utf-8")
    print(f"refreshed the provider lists in {STATE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
