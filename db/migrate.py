"""Apply `db/migrations/*.sql` in order, once each, and record what was applied.

Why this exists
---------------

`0002_job_retries.sql` was written, reviewed and committed — and then sat
unapplied against the live database for days, because applying a migration
meant remembering to paste it into the Supabase SQL editor by hand. Four
inbound WhatsApp messages were stranded in the queue in that window: the code
expected `attempts`/`max_attempts`/`timeout_seconds` columns the database did
not have. Nothing in the repo could tell you which migrations were live,
because nothing recorded it.

So the ledger is the point, not the runner. `schema_migrations` answers "is
this database at the version this checkout expects" without a human
remembering anything.

Approved by Ali on 1 September 2026 (`QUESTIONS.md` Q9) to write live schema,
with the driver named as a component decision: **`psycopg[binary]` v3**, not
a substitute.

How it decides what to run
--------------------------

Filename order, which is why they are zero-padded. A migration whose version
is already in `schema_migrations` is skipped, so a second run is a no-op —
that idempotence is what makes it safe to run on every deploy rather than
only when someone thinks it is needed. Each migration runs inside its own
transaction: a failure rolls that file back and stops, leaving the ledger
truthful about what is actually applied.

The SQL itself is still expected to be written idempotently (`if not exists`,
`create or replace`), because the ledger can be lost or a database restored
from elsewhere, and a migration that only works once is a migration that
cannot be re-run when that happens.

``--dry-run`` connects, reads the ledger, and prints the plan without opening
a write transaction. Run it first, every time.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

MIGRATIONS_DIR = Path(__file__).with_name("migrations")

#: `0002_job_retries.sql` -> version `0002`, name `job_retries`.
MIGRATION_PATTERN = re.compile(r"^(?P<version>\d+)_(?P<name>.+)\.sql$")

LEDGER_TABLE = "public.schema_migrations"

CREATE_LEDGER = f"""
create table if not exists {LEDGER_TABLE} (
    version text primary key,
    name text not null,
    checksum text not null,
    applied_at timestamptz not null default now()
)
"""

#: The direct-connection URL Supabase gives a project, assembled from the
#: values already in `.env` rather than adding a new secret to fill in.
#: Overridable because a pooler URL has a different shape and a project on a
#: custom domain has a different host.
DATABASE_URL_ENV = "SUPABASE_DB_URL"
SUPABASE_URL_ENV = "SUPABASE_URL"
DB_PASSWORD_ENV = "SUPABASE_DB_PASSWORD"


class MigrationError(RuntimeError):
    """Raised when a migration cannot be planned or applied."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover(directory: Path | None = None) -> list[Migration]:
    """Every migration on disk, in filename order.

    A file that does not match ``NNNN_name.sql`` is an error rather than a
    silent skip: a migration nobody notices is not applied, is the exact
    failure this module exists to prevent, and a typo in a filename is the
    cheapest way to cause it.
    """
    source = directory or MIGRATIONS_DIR
    migrations: list[Migration] = []
    for path in sorted(source.glob("*.sql")):
        match = MIGRATION_PATTERN.match(path.name)
        if match is None:
            raise MigrationError(
                f"{path.name} is not a migration filename (expected NNNN_name.sql)"
            )
        migrations.append(
            Migration(
                version=match["version"],
                name=match["name"],
                path=path,
                sql=path.read_text(encoding="utf-8"),
            )
        )
    versions = [migration.version for migration in migrations]
    duplicates = {version for version in versions if versions.count(version) > 1}
    if duplicates:
        raise MigrationError(f"duplicate migration version(s): {', '.join(sorted(duplicates))}")
    return migrations


class Cursor(Protocol):
    def execute(self, query: str, params: Sequence[Any] | None = ...) -> Any: ...
    def fetchall(self) -> Sequence[Sequence[Any]]: ...


class Connection(Protocol):
    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class AppliedMigration:
    version: str
    name: str
    checksum: str


def applied_versions(connection: Connection) -> dict[str, AppliedMigration]:
    """Read the ledger, creating it first if this is a fresh database."""
    with connection.cursor() as cursor:
        cursor.execute(CREATE_LEDGER)
        cursor.execute(f"select version, name, checksum from {LEDGER_TABLE}")
        rows = cursor.fetchall()
    connection.commit()
    return {
        str(row[0]): AppliedMigration(str(row[0]), str(row[1]), str(row[2])) for row in rows
    }


@dataclass(frozen=True)
class Plan:
    pending: tuple[Migration, ...]
    already_applied: tuple[Migration, ...]
    changed_since_applied: tuple[tuple[Migration, AppliedMigration], ...]

    @property
    def is_empty(self) -> bool:
        return not self.pending


