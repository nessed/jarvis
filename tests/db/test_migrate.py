from __future__ import annotations

from pathlib import Path

import pytest

from db import migrate
from db.migrate import (
    DATABASE_URL_ENV,
    DB_PASSWORD_ENV,
    LEDGER_TABLE,
    SUPABASE_URL_ENV,
    AppliedMigration,
    Migration,
    MigrationError,
    describe,
    discover,
    plan,
)


def _write(directory: Path, name: str, sql: str = "select 1;") -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self._connection = connection

    def execute(self, query, params=None):
        self._connection.executed.append((query.strip(), params))
        if self._connection.fail_on and self._connection.fail_on in query:
            raise RuntimeError("migration blew up")

    def fetchall(self):
        return self._connection.ledger_rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeConnection:
    def __init__(self, ledger_rows=(), fail_on: str | None = None) -> None:
        self.ledger_rows = list(ledger_rows)
        self.fail_on = fail_on
        self.executed: list[tuple[str, object]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


# --- discovery ----------------------------------------------------------------


def test_migrations_are_ordered_by_their_zero_padded_version(tmp_path: Path) -> None:
    _write(tmp_path, "0010_tenth.sql")
    _write(tmp_path, "0002_second.sql")
    _write(tmp_path, "0001_first.sql")

    assert [m.version for m in discover(tmp_path)] == ["0001", "0002", "0010"]


def test_a_misnamed_file_is_an_error_not_a_silent_skip(tmp_path: Path) -> None:
    """A migration nobody notices is a migration nobody applies — which is the
    exact failure that stranded four messages when 0002 sat unapplied."""
    _write(tmp_path, "0001_fine.sql")
    _write(tmp_path, "add_index.sql")

    with pytest.raises(MigrationError, match="add_index.sql"):
        discover(tmp_path)


def test_two_files_claiming_one_version_is_an_error(tmp_path: Path) -> None:
    _write(tmp_path, "0003_indexes.sql")
    _write(tmp_path, "0003_retention.sql")

    with pytest.raises(MigrationError, match="0003"):
        discover(tmp_path)


def test_the_checkout_migrations_are_all_well_named() -> None:
    versions = [m.version for m in discover()]

    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)


def test_the_checksum_follows_the_file_contents(tmp_path: Path) -> None:
    path = _write(tmp_path, "0001_first.sql", "select 1;")
    before = discover(tmp_path)[0].checksum
    path.write_text("select 2;", encoding="utf-8")

    assert discover(tmp_path)[0].checksum != before


# --- planning -----------------------------------------------------------------


def _migration(version: str, sql: str = "select 1;") -> Migration:
    return Migration(version=version, name="thing", path=Path(f"{version}_thing.sql"), sql=sql)


def test_an_unrecorded_migration_is_pending() -> None:
    result = plan([_migration("0001")], {})

    assert [m.version for m in result.pending] == ["0001"]
    assert result.already_applied == ()


def test_a_recorded_migration_is_skipped_so_a_rerun_is_a_no_op() -> None:
    migration = _migration("0001")
    applied = {"0001": AppliedMigration("0001", "thing", migration.checksum)}

    result = plan([migration], applied)

    assert result.pending == ()
    assert [m.version for m in result.already_applied] == ["0001"]
    assert result.is_empty


def test_a_migration_edited_after_it_was_applied_is_reported_and_not_re_run() -> None:
    """Re-running it would apply a diff nobody wrote; refusing outright would
    wedge the database over a reformatted comment. Report, and let the person
    who edited it decide."""
    migration = _migration("0001", "select 2;")
    applied = {"0001": AppliedMigration("0001", "thing", "a-different-checksum")}

    result = plan([migration], applied)

    assert result.pending == ()
    assert len(result.changed_since_applied) == 1
    assert "WARNING" in "\n".join(describe(result))


def test_the_plan_reads_as_english() -> None:
    result = plan([_migration("0001"), _migration("0002")], {"0001": AppliedMigration("0001", "thing", _migration("0001").checksum)})

    lines = describe(result)

    assert any(line.startswith("skip  0001") for line in lines)
    assert any(line.startswith("apply 0002") for line in lines)


def test_an_empty_plan_says_the_database_is_current() -> None:
    assert "nothing to apply" in "\n".join(describe(plan([], {})))


# --- applying -----------------------------------------------------------------


def test_the_ledger_table_is_created_before_it_is_read() -> None:
    connection = FakeConnection()

    migrate.applied_versions(connection)

    queries = [query for query, _ in connection.executed]
    assert queries[0].startswith("create table if not exists")
    assert LEDGER_TABLE in queries[0]


