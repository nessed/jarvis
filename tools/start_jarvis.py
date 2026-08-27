"""Start everything JARVIS needs, in order, from one command.

Three processes have to be up for a WhatsApp message to get a reply:

    phone -> Meta -> tunnel -> bus -> Supabase queue -> executor -> reply

Starting them by hand means four steps in the right order, plus re-pointing
Meta's callback every time the Cloudflare Quick Tunnel mints a new URL. This
does all of it, waits for each piece to actually answer before starting the
next, and shuts the whole set down together on Ctrl+C.

    .venv\\Scripts\\python.exe tools/start_jarvis.py

or double-click ``start-jarvis.bat`` in the repo root.

Only one copy may run at a time
-------------------------------

On 26-27 August 2026 two full copies of the stack ran at once, each with its
own bus, its own Cloudflare Quick Tunnel and its own executor draining the same
Supabase queue. The health checks below could not see it: ``ollama_ready`` talks
to a shared singleton service, ``wait_for_bus`` gets its 200 from whichever
process owns port 8000 — an HTTP probe on a loopback port cannot tell you whose
process answered — and by the time ``tunnel_reachable`` runs, the second copy
has already minted a tunnel and re-pointed Meta's webhook at itself, stealing
inbound traffic from the first.

So the guard is a lock, taken before any of that can happen: bind
``127.0.0.1:8765`` exclusively (``JARVIS_SINGLETON_PORT`` overrides the port)
as the first side effect ``main`` has, and refuse to continue if the bind fails.
8765 is arbitrary but deliberate — it collides with neither the bus (8000) nor
Ollama (11434), and nothing else in this repo uses it. ``SO_REUSEADDR`` is
never set: on Windows it lets two sockets share a port, which would make this
guard silently pass.

A bound socket rather than a lockfile, and for the same reason
``executor/heartbeat.py`` uses a timestamp file rather than a PID lock: "if the
executor is killed the marker simply goes stale on its own, so a crash can never
leave a lock behind that blocks every future batch run." The OS releases a bind
when the process dies, however it dies — clean exit, Ctrl+C, crash, or kill. The
lock therefore fails open by construction. There is no stale state to clear, no
file to delete, and no way for a dead launcher to wedge every future launch.

Recovering from the duplicate by force-killing PIDs caused a full outage on this
machine, so nothing here ever kills, signals, or cleans up another process. The
refusal names the holding PID and stops.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import socket
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

SINGLETON_HOST = "127.0.0.1"
SINGLETON_PORT_ENV = "JARVIS_SINGLETON_PORT"
DEFAULT_SINGLETON_PORT = 8765
#: The guard port as it stands at import. See ``singleton_port`` for the
#: call-time resolution the launcher actually uses.
SINGLETON_PORT = int(os.environ.get(SINGLETON_PORT_ENV, str(DEFAULT_SINGLETON_PORT)))

#: The bound socket lives here for the whole life of the process. A local would
#: be enough while ``main`` runs, but a module reference makes it impossible for
#: a future refactor to drop the lock early by letting it fall out of scope.
_singleton_lock: socket.socket | None = None


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


def singleton_port(environ: dict[str, str] | None = None) -> int:
    """The port the single-instance guard binds, honouring the env override.

    Resolved at call time rather than read from ``SINGLETON_PORT`` so that the
    override applies however late the environment is set. Note that the lock is
    taken before ``load_dotenv``, on purpose — a guard that waited for ``.env``
    would already be too late — so ``JARVIS_SINGLETON_PORT`` has to come from the
    real environment, not from ``.env``.
    """
    settings = os.environ if environ is None else environ
    return int(settings.get(SINGLETON_PORT_ENV, str(DEFAULT_SINGLETON_PORT)))


def acquire_singleton_lock(port: int | None = None) -> socket.socket | None:
    """Bind the guard port exclusively, or return ``None`` if someone else has it.

    The returned socket must be kept alive for as long as the launcher runs;
    closing it releases the lock and lets a second copy start.
    """
    target = singleton_port() if port is None else port
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # No SO_REUSEADDR here, ever. On Windows it permits a second bind to the
        # same address and the guard would pass for both copies.
        lock.bind((SINGLETON_HOST, target))
        lock.listen(1)
    except OSError:
        lock.close()
        return None
    return lock


def pid_holding_port(port: int) -> int | None:
    """The PID listening on ``port`` on loopback, or ``None`` if not discoverable.

    ``netstat -ano`` rather than ``psutil.net_connections`` because psutil is not
    a dependency of this repo, and a diagnostic line in an error message is not
    worth adding one for. The PID is best-effort: a missing one changes the
    wording of the refusal, never the refusal itself.
    """
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP":
            continue
        local, state, pid = fields[1], fields[3], fields[4]
        if state.upper() != "LISTENING" or not local.endswith(f":{port}"):
            continue
        try:
            return int(pid)
        except ValueError:
            return None
    return None


def report_duplicate(port: int) -> None:
    """Explain the refusal. Never kills, signals, or offers to kill anything."""
    holder = pid_holding_port(port)
    say(f"another copy of JARVIS already holds {SINGLETON_HOST}:{port}.")
    if holder is None:
        say("could not tell which process holds it — netstat gave no usable answer.")
    else:
        say(f"it belongs to PID {holder}.")
    say("nothing was started: no bus, no tunnel minted, WhatsApp left pointed where it is.")
    say("stop the running copy with Ctrl+C in its own window, then run this again.")
    say(f"if {port} is held by something unrelated, set {SINGLETON_PORT_ENV} and retry.")


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

    # The lock is the first thing that touches the outside world. Argument
    # parsing above has no side effects — it only reads argv, and --help must
    # still work while another copy runs — but everything past this point does.
    # Nothing is imported, loaded, probed or spawned until the bind succeeds,
    # because minting a tunnel and re-pointing Meta are the two acts that made
    # the duplicate destructive rather than merely wasteful.
    global _singleton_lock
    port = singleton_port()
    _singleton_lock = acquire_singleton_lock(port)
    if _singleton_lock is None:
        print("Starting JARVIS", flush=True)
        report_duplicate(port)
        return 1

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
        # The singleton socket is left open on purpose: the OS releases it when
        # this process exits, and holding it until then means a copy that is
        # still tearing children down cannot be raced by a fresh launch.
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
