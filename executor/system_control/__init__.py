"""Blueprint 2.4: Windows system-control capabilities as one executor job kind.

Five capabilities, five modules, one dispatch handler:

- ``power.py``      -- power plan, wifi, Bluetooth-radio, display-output switching.
- ``scheduled_tasks.py`` -- Windows Scheduled Tasks via ``schtasks``.
- ``printing.py``   -- printer enumeration/default selection and print submission.
- ``files.py``      -- confined file moves, renames, zipping.
- ``processes.py``  -- guarded process termination.
- ``handler.py``    -- ``build_system_control_handler()``, the ``system_control``
  job's ``action``-dispatch entry point.

Nothing here is wired into ``executor/poller.py``'s ``DEFAULT_HANDLERS`` by
this package -- see docs/tasks/laptop-system-control-report.md for the one
line CORE adds there.
"""

from __future__ import annotations
