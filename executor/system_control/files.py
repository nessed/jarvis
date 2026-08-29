"""Confined file moves, renames, and zipping (plain stdlib: shutil/zipfile/pathlib).

Every write is confined to a configurable root -- ``JARVIS_FILE_OPS_ROOT`` --
the same defense ``executor/flp/sort.py``'s ``flp_sort_root()`` /
path-containment guard uses for ``.flp`` writes: resolve the target, then
require it to be the root or a true descendant of it via
``Path.relative_to()``, never a string-prefix check (which a sibling
directory name like ``file_ops_workspace_evil`` could spoof against a naive
prefix comparison).
"""

from __future__ import annotations

import os
import shutil
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path


class FileOpsPathOutsideRootError(Exception):
    """Raised when a file-ops target resolves outside the configured safe root."""


def file_ops_root(environ: Mapping[str, str] | None = None) -> Path:
    """The only directory a ``system_control`` file operation may write inside.

    Reads ``JARVIS_FILE_OPS_ROOT`` at call time (env-configurable, matching
    ``flp_sort_root()``'s convention). Defaults to a dedicated
    ``file_ops_workspace/`` directory under the repository root -- not
    ``Path.home() / "Desktop"`` or any other real user directory, per
    docs/tasks/laptop-system-control.md's explicit warning against picking
    an "obviously scoped" default that is actually a real user directory.
    """
    settings = os.environ if environ is None else environ
    raw = settings.get("JARVIS_FILE_OPS_ROOT")
    if raw:
        return Path(raw).resolve()
    repository_root = Path(__file__).resolve().parent.parent.parent
    return (repository_root / "file_ops_workspace").resolve()


def _ensure_within_root(path: str | Path, root: Path) -> Path:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise FileOpsPathOutsideRootError(
            f"file-ops path {str(path)!r} resolves to {resolved}, which is outside "
            f"the configured safe root {root} -- refusing to touch it"
        ) from None
    return resolved


def move_file(src: str | Path, dst: str | Path, *, root: Path | None = None) -> Path:
    """Move ``src`` to ``dst``, refusing if either path resolves outside ``root``."""
    safe_root = (root if root is not None else file_ops_root()).resolve()
    source = _ensure_within_root(src, safe_root)
    if not source.exists():
        raise FileNotFoundError(source)
    destination = _ensure_within_root(dst, safe_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return destination


def rename_file(path: str | Path, new_name: str, *, root: Path | None = None) -> Path:
    """Rename ``path`` in place to ``new_name`` (same parent directory).

    ``new_name`` must be a bare filename -- a path separator in it would
    otherwise let a rename smuggle the file to an arbitrary sibling
    directory under a different guise than a "rename".
    """
    if os.sep in new_name or (os.altsep and os.altsep in new_name):
        raise ValueError(f"new_name must be a bare filename, got {new_name!r}")
    safe_root = (root if root is not None else file_ops_root()).resolve()
    source = _ensure_within_root(path, safe_root)
    if not source.exists():
        raise FileNotFoundError(source)
    destination = _ensure_within_root(source.with_name(new_name), safe_root)
    source.rename(destination)
    return destination


def zip_paths(paths: Sequence[str | Path], zip_path: str | Path, *, root: Path | None = None) -> Path:
    """Zip every path in ``paths`` (files or directory trees) into ``zip_path``.

    Directory trees are stored with paths relative to the directory's own
    parent, so the archive's top-level entry is the directory itself.
    """
    safe_root = (root if root is not None else file_ops_root()).resolve()
    sources = [_ensure_within_root(p, safe_root) for p in paths]
    destination = _ensure_within_root(zip_path, safe_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sources:
            if not source.exists():
                raise FileNotFoundError(source)
            if source.is_dir():
                for file_path in source.rglob("*"):
                    if file_path.is_file():
                        archive.write(file_path, file_path.relative_to(source.parent))
            else:
                archive.write(source, source.name)
    return destination
