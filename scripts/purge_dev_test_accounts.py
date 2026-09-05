"""Delete accounts left behind by the integration suite. DEV only.

Why this is a script and not a fixture
--------------------------------------
Test teardown cannot do this, and spent twenty-five PRs failing at it silently.

`profiles.id` references `auth.users` `ON DELETE CASCADE`, and every user-owned
table cascades from there. But `system_events`, `care_events` and the health
tables carry `reject_mutation()` triggers that refuse DELETE outright - `FINAL
§1.5` says those rows are immutable, and the trigger means it. So the cascade
promises a deletion the trigger forbids, and deleting any account that ever
created a plant fails with:

    Table system_events is append-only; DELETE is not permitted.

The two rules cannot both hold, and immutability is the one that should win: the
product never physically deletes an account anyway (`FINAL §21` anonymises
instead), so the cascade is unreachable in normal use. What it broke was the test
suite, whose teardown swallowed the error and left 1,375 accounts behind.

Removing them needs the immutability triggers disabled for the duration, which
needs table ownership. That is a deliberate administrative act on a development
database - so it lives in a script that names the project it will touch and
refuses to run anywhere else, rather than in a fixture that runs a thousand times
a day.

Foreign-key cascades stay enabled throughout. `session_replication_role =
replica` would have been shorter and wrong: it disables the constraint triggers
that implement `ON DELETE CASCADE`, so it would leave orphaned rows pointing at
users that no longer exist.

Usage
-----
    uv run python scripts/purge_dev_test_accounts.py           # report only
    uv run python scripts/purge_dev_test_accounts.py --delete  # actually delete
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import psycopg

# The DEV project, named so this cannot be pointed at production by editing an
# environment variable. A purge script that trusts its configuration is one
# mistyped `.env` away from being the worst tool in the repository.
DEV_REF = "ckwvjyxeennrknwjsujl"
POOLER_HOST = "aws-0-eu-central-1.pooler.supabase.com"

# Every address the suites generate. `@plantcare.local` is deliberately excluded:
# those accounts were made by hand for browser review and someone signs in with
# them.
TEST_EMAIL_PATTERNS = ("%@example.com", "%@example.test")

IMMUTABLE_TRIGGERS = [
    ("system_events", "system_events_immutable"),
    ("care_events", "care_events_immutable"),
    ("health_assessments", "health_assessments_immutable"),
    ("health_observations", "health_observations_immutable"),
    ("health_issues", "health_issues_immutable"),
    ("health_recommendations", "health_recommendations_immutable"),
    ("health_assessment_sources", "health_assessment_sources_immutable"),
    ("admin_audit_log", "admin_audit_log_immutable"),
]


def dsn() -> str:
    """The DEV connection string, with two independent safety checks.

    The password is read from `.env` rather than the environment because the
    application never opens a direct database connection - it goes through
    PostgREST - so there is no `Settings` field for it, and `STRUCTURE §6` bans
    reading `os.environ` anywhere but `settings.py`. The configured project URL
    is read through `Settings`, which is the point of that rule: the check that
    this is DEV uses the same value the application would.
    """
    from app.config.settings import get_settings

    if DEV_REF not in get_settings().supabase_url:
        sys.exit(f"configured Supabase project is not {DEV_REF}. Refusing to run.")

    env_path = pathlib.Path(__file__).resolve().parents[1] / ".env"
    password = ""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("SUPABASE_DB_PASSWORD="):
                password = line.split("=", 1)[1].strip()
                break
    if not password:
        sys.exit("SUPABASE_DB_PASSWORD is not in .env; nothing to connect with.")

    return f"postgresql://postgres.{DEV_REF}:{password}@{POOLER_HOST}:5432/postgres"


def _where() -> str:
    return " or ".join(f"email like '{pattern}'" for pattern in TEST_EMAIL_PATTERNS)


def report(conn: psycopg.Connection) -> int:
    total = conn.execute(f"select count(*) from auth.users where {_where()}").fetchone()
    assert total is not None
    print(f"test accounts:          {total[0]}")

    for table in ("plants", "care_tasks", "care_events", "system_events", "health_assessments"):
        row = conn.execute(
            f"""
            select count(*) from public.{table}
             where user_id in (select id from auth.users where {_where()})
            """
        ).fetchone()
        assert row is not None
        print(f"  {table:<20} {row[0]}")
    return int(total[0])


def purge(conn: psycopg.Connection) -> int:
    """Delete in one transaction, with the immutability triggers off.

    One transaction so a failure halfway leaves nothing half-deleted, and so the
    triggers are re-enabled by the rollback if anything raises. They are also
    re-enabled explicitly, because relying on a rollback to restore a safety
    mechanism is not a safety mechanism.
    """
    with conn.transaction():
        for table, trigger in IMMUTABLE_TRIGGERS:
            conn.execute(f"alter table public.{table} disable trigger {trigger}")
        try:
            result = conn.execute(f"delete from auth.users where {_where()}")
            deleted = result.rowcount
        finally:
            for table, trigger in IMMUTABLE_TRIGGERS:
                conn.execute(f"alter table public.{table} enable trigger {trigger}")
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="actually delete; default reports")
    args = parser.parse_args()

    conn = psycopg.connect(dsn(), connect_timeout=30, autocommit=True)
    try:
        found = report(conn)
        if not args.delete:
            print("\nreport only - pass --delete to remove them")
            return
        if not found:
            print("\nnothing to delete")
            return

        deleted = purge(conn)
        print(f"\ndeleted {deleted} accounts and everything that cascaded from them")

        left = conn.execute("select count(*) from public.profiles").fetchone()
        assert left is not None
        print(f"profiles remaining:     {left[0]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