def plan(migrations: Iterable[Migration], applied: Mapping[str, AppliedMigration]) -> Plan:
    """Split migrations into pending, done, and done-but-since-edited.

    The third bucket is a warning, never an action. Re-running an edited
    migration would apply a diff nobody wrote; refusing outright would wedge
    a database over a reformatted comment. Reporting it puts the judgement
    where it belongs — with whoever edited the file.
    """
    pending: list[Migration] = []
    done: list[Migration] = []
    changed: list[tuple[Migration, AppliedMigration]] = []
    for migration in migrations:
        record = applied.get(migration.version)
        if record is None:
            pending.append(migration)
            continue
        done.append(migration)
        if record.checksum != migration.checksum:
            changed.append((migration, record))
    return Plan(tuple(pending), tuple(done), tuple(changed))


def apply_migration(connection: Connection, migration: Migration) -> None:
    """Run one migration and record it, in a single transaction.

    Both halves commit together on purpose. A migration that applied but was
    not recorded would be re-applied on the next run; a record without the
    schema change would be a lie the next reader trusts. Either is worse than
    failing.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(migration.sql)
            cursor.execute(
                f"insert into {LEDGER_TABLE} (version, name, checksum) values (%s, %s, %s) "
                "on conflict (version) do update set name = excluded.name, "
                "checksum = excluded.checksum, applied_at = now()",
                (migration.version, migration.name, migration.checksum),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def database_url(environ: Mapping[str, str] | None = None) -> str:
    """The Postgres connection URL, from an explicit override or Supabase's parts.

    Never logged, never printed, never returned to anything that formats it
    into an error — callers pass it straight to ``connect``. The password is
    read from ``.env`` like every other secret in this repo.
    """
    settings = os.environ if environ is None else environ
    explicit = (settings.get(DATABASE_URL_ENV) or "").strip()
    if explicit:
        return explicit

    project_url = (settings.get(SUPABASE_URL_ENV) or "").strip()
    password = settings.get(DB_PASSWORD_ENV) or ""
    if not project_url or not password:
        raise MigrationError(
            f"set {DATABASE_URL_ENV}, or both {SUPABASE_URL_ENV} and {DB_PASSWORD_ENV}"
        )
    host = project_url.split("://", 1)[-1].split("/", 1)[0]
    reference = host.split(".", 1)[0]
    if not reference:
        raise MigrationError(f"could not read a project reference out of {SUPABASE_URL_ENV}")
    from urllib.parse import quote

    return f"postgresql://postgres:{quote(password, safe='')}@db.{reference}.supabase.co:5432/postgres"


def connect(url: str | None = None) -> Connection:
    """Open a psycopg v3 connection. The driver is a decision, not a default."""
    import psycopg

    return psycopg.connect(url or database_url(), autocommit=False)


def describe(plan_result: Plan) -> list[str]:
    """The plan as lines, for a dry run or a log. Contains no connection detail."""
    lines: list[str] = []
    for migration, record in plan_result.changed_since_applied:
        lines.append(
            f"WARNING {migration.version}_{migration.name}: applied, but the file has changed "
            f"since (recorded {record.checksum[:12]}, on disk {migration.checksum[:12]}). "
            "Not re-run."
        )
    for migration in plan_result.already_applied:
        lines.append(f"skip  {migration.version}_{migration.name} (already applied)")
    for migration in plan_result.pending:
        lines.append(f"apply {migration.version}_{migration.name}")
    if plan_result.is_empty:
        lines.append("nothing to apply; the database is at the checkout's version")
    return lines


def run(
    *,
    directory: Path | None = None,
    dry_run: bool = False,
    connection_factory: Callable[[], Connection] = connect,
    emit: Callable[[str], None] = print,
) -> int:
    """Plan, report, and (unless ``dry_run``) apply. Returns a process exit code."""
    migrations = discover(directory)
    connection = connection_factory()
    try:
        applied = applied_versions(connection)
        plan_result = plan(migrations, applied)
        for line in describe(plan_result):
            emit(line)
        if dry_run:
            emit("dry run: nothing was applied")
            return 0
        for migration in plan_result.pending:
            apply_migration(connection, migration)
            emit(f"applied {migration.version}_{migration.name}")
    finally:
        connection.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply pending database migrations")
    parser.add_argument(
        "--dry-run", action="store_true", help="show the plan without applying anything"
    )
    parser.add_argument(
        "--directory", type=Path, default=None, help="migrations directory (default: db/migrations)"
    )
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    try:
        return run(directory=args.directory, dry_run=args.dry_run)
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
