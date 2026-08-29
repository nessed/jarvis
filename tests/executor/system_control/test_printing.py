"""Tests for executor.system_control.printing. Every win32print/win32api call
is a fake -- nothing here talks to a real spooler or printer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from executor.system_control import printing


class _FakePrinterAPI:
    PRINTER_ENUM_LOCAL = 2
    PRINTER_ENUM_CONNECTIONS = 4

    def __init__(self, printers=None, default=None):
        self._printers = printers or []
        self._default = default
        self.set_default_calls: list[str] = []
        self.doc_calls: list[dict] = []
        self._handle_counter = 0
        self._written: list[bytes] = []

    def EnumPrinters(self, flags, name=None, level=1):
        return [(0, "", printer_name, "") for printer_name in self._printers]

    def GetDefaultPrinter(self):
        if self._default is None:
            raise Exception("no default printer set")
        return self._default

    def SetDefaultPrinter(self, name):
        self.set_default_calls.append(name)
        self._default = name

    def OpenPrinter(self, name):
        self._handle_counter += 1
        return f"handle-{self._handle_counter}-{name}"

    def ClosePrinter(self, handle):
        self.doc_calls.append({"op": "close", "handle": handle})

    def StartDocPrinter(self, handle, level, doc_info):
        self.doc_calls.append({"op": "start_doc", "handle": handle, "doc_info": doc_info})
        return 1

    def StartPagePrinter(self, handle):
        self.doc_calls.append({"op": "start_page", "handle": handle})

    def WritePrinter(self, handle, data):
        self._written.append(data)
        self.doc_calls.append({"op": "write", "handle": handle, "data": data})
        return len(data)

    def EndPagePrinter(self, handle):
        self.doc_calls.append({"op": "end_page", "handle": handle})

    def EndDocPrinter(self, handle):
        self.doc_calls.append({"op": "end_doc", "handle": handle})


def test_list_printers_returns_names_from_enum_printers() -> None:
    api = _FakePrinterAPI(printers=["HP LaserJet", "Microsoft Print to PDF"])

    assert printing.list_printers(printer_api=api) == ["HP LaserJet", "Microsoft Print to PDF"]


def test_get_default_printer_returns_name() -> None:
    api = _FakePrinterAPI(default="HP LaserJet")

    assert printing.get_default_printer(printer_api=api) == "HP LaserJet"


def test_get_default_printer_returns_none_when_unset() -> None:
    api = _FakePrinterAPI(default=None)

    assert printing.get_default_printer(printer_api=api) is None


def test_set_default_printer_delegates() -> None:
    api = _FakePrinterAPI()

    printing.set_default_printer("HP LaserJet", printer_api=api)

    assert api.set_default_calls == ["HP LaserJet"]


def test_print_text_sequences_start_doc_start_page_write_end_page_end_doc() -> None:
    api = _FakePrinterAPI()

    printing.print_text("HP LaserJet", "hello world", printer_api=api)

    ops = [call["op"] for call in api.doc_calls]
    assert ops == ["start_doc", "start_page", "write", "end_page", "end_doc", "close"]
    write_call = next(c for c in api.doc_calls if c["op"] == "write")
    assert write_call["data"] == b"hello world"


def test_print_file_raises_file_not_found_for_missing_path(tmp_path: Path) -> None:
    api = _FakePrinterAPI()

    with pytest.raises(FileNotFoundError):
        printing.print_file(tmp_path / "does-not-exist.txt", printer_api=api, shell_execute=lambda *a: None)


def test_print_file_invokes_shell_execute_print_verb(tmp_path: Path) -> None:
    target = tmp_path / "doc.txt"
    target.write_text("hello")
    api = _FakePrinterAPI()
    calls = []

    def fake_shell_execute(*args):
        calls.append(args)

    printing.print_file(target, printer_api=api, shell_execute=fake_shell_execute)

    assert calls[0][1] == "print"
    assert calls[0][2] == str(target)


def test_print_file_switches_default_printer_and_restores_it(tmp_path: Path) -> None:
    target = tmp_path / "doc.txt"
    target.write_text("hello")
    api = _FakePrinterAPI(default="OriginalPrinter")
    calls = []

    printing.print_file(
        target, printer_name="TempPrinter", printer_api=api, shell_execute=lambda *a: calls.append(a)
    )

    assert api.set_default_calls == ["TempPrinter", "OriginalPrinter"]


def test_print_file_restores_default_printer_even_if_shell_execute_raises(tmp_path: Path) -> None:
    target = tmp_path / "doc.txt"
    target.write_text("hello")
    api = _FakePrinterAPI(default="OriginalPrinter")

    def raising_shell_execute(*args):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        printing.print_file(
            target, printer_name="TempPrinter", printer_api=api, shell_execute=raising_shell_execute
        )

    assert api.set_default_calls == ["TempPrinter", "OriginalPrinter"]
