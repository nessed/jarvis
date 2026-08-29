"""Printer enumeration/default-selection and print submission via pywin32.

``win32print`` is already part of the pinned ``pywin32`` dependency (import
confirmed 2026-08-29, see docs/tasks/laptop-system-control.md) -- this module
adds no new dependency. File printing uses ``win32api.ShellExecute``'s
"print" verb (also part of the same ``pywin32`` install) so an arbitrary
file type gets printed by whatever application Windows already associates
with it, rather than this module building a raw spool job by hand for every
possible file format.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import win32api
import win32print

logger = logging.getLogger(__name__)


class Win32PrintModule(Protocol):
    """The subset of ``win32print``'s surface this module calls, for fake injection in tests."""

    PRINTER_ENUM_LOCAL: int
    PRINTER_ENUM_CONNECTIONS: int

    def EnumPrinters(self, flags: int, name: Any = None, level: int = 1) -> Any: ...
    def GetDefaultPrinter(self) -> str: ...
    def SetDefaultPrinter(self, name: str) -> None: ...
    def OpenPrinter(self, name: str) -> Any: ...
    def ClosePrinter(self, handle: Any) -> None: ...
    def StartDocPrinter(self, handle: Any, level: int, doc_info: tuple) -> int: ...
    def StartPagePrinter(self, handle: Any) -> None: ...
    def WritePrinter(self, handle: Any, data: bytes) -> int: ...
    def EndPagePrinter(self, handle: Any) -> None: ...
    def EndDocPrinter(self, handle: Any) -> None: ...


def list_printers(*, printer_api: Win32PrintModule = win32print) -> list[str]:
    """Names of every locally installed or connected printer.

    ``EnumPrinters`` returns one tuple per printer, ``(flags, description,
    name, comment)`` -- index 2 is the printer name.
    """
    flags = printer_api.PRINTER_ENUM_LOCAL | printer_api.PRINTER_ENUM_CONNECTIONS
    return [entry[2] for entry in printer_api.EnumPrinters(flags)]


def get_default_printer(*, printer_api: Win32PrintModule = win32print) -> str | None:
    """The current default printer's name, or ``None`` if no default is set."""
    try:
        return printer_api.GetDefaultPrinter()
    except Exception:
        return None


def set_default_printer(name: str, *, printer_api: Win32PrintModule = win32print) -> None:
    """Set the system default printer by exact name."""
    printer_api.SetDefaultPrinter(name)


def print_text(
    printer_name: str,
    text: str,
    *,
    document_name: str = "JARVIS system_control print job",
    printer_api: Win32PrintModule = win32print,
) -> None:
    """Submit ``text`` as a single raw print job to ``printer_name``."""
    handle = printer_api.OpenPrinter(printer_name)
    try:
        printer_api.StartDocPrinter(handle, 1, (document_name, None, "RAW"))
        try:
            printer_api.StartPagePrinter(handle)
            printer_api.WritePrinter(handle, text.encode("utf-8"))
            printer_api.EndPagePrinter(handle)
        finally:
            printer_api.EndDocPrinter(handle)
    finally:
        printer_api.ClosePrinter(handle)


def print_file(
    path: str | Path,
    *,
    printer_name: str | None = None,
    printer_api: Win32PrintModule = win32print,
    shell_execute: Callable[..., Any] = win32api.ShellExecute,
) -> None:
    """Print an existing file via the OS's associated "print" shell verb.

    Raises :class:`FileNotFoundError` if ``path`` does not exist. Windows'
    "print" verb has no per-call printer argument, so when ``printer_name``
    is given this temporarily switches the system default printer for the
    duration of the call and restores the previous default afterward --
    even if printing itself raises.
    """
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(target)

    previous_default: str | None = None
    if printer_name is not None:
        previous_default = get_default_printer(printer_api=printer_api)
        set_default_printer(printer_name, printer_api=printer_api)
    try:
        shell_execute(0, "print", str(target), None, ".", 0)
    finally:
        if printer_name is not None and previous_default:
            set_default_printer(previous_default, printer_api=printer_api)
