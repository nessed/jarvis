"""Blueprint 2.2: the "sort out this FLP" job.

Pipeline the ``flp_sort`` job handler runs: ``flp_backup`` the original,
``load`` it, ``apply_rules`` against a ruleset, ``save`` it back, then
``verify`` by re-parsing the saved file and confirming the renames actually
landed on disk (not just that the write call returned). Registered as job
kind ``flp_sort`` in ``executor/poller.py``'s ``DEFAULT_HANDLERS``.

Interpreter blocker -- resolved
--------------------------------
``load()``/``save()`` are thin wrappers around ``pyflp.parse()``/
``pyflp.save()``. PyFLP 2.2.1 raises unconditionally on Python 3.12 (and
3.11.6+, which backported the same guard) from inside ``pyflp.parse()``:

    TypeError: <enum 'EventEnum'> has no members; specify `names=()`
    if you meant to create a new, empty, enum

The fix is environmental, not code: run this module under ``.venv311``,
pinned to CPython **3.11.5** exactly. That interpreter parses and saves real
``.flp`` files -- proved against PyFLP's own ``FL 20.8.4.flp`` fixture with a
rename that survived a save-and-re-parse round trip
(``tests/flp/test_flp_real.py``, marker ``realflp``).

Known gap on real projects -- open, see docs/blockers/pyflp-channel-groups-indexerror.md
------------------------------------------------------------------------------------------
The interpreter fix is necessary but not sufficient. Parsing a real
user project with channel groups raises inside PyFLP's own
``channel.py`` (``IndexError`` indexing its ``groups`` list), independent of
the interpreter issue above. Fixtures without channel groups (like PyFLP's
own bundled test fixture) parse clean. This module's own logic is unit-tested
against fakes/stubs and is provably correct in isolation; ``load``/``save``
themselves still need PyFLP to clear this gap before they can be exercised
against an arbitrary real project.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyflp

logger = logging.getLogger(__name__)

# Anything with a ``.mixer`` yielding objects with ``.iid``/``.name`` --
# a real ``pyflp.Project``, or a test double standing in for one.
ProjectLike = Any
InsertLike = Any


class ReorderNotSupported(Exception):
    """Raised when a ruleset rule asks for mixer-insert reordering.

    PyFLP has no API to change an insert's position -- its own maintainers
    mark this unimplemented in ``pyflp/mixer.py``: ``# TODO A move() method
    to change the placement of Inserts; it's difficult!``. Renaming an
    insert is well-supported (``Insert.name`` is a settable property);
    physically moving one is not, and faking it by rewriting raw event
    order would risk corrupting a real project for a placeholder ruleset
    whose shape isn't even the user's dictated convention yet (blueprint
    2.1). Rather than silently ignore a requested reorder, this fails loudly
    and up front, before any rename in the same ruleset is applied.
    """


@dataclass(frozen=True)
class InsertRename:
    """One mixer insert whose name changed, identified by its stable ``iid``.

    ``iid`` (not list position) is what PyFLP itself uses for identity --
    ``Mixer.__iter__`` yields ``Insert(iid=i - 1, ...)`` per insert, with -1
    reserved for "current" and 0 for master -- so this is what
    ``verify()`` uses to re-check by insert, not import order.
    """

    iid: int
    before: str
    after: str


@dataclass(frozen=True)
class MixerDiff:
    """Old name -> new name per mixer insert, produced by :func:`diff_report`."""

    renames: tuple[InsertRename, ...]

    def as_dict(self) -> dict[str, str]:
        """``{before: after}`` for every insert that actually changed name."""
        return {rename.before: rename.after for rename in self.renames}

    def __bool__(self) -> bool:
        return bool(self.renames)


def flp_backup(path: str | Path, *, now: Callable[[], datetime] | None = None) -> Path:
    """Copy ``path`` to a timestamped backup alongside it before any write.

    Backup name: ``<stem>.<UTC compact ISO>.bak<suffix>``, e.g.
    ``song.2026-08-27T120000.bak.flp``. Colons are stripped from the
    timestamp since they are illegal in Windows filenames. ``now`` is
    injectable for deterministic tests; defaults to the real current UTC
    time. Uses ``shutil.copy2`` (preserves mtime) rather than a raw read/
    write so the backup is a byte-for-byte copy, not a re-serialization.
    """
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(src)
    stamp = (now or (lambda: datetime.now(UTC)))().strftime("%Y-%m-%dT%H%M%S")
    backup_path = src.with_name(f"{src.stem}.{stamp}.bak{src.suffix}")
    shutil.copy2(src, backup_path)
    return backup_path


def load(path: str | Path) -> ProjectLike:
    """Parse an ``.flp`` with PyFLP. See the module docstring for the current blocker."""
    return pyflp.parse(Path(path))


def save(project: ProjectLike, path: str | Path) -> None:
    """Save a PyFLP project back to disk. See the module docstring for the current blocker."""
    pyflp.save(project, Path(path))


def _snapshot_names(project_or_names: ProjectLike | Mapping[int, str]) -> dict[int, str]:
    """``{insert.iid: insert.name}``, accepting an already-computed mapping too.

    Letting both :func:`apply_rules` and :func:`diff_report` accept either a
    live project or a plain ``{iid: name}`` mapping means a caller who
    already has a snapshot (e.g. taken before a mutation) never has to
    re-walk ``project.mixer``, and tests can exercise ``diff_report`` with
    plain dicts instead of a PyFLP project or a fake standing in for one.
    """
    if isinstance(project_or_names, Mapping):
        return dict(project_or_names)
    return {insert.iid: insert.name for insert in project_or_names.mixer}


def diff_report(
    before: ProjectLike | Mapping[int, str], after: ProjectLike | Mapping[int, str]
) -> MixerDiff:
    """Old name -> new name per mixer insert, comparing two states by ``iid``.

    ``before``/``after`` are each either a project-like object (read via its
    ``.mixer``) or a pre-computed ``{iid: name}`` mapping -- see
    :func:`_snapshot_names`. An insert present in only one side is skipped
    (nothing to diff against); only inserts present in both, with a name
    that actually differs, are included.
    """
    before_names = _snapshot_names(before)
    after_names = _snapshot_names(after)
    shared_iids = sorted(before_names.keys() & after_names.keys())
    renames = tuple(
        InsertRename(iid=iid, before=before_names[iid], after=after_names[iid])
        for iid in shared_iids
        if before_names[iid] != after_names[iid]
    )
    return MixerDiff(renames=renames)


def apply_rules(project: ProjectLike, ruleset: Mapping[str, Any]) -> MixerDiff:
    """Rename mixer inserts per ``ruleset``, mutating ``project`` in place.

    Ruleset shape (placeholder -- see the module-level note below)::

        {"rules": [{"match": "<current insert name>",
                    "rename_to": "<new name>",
                    "position": None}, ...]}

    Each rule matches an insert by an *exact* current-name comparison and
    sets its ``.name``. An insert matching no rule, and a rule matching no
    insert, are both silent no-ops -- consistent with this being a
    placeholder ruleset the real one (blueprint 2.1) will replace wholesale.

    Reordering: any rule with a non-``None`` "position" raises
    :class:`ReorderNotSupported` before *any* rule in the call is applied
    (validated up front, so a call either fully applies or mutates nothing).
    See :class:`ReorderNotSupported` for why.

    Returns the :class:`MixerDiff` of what actually changed, via
    :func:`diff_report` against a snapshot taken before mutating.
    """
    for rule in ruleset.get("rules", []):
        if rule.get("position") is not None:
            raise ReorderNotSupported(
                f"rule for {rule.get('match')!r} requested position "
                f"{rule['position']!r}, but PyFLP has no insert-move API"
            )

    before_names = _snapshot_names(project)
    rules: Sequence[Mapping[str, Any]] = ruleset.get("rules", [])
    for insert in project.mixer:
        for rule in rules:
            if insert.name == rule["match"]:
                insert.name = rule["rename_to"]
                break
    return diff_report(before_names, project)


def verify(
    path: str | Path,
    expected_diff: MixerDiff,
    *,
    loader: Callable[[str | Path], ProjectLike] = load,
) -> bool:
    """Re-parse the saved file and confirm every expected rename actually stuck.

    This is read-back verification, not just "the write call didn't raise":
    a short or corrupted write can produce a file that still opens but with
    stale or missing insert names, and only re-parsing catches that.
    ``loader`` defaults to :func:`load` (real PyFLP) and is injectable so
    this can be tested against a fake reparse without a working PyFLP
    install -- see the module docstring for why that matters right now.

    Any exception from ``loader`` (a real corrupted/truncated file raises
    PyFLP's own ``HeaderCorrupted`` from ``parse()``) is treated as
    verification failure, not propagated: a caller asking "did this stick"
    should get a plain no, matching how ``executor.poller`` already treats
    handler failures as type-only diagnostics rather than raw exceptions.
    """
    try:
        reparsed = loader(path)
        actual_names = _snapshot_names(reparsed)
    except Exception as exc:
        logger.warning("verify() failed to re-parse %s (%s)", path, type(exc).__name__)
        return False

    return all(
        actual_names.get(rename.iid) == rename.after for rename in expected_diff.renames
    )


class FlpSortVerificationFailed(Exception):
    """Raised when an ``flp_sort`` job's saved file fails :func:`verify`.

    Deliberately an exception rather than a swallowed ``False``: this is
    what a claimed job raises back to ``executor.poller.poll_once``, whose
    existing retry/backoff/dead-letter path already treats any handler
    exception as a type-only diagnostic (see its docstring) -- a verify
    failure earns exactly that same retry, not a silent "done".
    """


class FlpSortPathOutsideRoot(Exception):
    """Raised when an ``flp_sort`` job names a path outside its safe root.

    Blueprint 2.1: "Originals never get touched." :func:`flp_backup` copies
    the target before any write, but the path a job names could be
    anything, including a real project living outside the safe root -- so
    the only thing that actually keeps an original untouched is refusing to
    treat it as a legal write target in the first place. Raised by
    :func:`build_flp_sort_handler`'s handler before ``backup()`` or
    ``loader()`` ever run, matching :class:`ReorderNotSupported`'s
    fail-loudly-and-up-front approach -- a type-only diagnostic for
    ``executor.poller``'s existing retry/dead-letter path, not something a
    caller is expected to catch and route around.
    """


def flp_sort_root(environ: Mapping[str, str] | None = None) -> Path:
    """The only directory an ``flp_sort`` job may write inside.

    Reads ``JARVIS_FLP_SORT_ROOT`` at call time, following
    ``executor.heartbeat.heartbeat_path``'s pattern for env-configured paths
    in this codebase (and ``tests/flp/test_flp_real.py``'s
    ``JARVIS_FLP_FIXTURE`` for the equivalent test-side convention).
    Defaults to ``test_projects/`` resolved from the repository root --
    this file lives at ``executor/flp/sort.py``, three parents up from the
    root -- matching blueprint 2.1's guinea-pig directory.
    """
    settings = os.environ if environ is None else environ
    raw = settings.get("JARVIS_FLP_SORT_ROOT")
    if raw:
        return Path(raw).resolve()
    repository_root = Path(__file__).resolve().parent.parent.parent
    return (repository_root / "test_projects").resolve()


def _ensure_path_within_root(path: str | Path, root: Path) -> Path:
    """Resolve ``path`` and confirm it is ``root`` or a true descendant of it.

    Raises :class:`FlpSortPathOutsideRoot` otherwise. Uses ``Path.resolve()``
    (so ``..`` segments and symlinks can't smuggle a path out) plus
    ``Path.relative_to()`` (so containment is checked by path *parts*, not
    text) -- a naive string-prefix check would wrongly let
    ``test_projects_evil/song.flp`` past a ``test_projects/`` root, since
    the string ``"test_projects"`` really is a prefix of
    ``"test_projects_evil"``.
    """
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise FlpSortPathOutsideRoot(
            f"flp_sort job path {str(path)!r} resolves to {resolved}, which is "
            f"outside the configured safe root {root} -- refusing to write"
        ) from None
    return resolved


def diff_report_path(target: str | Path, *, now: Callable[[], datetime] | None = None) -> Path:
    """Where :func:`build_flp_sort_handler` writes ``target``'s diff report.

    Same directory and timestamp format as :func:`flp_backup`'s backup file:
    ``<stem>.<UTC compact ISO>.diff.json``. ``now`` is injectable for the
    same reason ``flp_backup``'s is -- deterministic tests -- and
    :func:`build_flp_sort_handler` passes the *same* captured instant to
    both, so a run's backup and its diff report share one timestamp and are
    trivially pairable by it.
    """
    target_path = Path(target)
    stamp = (now or (lambda: datetime.now(UTC)))().strftime("%Y-%m-%dT%H%M%S")
    return target_path.with_name(f"{target_path.stem}.{stamp}.diff.json")


def write_diff_report(path: str | Path, diff: MixerDiff) -> None:
    """The real default ``report_writer``: write ``diff`` to ``path`` as JSON.

    Writes ``diff.as_dict()`` (``{before: after}``) rather than the raw
    :class:`InsertRename` tuples: blueprint 2.3 has the user comparing this
    file against FL Studio's mixer by eye, and old-name -> new-name pairs
    are what is directly comparable there. The ``iid`` on each
    ``InsertRename`` is an internal identity :func:`verify` needs to re-check
    by insert rather than list position -- not something visible in FL
    Studio's UI, and not useful noise in a report a human is skimming.
    """
    Path(path).write_text(
        json.dumps(diff.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_flp_sort_handler(
    *,
    backup: Callable[..., Path] = flp_backup,
    loader: Callable[[str | Path], ProjectLike] = load,
    saver: Callable[[ProjectLike, str | Path], None] = save,
    verifier: Callable[..., bool] = verify,
    safe_root: Path | None = None,
    report_writer: Callable[[Path, MixerDiff], None] = write_diff_report,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Callable[[Any], None]:
    """Build the ``flp_sort`` job handler: backup -> load -> apply_rules -> save -> verify.

    Expects ``job.payload`` shaped ``{"path": <str>, "ruleset": <dict>}`` per
    blueprint 2.2 ("Wrapped as an executor job type (kind: flp_sort,
    payload: path + ruleset)"). Every dependency is injectable, matching
    ``executor.handlers.whatsapp.build_whatsapp_webhook_handler``'s pattern,
    so this can be unit-tested without a working PyFLP install -- see the
    module docstring for why that matters right now.

    ``safe_root`` defaults to :func:`flp_sort_root` (resolved once, at
    build time, per blueprint 2.1) but is overridable for tests. The
    resolved job path is checked against it -- raising
    :class:`FlpSortPathOutsideRoot` -- before ``backup()`` or ``loader()``
    run. ``now`` is captured once per job so ``backup()`` and the diff
    report it triggers share one timestamp (see :func:`diff_report_path`).
    A report is only written when ``apply_rules`` actually changed
    something (``MixerDiff.__bool__``); an empty report on every no-op run
    would just be noise for the blueprint 2.3 verification loop to skip
    past.
    """
    root = (safe_root if safe_root is not None else flp_sort_root()).resolve()

    def _handle(job: Any) -> None:
        path = job.payload["path"]
        ruleset = job.payload.get("ruleset", {})
        _ensure_path_within_root(path, root)

        moment = now()
        backup(path, now=lambda: moment)
        project = loader(path)
        diff = apply_rules(project, ruleset)
        saver(project, path)
        if diff:
            report_writer(diff_report_path(path, now=lambda: moment), diff)
        if not verifier(path, diff, loader=loader):
            raise FlpSortVerificationFailed(f"verify() failed after saving {path}")

    return _handle
