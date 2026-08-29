"""Power mode, wifi, Bluetooth-radio, and display-output control.

``powercfg`` and ``netsh`` are first-class Windows CLIs. Bluetooth has no
equivalent first-class radio CLI, so this follows
docs/tasks/laptop-system-control.md's accepted approach: toggle the
Bluetooth-class PnP device via PowerShell's ``Get-PnpDevice`` /
``Enable-PnpDevice`` / ``Disable-PnpDevice``. Display switching shells out to
``DisplaySwitch.exe`` with one of its four fixed mode flags.

Every subprocess call here builds an argument list -- never a formatted
shell string -- so a payload-controlled value can never break out of its
argument (docs/tasks/laptop-system-control.md). Where a value must reach a
PowerShell ``-Command`` script (Bluetooth's ``instance_id``), it is passed
through an environment variable and read back with ``$env:...`` rather than
interpolated into the command text, which means it is never parsed as
PowerShell syntax at all.

The one sharp edge
-------------------
This laptop's own wifi carries the Cloudflare tunnel, the bus, and Meta's
webhook -- a job that disables it disconnects the machine running the job.
:func:`set_wifi_enabled` therefore takes no default ``interface`` (a caller
must always name the exact adapter) and, before any *disable* request runs,
checks whether that adapter is the one currently carrying the machine's
default route via :func:`default_route_interface`. If so it raises
:class:`WifiGuardError` instead of running the command -- never a silent
no-op, never a silent success. See
docs/tasks/laptop-system-control-report.md for whether this guard was
exercised by a test simulating "this is the active internet adapter".
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

Runner = Callable[..., subprocess.CompletedProcess]


def _run(
    args: Sequence[str], *, run: Runner, env: Mapping[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    return run(
        list(args),
        capture_output=True,
        text=True,
        check=check,
        env=dict(env) if env is not None else None,
    )


# ---------------------------------------------------------------------------
# Power plans (powercfg)
# ---------------------------------------------------------------------------

_PLAN_LINE_RE = re.compile(
    r"Power Scheme GUID:\s*(?P<guid>[0-9a-fA-F-]{36})\s*\((?P<name>[^)]*)\)\s*(?P<active>\*)?"
)


@dataclass(frozen=True)
class PowerPlan:
    guid: str
    name: str
    active: bool


def list_power_plans(*, run: Runner = subprocess.run) -> list[PowerPlan]:
    """Parse ``powercfg /list`` into the available power plans."""
    result = _run(["powercfg", "/list"], run=run)
    return [
        PowerPlan(
            guid=match.group("guid"),
            name=match.group("name").strip(),
            active=match.group("active") is not None,
        )
        for match in _PLAN_LINE_RE.finditer(result.stdout or "")
    ]


def get_active_power_plan(*, run: Runner = subprocess.run) -> PowerPlan | None:
    """The currently active power plan, or ``None`` if ``powercfg`` reports none as active."""
    for plan in list_power_plans(run=run):
        if plan.active:
            return plan
    return None


def set_power_plan(guid: str, *, run: Runner = subprocess.run) -> None:
    """Switch the active power plan to ``guid`` via ``powercfg /setactive``."""
    _run(["powercfg", "/setactive", guid], run=run)


# ---------------------------------------------------------------------------
# Wifi (netsh) -- see the module docstring's sharp-edge section
# ---------------------------------------------------------------------------


class WifiGuardError(Exception):
    """Raised when a wifi-disable request targets the machine's own default-route adapter.

    This is the guard docs/tasks/laptop-system-control.md calls out by name:
    a job that disables the adapter carrying the default route disconnects
    the machine running the job before it can even report success. Raised
    instead of running the ``netsh`` disable command -- never a silent
    no-op, never a silent success.
    """


@dataclass(frozen=True)
class WifiInterface:
    name: str
    state: str


_WIFI_NAME_RE = re.compile(r"^\s*Name\s*:\s*(?P<name>.+?)\s*$", re.MULTILINE)
_WIFI_STATE_RE = re.compile(r"^\s*State\s*:\s*(?P<state>.+?)\s*$", re.MULTILINE)


def list_wifi_interfaces(*, run: Runner = subprocess.run) -> list[WifiInterface]:
    """Parse ``netsh wlan show interfaces`` into each adapter's name and state.

    ``netsh`` emits one ``Name`` line and one ``State`` line per interface
    block, in that relative order, so pairing them positionally is safe.
    """
    result = _run(["netsh", "wlan", "show", "interfaces"], run=run)
    output = result.stdout or ""
    names = _WIFI_NAME_RE.findall(output)
    states = _WIFI_STATE_RE.findall(output)
    return [WifiInterface(name=name, state=state) for name, state in zip(names, states)]


def default_route_interface(*, run: Runner = subprocess.run) -> str | None:
    """The interface alias currently carrying the IPv4 default route (0.0.0.0/0).

    Fixed PowerShell command text, no payload-controlled value interpolated
    into it -- ``Get-NetRoute`` is read-only and takes no untrusted input
    here. Returns ``None`` if no default route is found (e.g. no active
    network) rather than raising, since "no default route" is itself a
    perfectly good reason not to guard a disable request.
    """
    command = (
        "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue "
        "| Sort-Object -Property RouteMetric | Select-Object -First 1 -ExpandProperty InterfaceAlias)"
    )
    result = run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or "").strip()
    return output or None


def set_wifi_enabled(
    interface: str,
    enabled: bool,
    *,
    run: Runner = subprocess.run,
    default_route_interface_fn: Callable[..., str | None] = default_route_interface,
) -> None:
    """Enable or disable one named wifi adapter via ``netsh interface set interface``.

    ``interface`` has no default -- see the module docstring's sharp-edge
    note; a caller must always name the exact adapter, never "the current
    one". Before a *disable* request (``enabled=False``) runs, this checks
    whether ``interface`` is the adapter :func:`default_route_interface_fn`
    reports as currently carrying the machine's default route, and raises
    :class:`WifiGuardError` instead of running the command if so. Enabling a
    radio is never guarded, since it cannot disconnect anything.
    """
    if not enabled:
        active = default_route_interface_fn(run=run)
        if active is not None and active.strip().lower() == interface.strip().lower():
            raise WifiGuardError(
                f"refusing to disable {interface!r}: it is the adapter currently "
                "carrying this machine's default route (this job's own connectivity)"
            )
    state = "enabled" if enabled else "disabled"
    _run(
        ["netsh", "interface", "set", "interface", f"name={interface}", f"admin={state}"],
        run=run,
    )


# ---------------------------------------------------------------------------
# Bluetooth radio (PnP) -- no first-class Bluetooth-radio CLI on Windows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PnpDevice:
    instance_id: str
    friendly_name: str
    status: str


def list_bluetooth_radios(*, run: Runner = subprocess.run) -> list[PnpDevice]:
    """List PnP devices in the Bluetooth device class via ``Get-PnpDevice -Class Bluetooth``.

    Confirm the exact ``instance_id`` on the live machine before calling
    :func:`set_bluetooth_enabled` with it -- see
    docs/tasks/laptop-system-control-report.md for the id captured on this
    machine. No untrusted input reaches this command (the class name is
    fixed), so a plain ``-Command`` string is safe here.
    """
    command = (
        "Get-PnpDevice -Class Bluetooth | Select-Object InstanceId, FriendlyName, Status "
        "| ConvertTo-Json -Compress"
    )
    result = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], run=run)
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    rows = parsed if isinstance(parsed, list) else [parsed]
    return [
        PnpDevice(
            instance_id=str(row.get("InstanceId", "")),
            friendly_name=str(row.get("FriendlyName", "")),
            status=str(row.get("Status", "")),
        )
        for row in rows
    ]


def set_bluetooth_enabled(instance_id: str, enabled: bool, *, run: Runner = subprocess.run) -> None:
    """Enable/disable one Bluetooth PnP device via Enable-PnpDevice/Disable-PnpDevice.

    ``instance_id`` (payload-controlled) is passed to PowerShell through an
    environment variable and read back with ``$env:JARVIS_PNP_INSTANCE_ID`` --
    never interpolated into the command text -- so it is read as plain string
    data, never parsed as PowerShell syntax, and can never break out of its
    argument. Bluetooth is the "secondary radio" this lane defaults to
    toggling freely; unlike wifi it carries no guard, since disabling it
    cannot disconnect the machine running the job.
    """
    command = (
        "$id = $env:JARVIS_PNP_INSTANCE_ID; "
        "if ($env:JARVIS_PNP_ACTION -eq 'Enable') "
        "{ Enable-PnpDevice -InstanceId $id -Confirm:$false } "
        "else { Disable-PnpDevice -InstanceId $id -Confirm:$false }"
    )
    env = dict(os.environ)
    env["JARVIS_PNP_INSTANCE_ID"] = instance_id
    env["JARVIS_PNP_ACTION"] = "Enable" if enabled else "Disable"
    _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], run=run, env=env)


# ---------------------------------------------------------------------------
# Display output (DisplaySwitch.exe)
# ---------------------------------------------------------------------------


class InvalidDisplayModeError(Exception):
    """Raised when an unsupported ``DisplaySwitch.exe`` mode is requested."""


_DISPLAY_MODE_FLAGS: dict[str, str] = {
    "internal": "/internal",
    "external": "/external",
    "clone": "/clone",
    "extend": "/extend",
}


def switch_display(mode: str, *, run: Runner = subprocess.run) -> None:
    """Switch display output via ``DisplaySwitch.exe``.

    ``mode`` must be one of ``internal``/``external``/``clone``/``extend``,
    checked against a fixed allow-list before shelling out -- an
    unrecognized mode raises :class:`InvalidDisplayModeError` rather than
    passing an arbitrary payload string straight to ``DisplaySwitch.exe``.
    """
    flag = _DISPLAY_MODE_FLAGS.get(mode.strip().lower())
    if flag is None:
        raise InvalidDisplayModeError(
            f"unknown display mode {mode!r}; expected one of {sorted(_DISPLAY_MODE_FLAGS)}"
        )
    _run(["DisplaySwitch.exe", flag], run=run)
