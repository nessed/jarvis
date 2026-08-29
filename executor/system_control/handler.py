"""Blueprint 2.4: the ``system_control`` job -- one job kind, an ``action`` dispatch.

Wraps power/wifi/bluetooth/display switching, scheduled tasks, printing,
confined file ops, and guarded process kills behind a single job kind,
following ``executor/flp/sort.py``'s ``build_flp_sort_handler()`` shape: each
capability has its own pure/testable function (in ``power.py``,
``scheduled_tasks.py``, ``printing.py``, ``files.py``, ``processes.py``) and
this handler just parses ``job.payload``, calls the right one, and lets
``executor.poller``'s existing retry/backoff/dead-letter path handle any
exception.

Payload schema
--------------
::

    {"action": "<capability>.<operation>", "args": {...}}

See docs/tasks/laptop-system-control-report.md for the full action list and
each action's expected ``args`` keys -- this is the schema
``enqueue-classifier`` (not built here) will need to produce whenever it
lands; nothing in this module parses free text or routes an inbound message.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from db.jobs import Job

from executor.system_control import files, power, printing, processes, scheduled_tasks

logger = logging.getLogger(__name__)

ActionFn = Callable[[Mapping[str, Any]], Any]


class UnknownSystemControlActionError(Exception):
    """Raised when a ``system_control`` job names an action with no registered handler."""


class MissingSystemControlArgError(Exception):
    """Raised when a required key is missing from a ``system_control`` job's ``args``."""


def _require(args: Mapping[str, Any], key: str) -> Any:
    if key not in args:
        raise MissingSystemControlArgError(f"action requires {key!r} in args, got {sorted(args)}")
    return args[key]


@dataclass(frozen=True)
class SystemControlDeps:
    """Every external dependency a ``system_control`` action can touch, bundled as one unit.

    Matches ``build_flp_sort_handler``'s "every dependency is injectable"
    pattern. Defaults are the real subprocess runner, the real ``win32print``
    module, the real ``win32api.ShellExecute``, and the real ``psutil``
    hooks -- override any of them (typically all of them, via ``actions``
    instead) to test dispatch without touching the real system.
    """

    subprocess_run: Callable[..., subprocess.CompletedProcess] = subprocess.run
    default_route_interface_fn: Callable[..., str | None] = power.default_route_interface
    printer_api: Any = printing.win32print
    shell_execute: Callable[..., Any] = printing.win32api.ShellExecute
    files_root: Path | None = None
    process_iter: Callable[..., Any] = field(default=processes.psutil.process_iter)
    process_factory: Callable[[int], Any] = field(default=processes.psutil.Process)
    own_pid: int | None = None
    venv_dir: Path | None = None


