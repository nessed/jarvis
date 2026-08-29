"""Tests for executor.system_control.scheduled_tasks. Every ``schtasks`` call
is faked -- nothing here creates, queries, or deletes a real scheduled task.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from executor.system_control import scheduled_tasks


@dataclass
class _FakeResult:
    stdout: str = ""
    returncode: int = 0


@dataclass
class _RecordingRunner:
    result: _FakeResult = field(default_factory=_FakeResult)
    calls: list[dict] = field(default_factory=list)

    def __call__(self, args, **kwargs):
        self.calls.append({"args": list(args), "kwargs": kwargs})
        return self.result


def test_create_scheduled_task_builds_full_argv() -> None:
    runner = _RecordingRunner()

    scheduled_tasks.create_scheduled_task(
        "JarvisProbe", 'notepad.exe "C:\\some file.txt"', "ONCE",
        start_time="12:00", start_date="08/29/2026", run=runner,
    )

    assert runner.calls[0]["args"] == [
        "schtasks", "/create",
        "/tn", "JarvisProbe",
        "/tr", 'notepad.exe "C:\\some file.txt"',
        "/sc", "ONCE",
        "/f",
        "/st", "12:00",
        "/sd", "08/29/2026",
    ]


def test_create_scheduled_task_omits_optional_start_fields() -> None:
    runner = _RecordingRunner()

    scheduled_tasks.create_scheduled_task("JarvisProbe", "notepad.exe", "ONLOGON", run=runner)

    assert runner.calls[0]["args"] == [
        "schtasks", "/create", "/tn", "JarvisProbe", "/tr", "notepad.exe", "/sc", "ONLOGON", "/f",
    ]


def test_delete_scheduled_task_uses_force_flag() -> None:
    runner = _RecordingRunner()

    scheduled_tasks.delete_scheduled_task("JarvisProbe", run=runner)

    assert runner.calls[0]["args"] == ["schtasks", "/delete", "/tn", "JarvisProbe", "/f"]


_QUERY_LIST_OUTPUT = """
Folder: \\
HostName:                            LAPTOP
TaskName:                            \\JarvisProbe
Next Run Time:                       8/30/2026 12:00:00 PM
Status:                              Ready
"""


def test_query_scheduled_task_parses_status_and_next_run_time() -> None:
    runner = _RecordingRunner(result=_FakeResult(stdout=_QUERY_LIST_OUTPUT, returncode=0))

    info = scheduled_tasks.query_scheduled_task("JarvisProbe", run=runner)

    assert info == scheduled_tasks.ScheduledTaskInfo(
        name="JarvisProbe", status="Ready", next_run_time="8/30/2026 12:00:00 PM"
    )


def test_query_scheduled_task_raises_not_found_on_nonzero_exit() -> None:
    runner = _RecordingRunner(result=_FakeResult(stdout="ERROR: not found", returncode=1))

    with pytest.raises(scheduled_tasks.ScheduledTaskNotFoundError):
        scheduled_tasks.query_scheduled_task("Ghost", run=runner)


_QUERY_CSV_OUTPUT = (
    '"\\JarvisProbe","Ready","8/30/2026 12:00:00 PM"\r\n'
    '"\\Microsoft\\Windows\\SomeTask","Running","N/A"\r\n'
)


def test_list_scheduled_tasks_parses_csv_names() -> None:
    runner = _RecordingRunner(result=_FakeResult(stdout=_QUERY_CSV_OUTPUT))

    names = scheduled_tasks.list_scheduled_tasks(run=runner)

    assert names == ["JarvisProbe", "Microsoft\\Windows\\SomeTask"]
