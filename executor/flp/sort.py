"""Blueprint 2.2: PyFLP proof-of-concept for the "sort out this FLP" job.

Pipeline a future ``flp_sort`` job handler will run: ``flp_backup`` the
original, ``load`` it, ``apply_rules`` against a ruleset, ``save`` it back,
then ``verify`` by re-parsing the saved file and confirming the renames
actually landed on disk (not just that the write call returned).

Known environment blocker -- read before wiring this into a live job
--------------------------------------------------------------------
``load()``/``save()`` are thin wrappers around ``pyflp.parse()``/
``pyflp.save()`` and nothing else in this module talks to PyFLP directly.
That wrapper currently cannot be exercised end-to-end: PyFLP 2.2.1 (the
latest release on PyPI as of this writing) raises unconditionally

    TypeError: <enum 'EventEnum'> has no members; specify `names=()`
    if you meant to create a new, empty, enum

from inside ``pyflp.parse()`` on Python 3.12 (this venv is 3.12.10; PyPI
classifiers for pyflp only list 3.8-3.11). The cause: PyFLP's ``EventEnum``
is a deliberately empty base ``enum.Enum`` that individual event-id enums
(``InsertID``, ``ChannelID``, ...) subclass, and ``parse()`` looks up raw
byte values against the *base* class so unregistered subclass members fall
through to ``EventEnum._missing_``. Python 3.12's ``enum.py`` added a guard
(``EnumType.__call__``, checked via ``cls._member_map_``) that special-cases
any Enum with zero *direct* members as "functional API" construction and
raises before ``_missing_`` ever runs -- a real, upstream, unpatched
incompatibility, not a bug in this module. Reproduced with both an in-memory
empty ``Project`` and a full real ``.flp`` (PyFLP's own bundled test-suite
fixture); reordering the input never reaches the enum call, so no input can
route around it. No pyflp release newer than 2.2.1 exists on PyPI to fix
this.

Practically: this rules out generating a synthetic ``.flp`` via PyFLP alone
(scope item 3) two ways over, not one -- ``pyflp.save()`` on a from-scratch
in-memory ``Project`` also fails, separately, with ``NoModelsFound`` (an
empty ``ChannelRack`` has no channels), meaning PyFLP has no from-scratch
authoring path at all; it only round-trips files it already parsed. And
since ``parse()`` itself doesn't run under this interpreter, there is
currently no way to round-trip *any* ``.flp`` -- real or synthetic -- in
this venv. Everything below is written and unit-tested against fakes/stubs
so the logic is provably correct in isolation; ``load``/``save`` themselves
are only exercised here via monkeypatched stand-ins for ``pyflp.parse``/
``pyflp.save``, and need a real run once the interpreter or PyFLP version
changes to close this gap.
"""

from __future__ import annotations

import logging
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


def build_flp_sort_handler(
    *,
    backup: Callable[[str | Path], Path] = flp_backup,
    loader: Callable[[str | Path], ProjectLike] = load,
    saver: Callable[[ProjectLike, str | Path], None] = save,
    verifier: Callable[..., bool] = verify,
) -> Callable[[Any], None]:
    """Build the ``flp_sort`` job handler: backup -> load -> apply_rules -> save -> verify.

    Expects ``job.payload`` shaped ``{"path": <str>, "ruleset": <dict>}`` per
    blueprint 2.2 ("Wrapped as an executor job type (kind: flp_sort,
    payload: path + ruleset)"). Every dependency is injectable, matching
    ``executor.handlers.whatsapp.build_whatsapp_webhook_handler``'s pattern,
    so this can be unit-tested without a working PyFLP install -- see the
    module docstring for why that matters right now. Not registered into
    ``executor.poller.DEFAULT_HANDLERS`` by this lane; see the lane report
    for the exact line to add.
    """

    def _handle(job: Any) -> None:
        path = job.payload["path"]
        ruleset = job.payload.get("ruleset", {})
        backup(path)
        project = loader(path)
        diff = apply_rules(project, ruleset)
        saver(project, path)
        if not verifier(path, diff, loader=loader):
            raise FlpSortVerificationFailed(f"verify() failed after saving {path}")

    return _handle
