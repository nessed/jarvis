"""Coverage for ``tools/context_status.py``, black-box.

``.githooks/pre-commit`` runs ``--write`` (and CI-equivalent checks would run
``--check``) on every commit, so a break here breaks every commit for every
lane. ``check()`` and ``main()`` are read directly against this repo's real
git history for the git-dependent assertions (read-only ``git log`` /
``rev-list`` / ``cat-file``, no network, no mutation) — only ``CONTEXT`` and
``CACHE`` are ever monkeypatched to a ``tmp_path``, so nothing here writes to
the real ``docs/context.md`` or ``.context-status.json``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tools import context_status as cs


REPO_ROOT = cs.REPO_ROOT


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _wrap(block_body: str) -> str:
    return f"before\n\n{cs.BEGIN}\n{block_body}\n{cs.END}\n\nafter\n"


# --- check(): the exit-code contract ------------------------------------


def test_check_returns_1_when_both_markers_are_missing() -> None:
    assert cs.check("docs/context.md with no generated block at all") == 1


def test_check_returns_1_when_only_begin_marker_present() -> None:
    assert cs.check(f"{cs.BEGIN}\nsome text, no end marker\n") == 1


def test_check_returns_1_when_block_was_hand_edited_and_has_no_head_line() -> None:
    current = _wrap("Someone typed something here instead of letting the tool write it.")

    assert cs.check(current) == 1


def test_check_returns_1_when_the_named_head_is_not_a_real_commit() -> None:
    current = _wrap("**HEAD** `abc1234 fake commit` on `main`, in sync with origin.")

    assert cs.check(current) == 1


def test_check_returns_0_when_head_line_names_the_current_head_exactly() -> None:
    head = _git("rev-parse", "--short", "HEAD")
    current = _wrap(f"**HEAD** `{head} whatever subject line` on `main`, in sync.")

    assert cs.check(current) == 0


def test_check_returns_0_at_the_max_lag_boundary() -> None:
    # MAX_LAG=2: naming the commit exactly two behind HEAD is still "normal".
    sha = _git("rev-parse", "--short", f"HEAD~{cs.MAX_LAG}")
    current = _wrap(f"**HEAD** `{sha} old subject` on `main`, in sync.")

    assert cs.check(current) == 0


def test_check_returns_1_once_past_the_max_lag_boundary() -> None:
    sha = _git("rev-parse", "--short", f"HEAD~{cs.MAX_LAG + 1}")
    current = _wrap(f"**HEAD** `{sha} very old subject` on `main`, in sync.")

    assert cs.check(current) == 1


def test_check_reports_the_specific_reason_on_stderr(capsys) -> None:
    cs.check("no markers here")
    assert "no generated block" in capsys.readouterr().err

    cs.check(_wrap("no HEAD line in this block"))
    assert "hand-edited" in capsys.readouterr().err

    cs.check(_wrap("**HEAD** `abc1234 x` on `main`, in sync."))
    assert "not a commit in this repo" in capsys.readouterr().err


# --- load_cache() ---------------------------------------------------------


def test_load_cache_returns_empty_dict_when_file_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cs, "CACHE", tmp_path / "missing.json")

    assert cs.load_cache() == {}


def test_load_cache_returns_empty_dict_on_malformed_json(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / ".context-status.json"
    cache_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(cs, "CACHE", cache_path)

    assert cs.load_cache() == {}


def test_load_cache_round_trips_recorded_values(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / ".context-status.json"
    cache_path.write_text(json.dumps({"offline": "9 passed"}), encoding="utf-8")
    monkeypatch.setattr(cs, "CACHE", cache_path)

    assert cs.load_cache() == {"offline": "9 passed"}


# --- working_tree() --------------------------------------------------------


def test_working_tree_reports_clean_with_nothing_changed(monkeypatch) -> None:
    monkeypatch.setattr(cs, "git", lambda *a: "")

    assert cs.working_tree() == "clean"


def test_working_tree_reports_clean_with_only_untracked_noise(monkeypatch) -> None:
    monkeypatch.setattr(cs, "git", lambda *a: "?? scratch/file.tmp\n?? scratch/other.tmp")

    assert cs.working_tree() == "clean (2 untracked)"


def test_working_tree_lists_tracked_changes_and_counts_untracked_separately(monkeypatch) -> None:
    porcelain = "\n".join(
        [" M docs/state.md", "A  tools/new.py", "?? scratch/ignored.tmp"]
    )
    monkeypatch.setattr(cs, "git", lambda *a: porcelain)

    result = cs.working_tree()

    assert result.startswith("2 changed (plus 1 untracked)")
    assert "docs/state.md" in result
    assert "tools/new.py" in result
    assert "ignored.tmp" not in result


def test_working_tree_truncates_past_twelve_changed_lines(monkeypatch) -> None:
    porcelain = "\n".join(f" M file{i}.py" for i in range(15))
    monkeypatch.setattr(cs, "git", lambda *a: porcelain)

    result = cs.working_tree()

    assert "15 changed" in result
    assert "...and 3 more" in result
    assert "file12.py" not in result  # only the first 12 are shown


# --- build_block(): sync-state phrasing -----------------------------------


def _stub_git(responses: dict[tuple[str, ...], str]):
    def _fake(*args: str) -> str:
        return responses.get(args, "")

    return _fake


def test_build_block_reports_no_upstream_when_rev_list_u_fails(monkeypatch) -> None:
    monkeypatch.setattr(cs, "load_cache", dict)
    monkeypatch.setattr(
        cs,
        "git",
        _stub_git(
            {
                ("log", "-1", "--format=%h %s"): "abc1234 a commit",
                ("rev-parse", "--abbrev-ref", "HEAD"): "main",
                ("log", "-8", "--format=- `%h` %s  _(%ad)_", "--date=short"): "- `abc1234` a commit  _(2026-01-01)_",
                ("rev-list", "--count", "@{u}..HEAD"): "",
                ("rev-list", "--count", "HEAD..@{u}"): "",
            }
        ),
    )

    assert "no upstream configured" in cs.build_block()


def test_build_block_reports_in_sync(monkeypatch) -> None:
    monkeypatch.setattr(cs, "load_cache", dict)
    monkeypatch.setattr(
        cs,
        "git",
        _stub_git(
            {
                ("log", "-1", "--format=%h %s"): "abc1234 a commit",
                ("rev-parse", "--abbrev-ref", "HEAD"): "main",
                ("log", "-8", "--format=- `%h` %s  _(%ad)_", "--date=short"): "",
                ("rev-list", "--count", "@{u}..HEAD"): "0",
                ("rev-list", "--count", "HEAD..@{u}"): "0",
            }
        ),
    )

    assert "in sync with origin" in cs.build_block()


def test_build_block_reports_ahead_and_behind_counts(monkeypatch) -> None:
    monkeypatch.setattr(cs, "load_cache", dict)
    monkeypatch.setattr(
        cs,
        "git",
        _stub_git(
            {
                ("log", "-1", "--format=%h %s"): "abc1234 a commit",
                ("rev-parse", "--abbrev-ref", "HEAD"): "main",
                ("log", "-8", "--format=- `%h` %s  _(%ad)_", "--date=short"): "",
                ("rev-list", "--count", "@{u}..HEAD"): "3",
                ("rev-list", "--count", "HEAD..@{u}"): "1",
            }
        ),
    )

    assert "3 ahead, 1 behind origin" in cs.build_block()


# --- main(): exit codes and the record-suite cache path -------------------


def test_main_check_returns_1_when_context_md_is_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cs, "CONTEXT", tmp_path / "does-not-exist.md")
    monkeypatch.setattr(cs.sys, "argv", ["context_status.py", "--check"])

    assert cs.main() == 1


def test_main_check_returns_1_through_checks_own_message_when_markers_are_missing(
    tmp_path, monkeypatch, capsys
) -> None:
    context_path = tmp_path / "context.md"
    context_path.write_text("no generated block here at all", encoding="utf-8")
    monkeypatch.setattr(cs, "CONTEXT", context_path)
    monkeypatch.setattr(cs.sys, "argv", ["context_status.py", "--check"])

    # main() checks args.check before ever calling splice()/build_block(), so
    # a missing marker on --check now surfaces as check()'s own dedicated
    # "no generated block" message via a clean return 1, not an uncaught
    # SystemExit from splice() (fixed 2026-08-28; splice() previously ran
    # unconditionally before the args.check branch, making this message
    # unreachable through the CLI).
    assert cs.main() == 1
    assert "docs/context.md has no generated block" in capsys.readouterr().err


def test_main_write_still_raises_systemexit_when_markers_are_missing(tmp_path, monkeypatch) -> None:
    context_path = tmp_path / "context.md"
    context_path.write_text("no generated block here at all", encoding="utf-8")
    monkeypatch.setattr(cs, "CONTEXT", context_path)
    monkeypatch.setattr(cs.sys, "argv", ["context_status.py", "--write"])

    # --write has no use for a block it cannot splice into, so it still
    # surfaces splice()'s own SystemExit -- only --check was rerouted.
    with pytest.raises(SystemExit) as excinfo:
        cs.main()
    assert "no generated block" in str(excinfo.value)


def test_main_check_returns_0_for_a_block_built_from_the_real_head(tmp_path, monkeypatch) -> None:
    head = _git("rev-parse", "--short", "HEAD")
    context_path = tmp_path / "context.md"
    context_path.write_text(_wrap(f"**HEAD** `{head} subject` on `main`, in sync."), encoding="utf-8")
    monkeypatch.setattr(cs, "CONTEXT", context_path)
    monkeypatch.setattr(cs, "CACHE", tmp_path / ".context-status.json")
    monkeypatch.setattr(cs.sys, "argv", ["context_status.py", "--check"])

    assert cs.main() == 0


def test_main_write_splices_the_block_and_is_idempotent(tmp_path, monkeypatch, capsys) -> None:
    context_path = tmp_path / "context.md"
    context_path.write_text(_wrap("stale placeholder"), encoding="utf-8")
    monkeypatch.setattr(cs, "CONTEXT", context_path)
    monkeypatch.setattr(cs, "CACHE", tmp_path / ".context-status.json")
    monkeypatch.setattr(cs.sys, "argv", ["context_status.py", "--write"])

    code = cs.main()
    first_write_stderr = capsys.readouterr().err

    assert code == 0
    assert "refreshed docs/context.md status block" in first_write_stderr
    written = context_path.read_text(encoding="utf-8")
    assert cs.BEGIN in written and cs.END in written
    assert "stale placeholder" not in written

    # Running again immediately with no repo-state change produces byte-for-
    # byte the same block, so main() must not report a refresh the second
    # time.
    code_again = cs.main()
    second_write_stderr = capsys.readouterr().err

    assert code_again == 0
    assert "refreshed" not in second_write_stderr


def test_main_record_suite_writes_the_cache_and_returns_early(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / ".context-status.json"
    monkeypatch.setattr(cs, "CACHE", cache_path)
    # CONTEXT points somewhere that doesn't exist; if main() reached the
    # CONTEXT-existence check it would return 1, so a 0 here proves the
    # record-suite-only path returns before ever looking at CONTEXT.
    monkeypatch.setattr(cs, "CONTEXT", tmp_path / "unrelated" / "context.md")
    monkeypatch.setattr(
        cs.sys, "argv", ["context_status.py", "--record-suite", "42 passed", "--live", "2 passed"]
    )

    assert cs.main() == 0

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["offline"] == "42 passed"
    assert cache["live"] == "2 passed"
    assert "offline_date" in cache and "live_date" in cache


def test_main_default_mode_prints_the_block_and_returns_0(tmp_path, monkeypatch, capsys) -> None:
    context_path = tmp_path / "context.md"
    context_path.write_text(_wrap("placeholder"), encoding="utf-8")
    monkeypatch.setattr(cs, "CONTEXT", context_path)
    monkeypatch.setattr(cs, "CACHE", tmp_path / ".context-status.json")
    monkeypatch.setattr(cs.sys, "argv", ["context_status.py"])

    code = cs.main()
    out = capsys.readouterr().out

    assert code == 0
    assert cs.BEGIN in out
    # Printing the block must not touch the file on disk.
    assert context_path.read_text(encoding="utf-8") == _wrap("placeholder")
