"""Tests for executor.system_control.files. Every operation runs against a
real ``tmp_path`` scoped as the safe root -- nothing here touches any real
directory outside pytest's own temp workspace.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from executor.system_control import files


def test_file_ops_root_reads_env_var(tmp_path: Path) -> None:
    root = files.file_ops_root({"JARVIS_FILE_OPS_ROOT": str(tmp_path)})
    assert root == tmp_path.resolve()


def test_file_ops_root_default_is_a_dedicated_directory_not_home_or_desktop() -> None:
    root = files.file_ops_root({})
    assert root.name == "file_ops_workspace"
    assert root != Path.home()
    assert root != Path.home() / "Desktop"


def test_move_file_within_root(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("hi")
    dst = tmp_path / "sub" / "b.txt"

    result = files.move_file(src, dst, root=tmp_path)

    assert result == dst.resolve()
    assert dst.read_text() == "hi"
    assert not src.exists()


def test_move_file_raises_for_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        files.move_file(tmp_path / "ghost.txt", tmp_path / "dst.txt", root=tmp_path)


def test_move_file_refuses_source_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("hi")

    with pytest.raises(files.FileOpsPathOutsideRootError):
        files.move_file(outside, root / "dst.txt", root=root)


def test_move_file_refuses_destination_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    src = root / "a.txt"
    src.write_text("hi")

    with pytest.raises(files.FileOpsPathOutsideRootError):
        files.move_file(src, tmp_path / "outside.txt", root=root)


def test_move_file_refuses_a_sibling_directory_that_string_prefixes_the_root(tmp_path: Path) -> None:
    """``root_evil`` string-prefixes ``root`` but must not be treated as inside it."""
    root = tmp_path / "root"
    root.mkdir()
    evil = tmp_path / "root_evil"
    evil.mkdir()
    src = evil / "a.txt"
    src.write_text("hi")

    with pytest.raises(files.FileOpsPathOutsideRootError):
        files.move_file(src, root / "dst.txt", root=root)


def test_rename_file_within_root(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("hi")

    result = files.rename_file(src, "b.txt", root=tmp_path)

    assert result == (tmp_path / "b.txt").resolve()
    assert result.read_text() == "hi"
    assert not src.exists()


def test_rename_file_rejects_a_path_separator_in_new_name(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("hi")

    with pytest.raises(ValueError):
        files.rename_file(src, "sub/b.txt", root=tmp_path)


def test_rename_file_raises_for_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        files.rename_file(tmp_path / "ghost.txt", "b.txt", root=tmp_path)


def test_rename_file_refuses_source_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "a.txt"
    outside.write_text("hi")

    with pytest.raises(files.FileOpsPathOutsideRootError):
        files.rename_file(outside, "b.txt", root=root)


def test_zip_paths_zips_individual_files(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    a.write_text("A")
    b = tmp_path / "b.txt"
    b.write_text("B")
    zip_path = tmp_path / "out.zip"

    result = files.zip_paths([a, b], zip_path, root=tmp_path)

    assert result == zip_path.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        assert sorted(archive.namelist()) == ["a.txt", "b.txt"]


def test_zip_paths_zips_a_directory_tree(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "nested").mkdir(parents=True)
    (project / "top.txt").write_text("top")
    (project / "nested" / "deep.txt").write_text("deep")
    zip_path = tmp_path / "out.zip"

    files.zip_paths([project], zip_path, root=tmp_path)

    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(archive.namelist())
        assert "project/top.txt" in names
        assert "project/nested/deep.txt" in names


def test_zip_paths_raises_for_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        files.zip_paths([tmp_path / "ghost.txt"], tmp_path / "out.zip", root=tmp_path)


def test_zip_paths_refuses_source_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "a.txt"
    outside.write_text("hi")

    with pytest.raises(files.FileOpsPathOutsideRootError):
        files.zip_paths([outside], root / "out.zip", root=root)


def test_zip_paths_refuses_destination_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    a = root / "a.txt"
    a.write_text("hi")

    with pytest.raises(files.FileOpsPathOutsideRootError):
        files.zip_paths([a], tmp_path / "out.zip", root=root)
