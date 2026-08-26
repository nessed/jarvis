"""Phase 2.2 PyFLP proof-of-concept: backup, rule-based mixer sort, verified save.

See :mod:`executor.flp.sort` for the implementation and its module docstring
for the current environment blocker (PyFLP's ``parse()`` does not work on
Python 3.12 in this venv -- tracked, not silently patched around).
"""

from __future__ import annotations

from executor.flp.sort import (
    FlpSortVerificationFailed,
    InsertRename,
    MixerDiff,
    ReorderNotSupported,
    apply_rules,
    build_flp_sort_handler,
    diff_report,
    flp_backup,
    load,
    save,
    verify,
)

__all__ = [
    "FlpSortVerificationFailed",
    "InsertRename",
    "MixerDiff",
    "ReorderNotSupported",
    "apply_rules",
    "build_flp_sort_handler",
    "diff_report",
    "flp_backup",
    "load",
    "save",
    "verify",
]
