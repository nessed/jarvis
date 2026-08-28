"""Phase 2.2: backup, rule-based mixer sort, verified save.

See :mod:`executor.flp.sort` for the implementation and its module docstring
for the current environment requirement (run under ``.venv311``, pinned to
CPython 3.11.5) and the open real-project channel-groups gap.
"""

from __future__ import annotations

from executor.flp.sort import (
    FlpSortPathOutsideRoot,
    FlpSortVerificationFailed,
    InsertRename,
    MixerDiff,
    ReorderNotSupported,
    apply_rules,
    build_flp_sort_handler,
    diff_report,
    diff_report_path,
    flp_backup,
    flp_sort_root,
    load,
    save,
    verify,
    write_diff_report,
)

__all__ = [
    "FlpSortPathOutsideRoot",
    "FlpSortVerificationFailed",
    "InsertRename",
    "MixerDiff",
    "ReorderNotSupported",
    "apply_rules",
    "build_flp_sort_handler",
    "diff_report",
    "diff_report_path",
    "flp_backup",
    "flp_sort_root",
    "load",
    "save",
    "verify",
    "write_diff_report",
]
