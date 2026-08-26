"""Autonomous second opinion. Replaces the human relay to Claude web.

The manual loop this removes: copy terminal output into a browser, paste it
into a stronger model, read the answer, paste it back. That makes the human a
network hop between two models. ``claude -p`` is subscription-backed and
scriptable, so an agent can take that hop itself.

Usage
-----
    .venv\\Scripts\\python.exe tools/consult.py "question" [options]

    --file PATH        attach a file's contents (repeatable)
    --tail PATH[:N]    attach the last N lines of a file, default 200 (repeatable)
    --cmd "..."        run a command and attach its exit code + output (repeatable)
    --model NAME       default: opus
    --slug NAME        directory name suffix; default derived from the question
    --timeout SECONDS  default: 600
    --dry-run          assemble and screen the prompt, print it, call nothing

Output
------
Writes ``docs/consults/<YYYY-MM-DD>-<slug>/`` containing ``prompt.md``,
``response.md`` and ``verdict.json``, and prints the verdict to stdout. The
verdict is structured so a calling agent can branch on it without parsing
prose::

    {"verdict": ..., "reasoning": ..., "confidence": "high|medium|low",
     "what_would_change_this": ...}

Secret discipline
-----------------
Nothing leaves this machine unscreened. ``.env``-like files are refused
outright; every attached byte is scanned against the live values in ``.env``
and against common key shapes, and any match is replaced with a redaction
marker before assembly. Redactions are reported by variable name only, never
by value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSULT_ROOT = REPO_ROOT / "docs" / "consults"

# Files that are secrets by definition; never attachable regardless of content.
REFUSED_NAMES = {".env", ".env.local", ".env.production", "credentials.json", "id_rsa"}

# Shapes that look like credentials even when they are not in .env — a leaked
# key pasted into a log would otherwise sail straight through.
SECRET_SHAPES = [
    ("openai-style", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("groq-style", re.compile(r"\bgsk_[A-Za-z0-9_\-]{16,}")),
    ("meta-graph", re.compile(r"\bEAA[A-Za-z0-9]{40,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("google-api", re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}")),
]

RESPONSE_CONTRACT = """
Answer as strict JSON and nothing else. No prose before or after, no code
fence. Exactly these keys:

{
  "verdict": "the decision or answer, one or two sentences, actionable",
  "reasoning": "why, citing the specific evidence above that drove it",
  "confidence": "high | medium | low",
  "what_would_change_this": "the concrete observation that would flip this verdict"
}

