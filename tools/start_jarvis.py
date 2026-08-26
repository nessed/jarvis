"""Start everything JARVIS needs, in order, from one command.

Three processes have to be up for a WhatsApp message to get a reply:

    phone -> Meta -> tunnel -> bus -> Supabase queue -> executor -> reply

Starting them by hand means four steps in the right order, plus re-pointing
Meta's callback every time the Cloudflare Quick Tunnel mints a new URL. This
does all of it, waits for each piece to actually answer before starting the
next, and shuts the whole set down together on Ctrl+C.

    .venv\\Scripts\\python.exe tools/start_jarvis.py

or double-click ``start-jarvis.bat`` in the repo root.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TUNNEL_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
LOG_DIR = ROOT / "tools"
BUS_HOST = "127.0.0.1"
BUS_PORT = 8000


class Supervisor:
    """Owns the child processes so they die together, not one at a time."""

    def __init__(self) -> None:
        self.children: list[tuple[str, subprocess.Popen]] = []

    def spawn(self, name: str, args: list[str], log: Path) -> subprocess.Popen:
        handle = log.open("w", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            args, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, creationflags=flags
        )
        self.children.append((name, process))
        return process

    def check_alive(self) -> str | None:
        for name, process in self.children:
            if process.poll() is not None:
                return name
        return None

    def shutdown(self) -> None:
        for name, process in reversed(self.children):
            if process.poll() is not None:
                continue
            say(f"stopping {name}")
            try:
                process.terminate()
            except OSError:
                pass
        deadline = time.monotonic() + 10
        for _, process in reversed(self.children):
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()


def say(message: str) -> None:
    print(f"  {message}", flush=True)


def step(message: str) -> None:
    print(f"\n{message}", flush=True)


def python_executable() -> str:
    venv = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(venv) if venv.exists() else sys.executable


def wait_for_bus(timeout: float = 30.0) -> bool:
    """The bus is up once it answers at all — 401 counts, auth is doing its job."""
    import httpx

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://{BUS_HOST}:{BUS_PORT}/health", timeout=2.0)
            return True
        except httpx.HTTPError:
            time.sleep(0.5)
    return False


def wait_for_tunnel_url(log: Path, timeout: float = 60.0) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            found = TUNNEL_URL_PATTERN.search(log.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            found = None
        if found:
            return found.group(0)
        time.sleep(0.5)
    return None


def tunnel_reachable(url: str, timeout: float = 45.0) -> bool:
    """A Quick Tunnel answers its own 5xx for a while before the origin is wired."""
    import httpx

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/health", timeout=8.0)
            if response.status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2.0)
    return False


def resolves_on_public_dns(url: str) -> bool:
    """Whether the tunnel hostname exists according to a resolver that isn't ours.

    This machine's ISP resolver lags badly on freshly-minted records — it
    returned NXDOMAIN for a Quick Tunnel hostname that 1.1.1.1 and 8.8.8.8 both
    resolved. Meta does its own resolution, so a tunnel this machine cannot look
    up is still perfectly reachable from the internet. Without this check the
    launcher would refuse to point Meta at a working tunnel every single run.
    """
    host = url.split("://", 1)[-1].split("/", 1)[0]
    for resolver in ("1.1.1.1", "8.8.8.8"):
        try:
            result = subprocess.run(
                ["nslookup", host, resolver], capture_output=True, text=True, timeout=15
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        output = result.stdout.lower()
        if host.lower() in output and "can't find" not in output and "non-existent" not in output:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the whole JARVIS stack")
    parser.add_argument("--skip-webhook", action="store_true", help="don't re-point Meta")
    parser.add_argument("--interval", default="3", help="executor poll seconds (default 3)")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    python = python_executable()
    supervisor = Supervisor()
    print("Starting JARVIS", flush=True)

    try:
        step("[1/4] Local AI (Ollama)")
        if not ollama_ready():
            say("Ollama is not answering on 127.0.0.1:11434.")
            say("Start it and run this again — memory needs it.")
            return 1
        say("ready")

        step("[2/4] Webhook receiver")
        bus_log = LOG_DIR / "bus.out.log"
        supervisor.spawn(
            "bus",
            [python, "-m", "uvicorn", "bus.main:app", "--host", BUS_HOST, "--port", str(BUS_PORT)],
            bus_log,
        )
        if not wait_for_bus():
            say(f"never came up — see {bus_log}")
            return 1
        say(f"listening on {BUS_HOST}:{BUS_PORT}")

        step("[3/4] Public tunnel")
        cloudflared = ROOT / "tools" / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
        if not cloudflared.exists():
            say(f"cloudflared not found at {cloudflared}")
            return 1
        tunnel_log = LOG_DIR / "cloudflared.log"
        tunnel_log.unlink(missing_ok=True)
        supervisor.spawn(
            "tunnel",
            [
                str(cloudflared),
                "tunnel",
                "--url",
                f"http://{BUS_HOST}:{BUS_PORT}",
                "--logfile",
                str(tunnel_log),
            ],
            LOG_DIR / "cloudflared.out.log",
        )
        url = wait_for_tunnel_url(tunnel_log) or wait_for_tunnel_url(LOG_DIR / "cloudflared.out.log", 5)
        if not url:
            say(f"no tunnel URL appeared — see {tunnel_log}")
            return 1
        say(url)
        reachable = tunnel_reachable(url)
        skip_probe = False
        if not reachable:
            if resolves_on_public_dns(url):
                # Local DNS lag only. Meta resolves independently, so the probe
                # inside repoint_webhook would also fail for the wrong reason.
                say("this machine's DNS can't see it yet, but public DNS can")
                skip_probe = True
            else:
                say("tunnel is not reachable and does not resolve publicly")
                say("replies will not arrive until the tunnel is up")

        if args.skip_webhook:
            say("skipping Meta update (--skip-webhook)")
        else:
            say("pointing WhatsApp at it...")
            command = [python, str(ROOT / "tools" / "repoint_webhook.py"), "--url", url]
            if skip_probe:
                command.append("--skip-probe")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            if result.returncode == 0:
                say("WhatsApp updated")
            else:
                say("could not update WhatsApp automatically:")
                for line in (result.stderr or result.stdout).strip().splitlines()[-3:]:
                    say(f"  {line}")
                say("replies will not arrive until this is fixed")

        step("[4/4] Worker")
        supervisor.spawn(
            "executor",
            [python, "-m", "executor.poller", "--interval", str(args.interval)],
            LOG_DIR / "executor.out.log",
        )
        say(f"polling every {args.interval}s")

        print("\n" + "-" * 58, flush=True)
        print("  JARVIS is running. Message it on WhatsApp.", flush=True)
        print("  Press Ctrl+C here to stop everything.", flush=True)
        print("-" * 58 + "\n", flush=True)

        while True:
            time.sleep(2)
            died = supervisor.check_alive()
            if died:
                print(f"\n{died} stopped unexpectedly — see tools/{died}.out.log", flush=True)
                return 1
    except KeyboardInterrupt:
        print("\nShutting down", flush=True)
        return 0
    finally:
        supervisor.shutdown()
        print("All stopped.", flush=True)


def ollama_ready() -> bool:
    import httpx

    try:
        httpx.get("http://127.0.0.1:11434/api/tags", timeout=5.0).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    if os.name == "nt":
        signal.signal(signal.SIGBREAK, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
