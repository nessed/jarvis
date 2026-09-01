"""A static regression signal for ``.githooks/pre-commit``.

``.githooks/pre-commit`` only fires once someone runs
``git config core.hooksPath .githooks`` in their clone -- a rule that
depends on being remembered doesn't hold. This file cannot test that
runtime enforcement: doing so would need a real git checkout with the hook
path configured, a commit attempted, and the commit's outcome observed,
which is out of reach for an offline unit test running inside an existing
worktree (and would mutate real repo state to prove it).

What this file actually guards, and nothing more:

1. The hook script exists and is the script CLAUDE.md describes -- it runs
   the specific offline-suite command documented in CLAUDE.md's Commands
   section, and it refuses (non-zero exit) when that suite is red.
2. It regenerates and stages the generated block in docs/context.md, per
   its own comment and per CLAUDE.md's rule that block is never
   hand-maintained.
3. A fresh clone is actually told to run
   ``git config core.hooksPath .githooks`` -- README.md and CLAUDE.md both
   carry that instruction, in the exact form the hook needs.

None of this proves the hook is wired up in any given clone, or that it
would actually catch a red suite at commit time. It proves the script and
the setup instructions cannot silently drift apart from what CLAUDE.md
claims without a test failing.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = REPO_ROOT / ".githooks" / "pre-commit"


def _hook_text() -> str:
    return HOOK_PATH.read_text(encoding="utf-8")


def test_the_hook_script_exists() -> None:
    assert HOOK_PATH.is_file()


def test_the_hook_is_a_posix_shell_script() -> None:
    first_line = _hook_text().splitlines()[0]

    assert first_line.startswith("#!"), "hook has no shebang; git won't know how to run it"
    assert "sh" in first_line


def _documented_suite_command() -> str:
    """The pytest invocation CLAUDE.md documents as required before any commit.

    Returned from ``-m pytest`` onward, so it is comparable against the hook
    regardless of how each spells the interpreter.

    Read out of CLAUDE.md rather than hardcoded. The previous version of this
    test pinned the flags as literals, so changing the documented command made
    it fail for the wrong reason -- it reported drift between the hook and a
    copy of the command frozen in a test file, not drift between the hook and
    CLAUDE.md.
    """
    for line in (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines():
        if "-m pytest" in line and "required before any commit" in line:
            command = line.split("#", 1)[0]
            return " ".join(command[command.index("-m pytest"):].split())
    raise AssertionError(
        "CLAUDE.md no longer documents a full-suite command marked "
        "'required before any commit'"
    )


def test_the_hook_runs_the_documented_offline_suite_command() -> None:
    hook = " ".join(_hook_text().split())
    documented = _documented_suite_command()

    # CLAUDE.md's Commands section names this exact invocation as "required
    # before any commit". If the hook's actual command drifts from it, the hook
    # is no longer proving what CLAUDE.md claims it proves. Compared whole, not
    # flag by flag: '-p no:cacheprovider' must keep its value, and a flag-set
    # check would pass on '-p something_else'.
    assert documented.startswith("-m pytest"), documented
    assert documented in hook, (
        f"CLAUDE.md documents {documented!r} as required before any commit, "
        f"but .githooks/pre-commit does not run that command"
    )

    # Not stylistic. The system TEMP directory is locked down on this machine,
    # so pytest's default cache and scratch dirs fail with PermissionError.
    assert "-p no:cacheprovider" in documented
    assert "--basetemp=.pytest-basetemp" in documented


def test_the_hook_does_not_skip_the_jobs_integration_file_by_path() -> None:
    """The full suite must not be narrowed with ``--ignore``.

    Until 1 Sep 2026 both the hook and CLAUDE.md passed
    ``--ignore=tests/db/test_jobs_integration.py`` to keep the two tests in
    that file that need live Supabase out of every routine run. ``--ignore`` is
    path-based, so it also took out the 23 offline guards in the same file --
    including the ones that keep the live-schema drift detector honest. Those
    guards had therefore never run.

    Both live tests now carry ``@pytest.mark.live``, and pytest.ini's addopts
    already deselect that marker, so the exclusion happens per-test instead of
    per-file. Re-adding ``--ignore`` would silently re-hide the guards.
    """
    assert "--ignore" not in _hook_text(), (
        "the hook narrows the suite by path; use a pytest marker instead so "
        "offline tests in the same file still run"
    )


def test_the_hook_refuses_a_red_suite() -> None:
    text = _hook_text()

    assert "STATUS -ne 0" in text
    assert "exit 1" in text
    # The escape hatch is documented, not silent.
    assert "--no-verify" in text


def test_the_hook_only_proceeds_past_the_red_check_toward_a_zero_exit() -> None:
    # A weaker version of this hook could check the suite and then exit 0
    # unconditionally regardless of STATUS. Pin that the success path is
    # reached by falling through from the red-suite branch, not by a second,
    # independent "exit 0" that would run even when STATUS is nonzero.
    text = _hook_text()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    exit_1_indexes = [i for i, ln in enumerate(lines) if ln == "exit 1"]
    assert exit_1_indexes, "no unconditional exit 1 found on the red-suite path"
    final_exit_index = len(lines) - 1 - lines[::-1].index("exit 0")

    assert final_exit_index > exit_1_indexes[-1], (
        "the hook's final exit 0 must come after the red-suite exit 1, "
        "so the red-suite branch actually stops the commit"
    )


def test_the_hook_regenerates_and_stages_the_context_status_block() -> None:
    text = _hook_text()

    # Per CLAUDE.md: "Its status block is generated, never hand-edited."
    assert "context_status.py" in text
    assert "--write" in text
    assert "git add docs/context.md" in text


def test_the_hook_records_the_suite_summary_it_just_ran() -> None:
    text = _hook_text()

    assert "--record-suite" in text


def test_readme_tells_a_fresh_clone_to_enable_the_hook_path() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "git config core.hooksPath .githooks" in readme


def test_claude_md_tells_a_fresh_clone_to_enable_the_hook_path() -> None:
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert "git config core.hooksPath .githooks" in claude_md