Set confidence to low rather than guessing. If the evidence provided is not
enough to decide, say exactly what is missing in what_would_change_this — that
is a useful answer, an invented one is not.
""".strip()


def load_env_values() -> dict[str, str]:
    """Read .env for redaction only. Values are never printed or written out."""
    env_path = REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        value = raw.strip().strip("'").strip('"')
        # Short values produce false positives ("true", "1", a port number).
        if len(value) >= 12:
            values[name.strip()] = value
    return values


def screen(text: str, env_values: dict[str, str]) -> tuple[str, list[str]]:
    """Redact known secret values and secret-shaped strings. Returns (text, findings)."""
    findings: list[str] = []
    for name, value in env_values.items():
        if value and value in text:
            text = text.replace(value, "<redacted:" + name + ">")
            findings.append(name)
    for label, pattern in SECRET_SHAPES:
        if pattern.search(text):
            text = pattern.sub("<redacted:" + label + ">", text)
            findings.append("shape/" + label)
    return text, findings


def read_attachment(spec: str, kind: str, env_values: dict[str, str]):
    if kind == "tail":
        raw_path, _, count = spec.rpartition(":")
        if raw_path and count.isdigit():
            path, lines = Path(raw_path), int(count)
        else:
            path, lines = Path(spec), 200
    else:
        path, lines = Path(spec), 0

    if path.name in REFUSED_NAMES:
        print("refusing to attach " + path.name + ": secrets are never sent off-machine", file=sys.stderr)
        return None
    if not path.exists():
        print("skipping missing attachment: " + str(path), file=sys.stderr)
        return None

    body = path.read_text(encoding="utf-8", errors="replace")
    if lines:
        body = "\n".join(body.splitlines()[-lines:])
    body, findings = screen(body, env_values)
    label = path.as_posix() + (" (last %d lines)" % lines if lines else "")
    return "### " + label + "\n\n```\n" + body + "\n```", findings


def run_attachment(command: str, env_values: dict[str, str]) -> tuple[str, list[str]]:
    completed = subprocess.run(
        command, shell=True, cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    output, findings = screen(output, env_values)
    section = (
        "### $ " + command + "\n\nexit code: " + str(completed.returncode)
        + "\n\n```\n" + output.strip() + "\n```"
    )
    return section, findings


def build_prompt(question: str, sections: list[str]) -> str:
    parts = [
        "You are a second opinion on a decision inside an AI-agent-built project.",
        "The agent asking has already gathered the evidence below and could not",
        "resolve the question from it alone. Do not restate the evidence. Decide.",
        "",
        "## Question",
        "",
        question.strip(),
    ]
    if sections:
        parts += ["", "## Evidence", ""] + sections
    parts += ["", "## Response format", "", RESPONSE_CONTRACT]
    return "\n".join(parts)


def parse_verdict(raw: str) -> dict:
    """Pull the JSON verdict out of whatever the model returned."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {
            "verdict": raw.strip(),
            "reasoning": "model did not return the requested JSON; raw text preserved",
            "confidence": "low",
            "what_would_change_this": "a re-run that honours the response contract",
        }
    if not isinstance(parsed, dict):
        parsed = {"verdict": str(parsed)}
    for key in ("verdict", "reasoning", "confidence", "what_would_change_this"):
        parsed.setdefault(key, "")
    return parsed


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(slug.split("-")[:6]) or "consult"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ask a stronger model for a structured second opinion, without a human relay."
    )
    parser.add_argument("question")
    parser.add_argument("--file", action="append", default=[], metavar="PATH")
    parser.add_argument("--tail", action="append", default=[], metavar="PATH[:N]")
    parser.add_argument("--cmd", action="append", default=[], metavar="COMMAND")
    parser.add_argument("--model", default="opus")
    parser.add_argument("--slug", default=None)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env_values = load_env_values()
    sections: list[str] = []
    findings: list[str] = []

    for spec in args.file:
        result = read_attachment(spec, "file", env_values)
        if result:
            sections.append(result[0])
            findings += result[1]
    for spec in args.tail:
        result = read_attachment(spec, "tail", env_values)
        if result:
            sections.append(result[0])
            findings += result[1]
    for command in args.cmd:
        section, found = run_attachment(command, env_values)
        sections.append(section)
        findings += found

    if findings:
        unique = sorted(set(findings))
        print(
            "screened %d secret(s) before sending: %s" % (len(unique), ", ".join(unique)),
            file=sys.stderr,
        )

    prompt = build_prompt(args.question, sections)

    if args.dry_run:
        print(prompt)
        return 0

    outdir = CONSULT_ROOT / (date.today().isoformat() + "-" + (args.slug or slugify(args.question)))
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "prompt.md").write_text(prompt, encoding="utf-8")

    print(
        "consulting %s (%d chars, %d attachment(s))..." % (args.model, len(prompt), len(sections)),
        file=sys.stderr,
    )
    # On Windows the CLI is installed as claude.cmd; a bare "claude" is a shell
    # shim that subprocess cannot exec directly.
    executable = shutil.which("claude") or shutil.which("claude.cmd")
    if not executable:
        print("claude CLI not found on PATH; cannot consult", file=sys.stderr)
        return 2

    try:
        completed = subprocess.run(
            [executable, "-p", prompt, "--output-format", "json", "--model", args.model],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
            env={**os.environ, "CLAUDE_CODE_ENTRYPOINT": "consult"},
        )
    except FileNotFoundError:
        print("claude CLI not found on PATH; cannot consult", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print("consult timed out after %ds" % args.timeout, file=sys.stderr)
        return 3

    if completed.returncode != 0:
        print(completed.stderr.strip()[:2000], file=sys.stderr)
        return completed.returncode

    try:
        envelope = json.loads(completed.stdout)
        raw_result = envelope.get("result", completed.stdout) if isinstance(envelope, dict) else completed.stdout
    except json.JSONDecodeError:
        raw_result = completed.stdout

    (outdir / "response.md").write_text(str(raw_result), encoding="utf-8")
    verdict = parse_verdict(str(raw_result))
    verdict["_model"] = args.model
    verdict["_question"] = args.question
    (outdir / "verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")

    print(json.dumps(verdict, indent=2))
    print("\nsaved to " + outdir.relative_to(REPO_ROOT).as_posix(), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