def _build_action_registry(deps: SystemControlDeps) -> dict[str, ActionFn]:
    def power_list_plans(args: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [asdict(plan) for plan in power.list_power_plans(run=deps.subprocess_run)]

    def power_get_active_plan(args: Mapping[str, Any]) -> dict[str, Any] | None:
        plan = power.get_active_power_plan(run=deps.subprocess_run)
        return asdict(plan) if plan is not None else None

    def power_set_plan(args: Mapping[str, Any]) -> None:
        power.set_power_plan(_require(args, "guid"), run=deps.subprocess_run)

    def wifi_list_interfaces(args: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [asdict(iface) for iface in power.list_wifi_interfaces(run=deps.subprocess_run)]

    def wifi_set_enabled(args: Mapping[str, Any]) -> None:
        power.set_wifi_enabled(
            _require(args, "interface"),
            bool(_require(args, "enabled")),
            run=deps.subprocess_run,
            default_route_interface_fn=deps.default_route_interface_fn,
        )

    def bluetooth_list_devices(args: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [asdict(device) for device in power.list_bluetooth_radios(run=deps.subprocess_run)]

    def bluetooth_set_enabled(args: Mapping[str, Any]) -> None:
        power.set_bluetooth_enabled(
            _require(args, "instance_id"),
            bool(_require(args, "enabled")),
            run=deps.subprocess_run,
        )

    def display_switch(args: Mapping[str, Any]) -> None:
        power.switch_display(_require(args, "mode"), run=deps.subprocess_run)

    def scheduled_task_create(args: Mapping[str, Any]) -> None:
        scheduled_tasks.create_scheduled_task(
            _require(args, "name"),
            _require(args, "command"),
            _require(args, "schedule"),
            start_time=args.get("start_time"),
            start_date=args.get("start_date"),
            run=deps.subprocess_run,
        )

    def scheduled_task_delete(args: Mapping[str, Any]) -> None:
        scheduled_tasks.delete_scheduled_task(_require(args, "name"), run=deps.subprocess_run)

    def scheduled_task_query(args: Mapping[str, Any]) -> dict[str, Any]:
        return asdict(scheduled_tasks.query_scheduled_task(_require(args, "name"), run=deps.subprocess_run))

    def scheduled_task_list(args: Mapping[str, Any]) -> list[str]:
        return scheduled_tasks.list_scheduled_tasks(run=deps.subprocess_run)

    def printing_list_printers(args: Mapping[str, Any]) -> list[str]:
        return printing.list_printers(printer_api=deps.printer_api)

    def printing_get_default_printer(args: Mapping[str, Any]) -> str | None:
        return printing.get_default_printer(printer_api=deps.printer_api)

    def printing_set_default_printer(args: Mapping[str, Any]) -> None:
        printing.set_default_printer(_require(args, "name"), printer_api=deps.printer_api)

    def printing_print_file(args: Mapping[str, Any]) -> None:
        printing.print_file(
            _require(args, "path"),
            printer_name=args.get("printer"),
            printer_api=deps.printer_api,
            shell_execute=deps.shell_execute,
        )

    def printing_print_text(args: Mapping[str, Any]) -> None:
        printing.print_text(
            _require(args, "printer"),
            _require(args, "text"),
            document_name=args.get("document_name", "JARVIS system_control print job"),
            printer_api=deps.printer_api,
        )

    def file_move(args: Mapping[str, Any]) -> str:
        return str(files.move_file(_require(args, "src"), _require(args, "dst"), root=deps.files_root))

    def file_rename(args: Mapping[str, Any]) -> str:
        return str(
            files.rename_file(_require(args, "path"), _require(args, "new_name"), root=deps.files_root)
        )

    def file_zip(args: Mapping[str, Any]) -> str:
        return str(
            files.zip_paths(_require(args, "paths"), _require(args, "zip_path"), root=deps.files_root)
        )

    def process_kill(args: Mapping[str, Any]) -> list[int]:
        return processes.kill_process(
            name=args.get("name"),
            pid=args.get("pid"),
            own_pid=deps.own_pid,
            venv_dir=deps.venv_dir,
            process_iter=deps.process_iter,
            process_factory=deps.process_factory,
        )

    return {
        "power.list_plans": power_list_plans,
        "power.get_active_plan": power_get_active_plan,
        "power.set_plan": power_set_plan,
        "wifi.list_interfaces": wifi_list_interfaces,
        "wifi.set_enabled": wifi_set_enabled,
        "bluetooth.list_devices": bluetooth_list_devices,
        "bluetooth.set_enabled": bluetooth_set_enabled,
        "display.switch": display_switch,
        "scheduled_task.create": scheduled_task_create,
        "scheduled_task.delete": scheduled_task_delete,
        "scheduled_task.query": scheduled_task_query,
        "scheduled_task.list": scheduled_task_list,
        "printing.list_printers": printing_list_printers,
        "printing.get_default_printer": printing_get_default_printer,
        "printing.set_default_printer": printing_set_default_printer,
        "printing.print_file": printing_print_file,
        "printing.print_text": printing_print_text,
        "file.move": file_move,
        "file.rename": file_rename,
        "file.zip": file_zip,
        "process.kill": process_kill,
    }


def build_system_control_handler(
    *,
    deps: SystemControlDeps | None = None,
    actions: Mapping[str, ActionFn] | None = None,
) -> Callable[[Job], None]:
    """Build the ``system_control`` job handler: dispatch ``payload["action"]``.

    ``deps`` bundles every external dependency (subprocess runner, printer
    API, psutil hooks, file-ops root, ...) as one injectable unit. ``actions``
    overrides the whole dispatch table directly -- the seam handler-level
    tests use to prove dispatch/error behavior (unknown action, missing arg,
    the wifi guard propagating end to end) without wiring all twenty real
    actions through fakes at once; each real action is independently
    unit-tested in its own module (``tests/executor/system_control/``).
    """
    registry = actions if actions is not None else _build_action_registry(deps or SystemControlDeps())

    def _handle(job: Job) -> None:
        action = job.payload.get("action")
        if action not in registry:
            raise UnknownSystemControlActionError(
                f"no system_control action registered for {action!r}"
            )
        args = job.payload.get("args") or {}
        registry[action](args)
        logger.info("system_control action %s completed (job=%s)", action, job.id)

    return _handle