def test_a_migration_and_its_ledger_row_commit_together() -> None:
    connection = FakeConnection()

    migrate.apply_migration(connection, _migration("0003"))

    queries = [query for query, _ in connection.executed]
    assert queries[0] == "select 1;"
    assert queries[1].startswith(f"insert into {LEDGER_TABLE}")
    assert connection.commits == 1


def test_a_failing_migration_rolls_back_and_records_nothing() -> None:
    """A ledger row without its schema change is a lie the next reader trusts."""
    connection = FakeConnection(fail_on="select 1;")

    with pytest.raises(RuntimeError):
        migrate.apply_migration(connection, _migration("0003"))

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert not any(query.startswith("insert into") for query, _ in connection.executed)


def test_the_ledger_insert_is_upsertable_so_a_partial_state_can_recover() -> None:
    connection = FakeConnection()

    migrate.apply_migration(connection, _migration("0003"))

    insert = [query for query, _ in connection.executed if query.startswith("insert into")][0]
    assert "on conflict (version) do update" in insert


# --- the runner ---------------------------------------------------------------


def test_a_dry_run_applies_nothing_and_says_so(tmp_path: Path) -> None:
    _write(tmp_path, "0001_first.sql")
    connection = FakeConnection()
    lines: list[str] = []

    assert migrate.run(
        directory=tmp_path, dry_run=True, connection_factory=lambda: connection, emit=lines.append
    ) == 0

    assert "dry run: nothing was applied" in lines
    assert not any(query == "select 1;" for query, _ in connection.executed)
    assert connection.closed


def test_a_real_run_applies_every_pending_migration_in_order(tmp_path: Path) -> None:
    _write(tmp_path, "0001_first.sql", "select 'one';")
    _write(tmp_path, "0002_second.sql", "select 'two';")
    connection = FakeConnection()
    lines: list[str] = []

    migrate.run(directory=tmp_path, connection_factory=lambda: connection, emit=lines.append)

    applied = [line for line in lines if line.startswith("applied ")]
    assert applied == ["applied 0001_first", "applied 0002_second"]


def test_the_connection_is_closed_even_when_a_migration_fails(tmp_path: Path) -> None:
    _write(tmp_path, "0001_first.sql", "select 1;")
    connection = FakeConnection(fail_on="select 1;")

    with pytest.raises(RuntimeError):
        migrate.run(directory=tmp_path, connection_factory=lambda: connection, emit=lambda _: None)

    assert connection.closed


def test_running_twice_is_a_no_op_the_second_time(tmp_path: Path) -> None:
    """Idempotence is what makes this safe to run on every deploy."""
    _write(tmp_path, "0001_first.sql", "select 'one';")
    migration = discover(tmp_path)[0]
    second_run = FakeConnection(ledger_rows=[("0001", "first", migration.checksum)])
    lines: list[str] = []

    migrate.run(directory=tmp_path, connection_factory=lambda: second_run, emit=lines.append)

    assert not any(line.startswith("applied ") for line in lines)
    assert any("already applied" in line for line in lines)


# --- the connection URL -------------------------------------------------------


def test_an_explicit_database_url_wins() -> None:
    url = migrate.database_url({DATABASE_URL_ENV: "postgresql://somewhere/else"})

    assert url == "postgresql://somewhere/else"


def test_the_url_is_assembled_from_the_supabase_values_already_in_env() -> None:
    url = migrate.database_url(
        {SUPABASE_URL_ENV: "https://abcdefgh.supabase.co", DB_PASSWORD_ENV: "pw"}
    )

    assert url == "postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres"


def test_a_password_with_url_characters_is_escaped() -> None:
    """An unescaped @ or / silently points the driver at the wrong host."""
    url = migrate.database_url(
        {SUPABASE_URL_ENV: "https://abcdefgh.supabase.co", DB_PASSWORD_ENV: "p@ss/word#1"}
    )

    assert "p%40ss%2Fword%231" in url
    assert url.endswith("@db.abcdefgh.supabase.co:5432/postgres")


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {SUPABASE_URL_ENV: "https://abcdefgh.supabase.co"},
        {DB_PASSWORD_ENV: "pw"},
        {SUPABASE_URL_ENV: "   ", DB_PASSWORD_ENV: "pw"},
    ],
)
def test_missing_credentials_name_what_to_set(environ) -> None:
    with pytest.raises(MigrationError) as excinfo:
        migrate.database_url(environ)

    assert DATABASE_URL_ENV in str(excinfo.value)


def test_the_url_builder_never_leaks_the_password_into_an_error() -> None:
    with pytest.raises(MigrationError) as excinfo:
        migrate.database_url({SUPABASE_URL_ENV: "", DB_PASSWORD_ENV: "hunter2"})

    assert "hunter2" not in str(excinfo.value)
