"""Start everything JARVIS needs, in order, from one command.

Four processes have to be up for a WhatsApp message to get a reply:

    phone -> Meta -> tunnel -> bus -> Supabase queue -> WhatsApp worker -> reply

Two more children exist for work that is not a reply, and both are optional --
their death degrades one capability and must never take the reply path down.
``action-worker`` is the third poller; without it a desktop action
(``system_control``, the two UIA kinds, ``flp_sort``) is claimed by nobody.
``whisper-server`` is what a *voice note* needs to get a reply; text does not
need it, and it is started best-effort because missing NPU build artifacts
(voice/whisper/local_backend.py's own availability check) are a machine-local
condition that was never committed -- a warning here, not a failed launch.

Starting them by hand means five steps in the right order, plus re-pointing
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

Children die with the launcher
------------------------------

That rule is about processes this launcher did not spawn. Its own children are
a different matter, and on 4 September 2026 they were the problem: two
``whisper-server.exe`` from earlier launches were still alive with the stack
down, holding 750 MB and both bound to 127.0.0.1:8081, because ``shutdown()``
only runs if ``main`` reaches its ``finally``. Closing the console window --
which ``start-jarvis.bat`` invites -- kills python outright, and a child
spawned with ``CREATE_NEW_PROCESS_GROUP`` survives it. Every launch after that
stacked another 3 GB model load on top of the last one.

So every child is assigned to a Windows Job Object created with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``. When this process ends *however* it
ends -- Ctrl+C, window close, crash, taskkill -- the OS closes the last handle
to the job and takes the tree with it. Same fail-open shape as the singleton
socket: nothing to clean up, nothing to go stale, no lock left behind by a
crash. ``process.terminate()`` in ``shutdown()`` stays for the orderly path;
the job is what covers the paths that never reach it.

The job is best-effort by construction. Missing pywin32, or a terminal that
already runs the launcher inside a job forbidding nesting, degrades to one
warning line and a launch that still works -- exactly what it did before.
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

# A minted Quick Tunnel name is a hyphenated random label (for example,
# ``injured-drew-wells-partner``).  Requiring that separator keeps the
# provisioning endpoint ``api.trycloudflare.com`` in a cloudflared error line
# from being mistaken for the tunnel that endpoint was meant to create.
TUNNEL_URL_PATTERN = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com\b")
LOG_DIR = ROOT / "tools"
BUS_HOST = "127.0.0.1"
BUS_PORT = 8000

# cloudflared prefers QUIC, which is UDP on port 7844. That is blocked or
# unroutable on this network: every dial failed with "wsasendto: A socket
# operation was attempted to an unreachable network", the tunnel never
# registered, and the launcher minted a URL that resolved nowhere while
# ordinary TCP to the same edge was fine (github 200, api.cloudflare.com 301).
# Forcing the http2 transport registered on the first attempt with zero errors.
# Overridable because this is a property of the network, not of the tool — set
# JARVIS_TUNNEL_PROTOCOL=quic on a network that permits UDP 7844.
TUNNEL_PROTOCOL_ENV = "JARVIS_TUNNEL_PROTOCOL"
DEFAULT_TUNNEL_PROTOCOL = "http2"


def tunnel_protocol(environ: dict[str, str] | None = None) -> str:
    settings = os.environ if environ is None else environ
    return settings.get(TUNNEL_PROTOCOL_ENV, DEFAULT_TUNNEL_PROTOCOL).strip() or DEFAULT_TUNNEL_PROTOCOL

#: Where Ollama's installer puts the binary on this machine. ``ollama serve``
#: binds 11434 itself, so the launcher never has to pass a port.
OLLAMA_EXE_ENV = "JARVIS_OLLAMA_EXE"
OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
OLLAMA_START_TIMEOUT = 30.0

#: How long whisper-server gets to load its 3 GB model, counted from the moment
#: it is spawned rather than from the moment we start waiting -- the tunnel work
#: that now runs in parallel spends most of this budget for us.
WHISPER_READY_TIMEOUT = 60.0

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

#: The job object lives here for the same reason, and it matters more: closing
#: the last handle to a kill-on-close job kills its processes, so a handle that
#: fell out of scope early would take the whole stack down mid-launch.
_job: object | None = None


def create_job_object() -> object | None:
    """A Windows job that kills its processes when its last handle closes.

    ``None`` on anything but Windows, and ``None`` -- with one warning line --
    when pywin32 is missing or the job cannot be configured. A launcher without
    the job is the launcher we had before, not a broken one, so nothing here
    raises.
    """
    if os.name != "nt":
        return None
    try:
        import win32job
    except ImportError:
        say("pywin32 missing — children may outlive this window if it is closed")
        return None
    try:
        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
    except Exception as exc:  # pragma: no cover - pywintypes.error, machine-local
        say(f"could not create the kill-on-close job ({exc}) — children may outlive this window")
        return None
    return job


class Supervisor:
    """Owns the child processes so the *required* ones die together.

    Not every child is required. ``whisper-server`` is optional: a WhatsApp
    voice note fails without it, but text messages do not need it at all, and
    the whole point of starting it best-effort (see the module docstring) is
    defeated if its death takes bus/tunnel/workers down with it.
    ``action-worker`` is optional for the same reason: without it a desktop
    action goes unclaimed, while text and voice replies are untouched.
    ``optional`` marks exactly that: a dead optional child is reported once and otherwise
    ignored by :meth:`check_alive`, never treated as a reason to shut down.
    """

    def __init__(self, job: object | None = None) -> None:
        self.children: list[tuple[str, subprocess.Popen]] = []
        self.optional: set[str] = set()
        self._reported_dead: set[str] = set()
        #: The kill-on-close job every child is assigned to, or ``None`` when
        #: this platform or this machine cannot provide one.
        self.job = job
        self._job_warned = False

    def adopt(self, process: subprocess.Popen) -> bool:
        """Put a child in the kill-on-close job. ``False`` if it could not go in.

        A failure is never fatal and never repeated: a terminal that already
        runs us inside a job forbidding nesting makes every assignment fail, and
        one warning line says everything a hundred would.
        """
        if self.job is None:
            return False
        try:
            import win32job

            handle = getattr(process, "_handle", None)
            if handle is None:
                raise OSError("the child exposes no process handle")
            win32job.AssignProcessToJobObject(self.job, handle)
        except Exception as exc:
            if not self._job_warned:
                self._job_warned = True
                say(f"could not add children to the kill-on-close job ({exc})")
                say("they may outlive this window if it is closed — Ctrl+C still stops them")
            return False
        return True

    def spawn(
        self,
        name: str,
        args: list[str],
        log: Path,
        env: dict[str, str] | None = None,
        *,
        optional: bool = False,
    ) -> subprocess.Popen:
        handle = log.open("w", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            args, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, creationflags=flags, env=env
        )
        self.children.append((name, process))
        if optional:
            self.optional.add(name)
        # Assigning a child created with CREATE_NEW_PROCESS_GROUP to a job works
        # on Windows 8+; it does not need CREATE_BREAKAWAY_FROM_JOB.
        self.adopt(process)
        return process

    def check_alive(self) -> str | None:
        """The name of the first dead *required* child, or ``None``.

        A dead optional child is reported once via ``say`` (so it is not
        silently invisible) and then skipped on every later check — nothing
        here escalates it into a shutdown reason.
        """
        for name, process in self.children:
            if process.poll() is None:
                continue
            if name in self.optional:
                if name not in self._reported_dead:
                    self._reported_dead.add(name)
                    say(f"{name} stopped unexpectedly — see tools/{name}.out.log (optional, continuing without it)")
                continue
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


def took(start: float) -> str:
    """How long a step took, for the line that announces it finished.

    "Slow to start" was a complaint with no number attached to it for as long
    as this launcher has existed. Every step now says its own.
    """
    return f"{time.monotonic() - start:.1f}s"


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


def pids_holding_port(port: int) -> list[int]:
    """Every PID listening on ``port`` on loopback, in the order netstat lists them.

    ``netstat -ano`` rather than ``psutil.net_connections`` because psutil is not
    a dependency of this repo, and a diagnostic line in an error message is not
    worth adding one for. The list is best-effort: an empty one changes the
    wording of a refusal, never the refusal itself.

    Plural because 4 September 2026 showed two ``whisper-server.exe`` bound to
    8081 at once. Naming one of them would have made the leak look like a single
    stray process instead of the pile-up it was.
    """
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    found: list[int] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP":
            continue
        local, state, pid = fields[1], fields[3], fields[4]
        if state.upper() != "LISTENING" or not local.endswith(f":{port}"):
            continue
        try:
            number = int(pid)
        except ValueError:
            continue
        if number not in found:
            found.append(number)
    return found


def pid_holding_port(port: int) -> int | None:
    """The first PID listening on ``port``, or ``None`` if not discoverable."""
    found = pids_holding_port(port)
    return found[0] if found else None


def describe_holders(port: int) -> str:
    """``"PID 4242"``, ``"PIDs 4242 and 4243"``, or an honest admission."""
    found = pids_holding_port(port)
    if not found:
        return "an unknown process — netstat gave no usable answer"
    if len(found) == 1:
        return f"PID {found[0]}"
    return "PIDs " + ", ".join(str(pid) for pid in found[:-1]) + f" and {found[-1]}"


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


def bus_is_answering(timeout: float = 2.0) -> bool:
    """Whether *something* already answers the bus port before we spawn one.

    The singleton lock is the real guard against a second copy, but it only
    covers copies started through this launcher. A bus left running by hand, or
    by a launcher whose window was closed, would otherwise get a second uvicorn
    spawned on top of it: the new one exits with "address already in use" and
    ``wait_for_bus`` passes anyway, because an HTTP probe on loopback cannot
    tell you whose process answered.
    """
    import httpx

    try:
        httpx.get(f"http://{BUS_HOST}:{BUS_PORT}/health", timeout=timeout)
        return True
    except httpx.HTTPError:
        return False


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


def whisper_server_is_ready() -> bool:
    """Whether a whisper-server is *already* serving on the configured port.

    Lazily imported for the same reason as ``httpx``: nothing outside the
    standard library loads until after the singleton lock.
    """
    from voice.whisper.server_client import WhisperServerClient

    return WhisperServerClient().is_ready()


def ollama_executable(environ: dict[str, str] | None = None) -> Path | None:
    """Where ``ollama.exe`` is, or ``None`` if it is not where it should be.

    ``JARVIS_OLLAMA_EXE`` overrides the installer's default location. An
    override that does not exist is treated as "not found" rather than spawned
    blindly, so a typo produces the same clear message as a missing install.
    """
    settings = os.environ if environ is None else environ
    override = (settings.get(OLLAMA_EXE_ENV) or "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.exists() else None
    local_app_data = (settings.get("LOCALAPPDATA") or "").strip()
    if not local_app_data:
        return None
    candidate = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
    return candidate if candidate.exists() else None


def wait_for_ollama(timeout: float = OLLAMA_START_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ollama_ready():
            return True
        time.sleep(1.0)
    return False


def start_ollama(supervisor: "Supervisor", timeout: float = OLLAMA_START_TIMEOUT) -> bool:
    """Spawn ``ollama serve`` and wait for it to answer. ``False`` if it cannot.

    Supervised and **optional**: Ali may already be running the tray app, in
    which case this is never reached, and an Ollama that dies later degrades
    memory rather than taking the reply path down.
    """
    executable = ollama_executable()
    if executable is None:
        return False
    say(f"starting {executable}")
    supervisor.spawn(
        "ollama",
        [str(executable), "serve"],
        LOG_DIR / "ollama.out.log",
        optional=True,
    )
    return wait_for_ollama(timeout)


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


def wait_for_whisper_server(timeout: float = 60.0) -> bool:
    """``whisper-server``'s ``/health`` reports ``ok`` once the model has loaded.

    Imported lazily, same as ``httpx`` above and for the same reason: nothing
    outside the standard library loads until after the singleton lock.
    """
    from voice.whisper.server_client import WhisperServerClient

    client = WhisperServerClient()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.is_ready():
            return True
        time.sleep(1.0)
    return False


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


#: The job kinds the action worker owns. All four are registered in
#: ``executor.poller.DEFAULT_HANDLERS`` and, before this worker existed, no
#: running poller ever claimed any of them: ``--kind`` took one value and the
#: two live workers were pinned to ``whatsapp_webhook`` and ``distill_memory``.
#: They are kept off the other two workers deliberately — a desktop action
#: that takes a second must never queue behind a 130s Ollama extraction.
ACTION_JOB_KINDS = (
    "flp_sort",
    "system_control",
    "zoom_join_meeting",
    "whatsapp_desktop_send_message",
)

#: The kinds ``whatsapp-worker`` owns. ``whatsapp_outcome`` is here and not in
#: ``ACTION_JOB_KINDS`` on purpose: it is the *reply* an action produces, and
#: sending it needs the Graph client and token this worker already holds and
#: ``action-worker`` deliberately does not. An outcome may therefore queue
#: behind a reply this worker is routing, which is the right way round — the
#: message the user is waiting on goes first.
WHATSAPP_JOB_KINDS = (
    "whatsapp_webhook",
    "whatsapp_outcome",
)


def spawn_whisper_server(supervisor: Supervisor) -> object | None:
    """Start whisper-server if it is not already up. Returns its config, or ``None``.

    ``None`` means there is nothing to wait for later: not built, not available
    on this machine, or -- the case 4 September 2026 produced -- already
    listening. A server that is already there is *used*, never restarted and
    never killed: each one holds a 3 GB model, and stacking a second cost 750 MB
    for nothing. The reply path is unaffected either way, which is why every
    branch here warns and continues instead of failing the launch.
    """
    from voice.whisper.local_backend import LocalWhisperBackend, subprocess_env
    from voice.whisper.server_client import WhisperServerConfig

    server_config = WhisperServerConfig.from_environ()
    if whisper_server_is_ready():
        say(f"already listening on {server_config.host}:{server_config.port} — it belongs to {describe_holders(server_config.port)}.")
        say("using the one that is there; nothing was started and nothing was stopped")
        return None

    backend = LocalWhisperBackend()
    availability = backend.availability()
    # backend.binary is whisper-cli.exe -- it has no --host/--port and
    # exits on them. The server binary is a sibling in the same
    # bin/Release/ directory, since both come out of the same
    # build-vitisai build (voice/whisper/local_backend.py's own docstring
    # names both artifacts landing there together).
    server_binary = backend.binary.parent / "whisper-server.exe"
    if not availability.available:
        say(f"skipping: {availability.reason}")
        say("text messages are unaffected; voice notes will not get a reply until this is built")
        return None
    if not server_binary.exists():
        say(f"skipping: whisper-server not built: {server_binary} does not exist")
        say("text messages are unaffected; voice notes will not get a reply until this is built")
        return None

    supervisor.spawn(
        "whisper-server",
        [
            str(server_binary),
            "-m",
            str(backend.model),
            "-l",
            backend.language,
            "--host",
            server_config.host,
            "--port",
            str(server_config.port),
        ],
        LOG_DIR / "whisper-server.out.log",
        # Same defensive PATH prepend as the CLI backend
        # (voice/whisper/local_backend.py): flexmlrt.dll is normally
        # staged next to the binary already, but a partial build
        # should still run rather than die with an opaque loader error.
        env=subprocess_env(),
        # Optional: a dead or never-ready whisper-server must degrade
        # to text-only, never take bus/tunnel/workers down with it.
        optional=True,
    )
    return server_config


def spawn_workers(supervisor: Supervisor, python: str, interval: str) -> None:
    """Start the three supervised pollers, each restricted to its own kinds.

    Only ``background-worker`` seeds the distill chain and maintains the batch
    heartbeat; the other two pass ``--no-heartbeat`` because neither drives the
    single local Ollama, and a worker that marked the executor live would block
    the batch tools that guard on it (``executor/heartbeat.py``).

    ``action-worker`` is **optional**, decided the same way ``whisper-server``
    was: its death degrades desktop actions, and text and voice replies keep
    working without it, so it must not take bus/tunnel/reply-path down with it.
    """
    supervisor.spawn(
        "whatsapp-worker",
        [python, "-m", "executor.poller", "--kind", *WHATSAPP_JOB_KINDS,
         "--no-heartbeat", "--interval", interval],
        LOG_DIR / "whatsapp-worker.out.log",
    )
    supervisor.spawn(
        "background-worker",
        [python, "-m", "executor.poller", "--kind", "distill_memory",
         "--interval", interval],
        LOG_DIR / "background-worker.out.log",
    )
    supervisor.spawn(
        "action-worker",
        [python, "-m", "executor.poller", "--kind", *ACTION_JOB_KINDS,
         "--no-heartbeat", "--interval", interval],
        LOG_DIR / "action-worker.out.log",
        optional=True,
    )
    say(f"WhatsApp, background and action workers polling every {interval}s")


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
    global _singleton_lock, _job
    port = singleton_port()
    _singleton_lock = acquire_singleton_lock(port)
    if _singleton_lock is None:
        print("Starting JARVIS", flush=True)
        report_duplicate(port)
        return 1

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    started = time.monotonic()
    python = python_executable()
    print("Starting JARVIS", flush=True)
    # Created after the banner because its failure path prints, and before any
    # child exists because a child spawned outside the job is one the OS will
    # not clean up.
    _job = create_job_object()
    supervisor = Supervisor(job=_job)

    try:
        step("[1/6] Local AI (Ollama)")
        begun = time.monotonic()
        if ollama_ready():
            # Already serving — the tray app, or a previous launch. Leave it be.
            say(f"ready ({took(begun)})")
        else:
            say(f"not answering on {OLLAMA_HOST}:{OLLAMA_PORT}")
            if start_ollama(supervisor):
                say(f"ready ({took(begun)})")
            else:
                say(f"Ollama is not answering on {OLLAMA_HOST}:{OLLAMA_PORT}.")
                say("Start it and run this again — memory needs it.")
                return 1

        step("[2/6] Webhook receiver")
        begun = time.monotonic()
        if bus_is_answering():
            # Same refusal as the singleton lock, for the same reason: whoever
            # answers 8000 owns the reply path, and we cannot tell whose it is.
            say(f"something already answers {BUS_HOST}:{BUS_PORT} — it belongs to {describe_holders(BUS_PORT)}.")
            say("nothing was started: no tunnel minted, WhatsApp left pointed where it is.")
            say("stop the running copy with Ctrl+C in its own window, then run this again.")
            return 1
        bus_log = LOG_DIR / "bus.out.log"
        supervisor.spawn(
            "bus",
            [python, "-m", "uvicorn", "bus.main:app", "--host", BUS_HOST, "--port", str(BUS_PORT)],
            bus_log,
        )
        if not wait_for_bus():
            say(f"never came up — see {bus_log}")
            return 1
        say(f"listening on {BUS_HOST}:{BUS_PORT} ({took(begun)})")

        # Everything from here to the tunnel is started, not waited on. Whisper
        # loads a 3 GB model and the workers only need the bus process and
        # Supabase; none of it has anything to do with minting a tunnel or
        # re-pointing Meta. Running them in sequence made a ~2 minute launch out
        # of steps whose *maximum* is under one, so the two slow independent
        # things now overlap and whisper's readiness check moves to the end.
        step("[3/6] Voice (whisper-server)")
        begun = time.monotonic()
        whisper_started_at: float | None = None
        whisper_log = LOG_DIR / "whisper-server.out.log"
        server_config = spawn_whisper_server(supervisor)
        if server_config is not None:
            whisper_started_at = time.monotonic()
            say(f"loading its model in the background ({took(begun)})")

        step("[4/6] Workers")
        begun = time.monotonic()
        spawn_workers(supervisor, python, str(args.interval))
        say(f"started ({took(begun)})")

        step("[5/6] Public tunnel")
        begun = time.monotonic()
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
                "--protocol",
                tunnel_protocol(),
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
            say(f"skipping Meta update (--skip-webhook) ({took(begun)})")
        else:
            say("pointing WhatsApp at it...")
            command = [python, str(ROOT / "tools" / "repoint_webhook.py"), "--url", url]
            if skip_probe:
                command.append("--skip-probe")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            if result.returncode == 0:
                say(f"WhatsApp updated ({took(begun)})")
            else:
                say("could not update WhatsApp automatically:")
                for line in (result.stderr or result.stdout).strip().splitlines()[-3:]:
                    say(f"  {line}")
                say("replies will not arrive until this is fixed")

        step("[6/6] Voice readiness")
        if server_config is None:
            say("nothing to wait for")
        else:
            # Whatever the tunnel spent is time the model was already loading,
            # so only the remainder of its budget is left to wait out. The floor
            # keeps a fast tunnel from turning into a zero-length wait.
            spent = time.monotonic() - (whisper_started_at or time.monotonic())
            remaining = max(5.0, WHISPER_READY_TIMEOUT - spent)
            if wait_for_whisper_server(remaining):
                say(f"listening on {server_config.host}:{server_config.port} ({took(whisper_started_at)})")
            else:
                say(f"never became ready — see {whisper_log}")
                say("text messages are unaffected; voice notes will fail until this is fixed")

        print("\n" + "-" * 58, flush=True)
        print(f"  JARVIS is running — {time.monotonic() - started:.0f}s. Message it on WhatsApp.", flush=True)
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
