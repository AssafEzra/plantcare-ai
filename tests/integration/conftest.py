"""Integration-test plumbing: a direct Postgres connection to the DEV project.

These tests talk to a real Supabase database, so they are marked `integration`
and excluded from the default CI run. They exist to prove the things static
analysis cannot: that triggers fire, that RLS policies actually deny, and that
the immutability guarantees hold under a real UPDATE.

The application itself never connects this way — it goes through PostgREST with
the caller's JWT (see the plan, decision 1). This direct connection is a test
harness only, and it deliberately drops from the `postgres` superuser to the
`authenticated` role before exercising any policy, because a superuser bypasses
RLS entirely and would make every policy test vacuously pass.
"""

from __future__ import annotations

import os
import random
import string
import uuid
from collections.abc import Iterator

import psycopg
import pytest

# The trigger lists live with the purge script. See the teardown section below for
# why they are shared rather than copied.
from scripts.purge_dev_test_accounts import CONSTRAINT_TRIGGERS, IMMUTABLE_TRIGGERS

SUPABASE_REF = "ckwvjyxeennrknwjsujl"
POOLER_HOST = "aws-0-eu-central-1.pooler.supabase.com"


def _dsn() -> str | None:
    """Build the DEV connection string from .env, without importing app settings."""
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if not password:
        env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("SUPABASE_DB_PASSWORD="):
                        password = line.split("=", 1)[1].strip()
                        break
    if not password:
        return None
    return f"postgresql://postgres.{SUPABASE_REF}:{password}@{POOLER_HOST}:5432/postgres"


@pytest.fixture(scope="session")
def dsn() -> str:
    value = _dsn()
    if not value:
        pytest.skip("SUPABASE_DB_PASSWORD not available; skipping integration tests")
    return value


@pytest.fixture
def db(dsn: str) -> Iterator[psycopg.Connection]:
    """A connection whose work is rolled back, so tests never leave residue."""
    conn = psycopg.connect(dsn, connect_timeout=20, autocommit=False)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def make_user(db: psycopg.Connection):
    """Create an auth.users row, which is what the signup trigger reacts to."""

    def _make(email: str | None = None, display_name: str | None = None) -> uuid.UUID:
        user_id = uuid.uuid4()
        db.execute(
            """
            insert into auth.users (
                instance_id, id, aud, role, email,
                encrypted_password, email_confirmed_at,
                raw_app_meta_data, raw_user_meta_data,
                created_at, updated_at
            ) values (
                '00000000-0000-0000-0000-000000000000', %s, 'authenticated', 'authenticated', %s,
                'x', now(),
                '{"provider":"email","providers":["email"]}'::jsonb, %s::jsonb,
                now(), now()
            )
            """,
            (
                user_id,
                email or f"{user_id}@example.test",
                f'{{"display_name": "{display_name}"}}' if display_name else "{}",
            ),
        )
        return user_id

    return _make


def as_user(conn: psycopg.Connection, user_id: uuid.UUID) -> None:
    """Drop to the `authenticated` role with a JWT claim, so RLS applies.

    Without this the connection runs as `postgres`, which bypasses RLS and would
    make every policy assertion below pass regardless of the policy.
    """
    conn.execute("set local role authenticated")
    conn.execute(
        "select set_config('request.jwt.claims', %s, true)",
        (f'{{"sub":"{user_id}","role":"authenticated"}}',),
    )


def as_postgres(conn: psycopg.Connection) -> None:
    conn.execute("reset role")


# --- unique fixture data ------------------------------------------------------
#
# These tests run against a shared DEV database that also holds seed data, so a
# test must never assume a name is unused or that a table contains only its own
# rows. Both assumptions held until the seed fixtures landed, and then nine tests
# failed at once. Generate names; scope assertions.


def unique_species_name() -> str:
    """A unique binomial made only of letters.

    Letters only, deliberately: normalize_scientific_name() strips digits, so a
    hex-based epithet like "a1b2c3" collapses to "a" and collides with every other
    such name. Real botanical names contain no digits, so the function is correct
    and the generator has to match it.
    """
    epithet = "".join(random.choices(string.ascii_lowercase, k=14))
    return f"Testus {epithet}"


def unique_domain() -> str:
    return f"test-{uuid.uuid4().hex[:12]}.example.org"


def unique_epithet(name: str) -> str:
    """The lowercase epithet of a name from unique_species_name()."""
    return name.split()[1].lower()


# --- account teardown ---------------------------------------------------------
#
# Test accounts cannot be deleted, and every suite spent twenty-five PRs
# pretending otherwise.
#
# `profiles.id` cascades from `auth.users`, and every user-owned table cascades
# from there - but `system_events`, `care_events` and the health tables carry
# `reject_mutation()` triggers that refuse DELETE, because FINAL §1.5 says those
# rows are immutable. So deleting any account that ever created a plant fails
# with "Table system_events is append-only". The cascade promises what the
# trigger forbids.
#
# Immutability is the rule that should win: FINAL §21 anonymises accounts rather
# than deleting them, so the product never walks this path. What it broke was
# teardown, which wrapped the failure in `contextlib.suppress(Exception)` and
# left 1,375 accounts behind - roughly a quarter of them administrators. Reporting
# the failure instead of swallowing it made the problem visible, and then the count
# climbed again: 282 accounts in three days, because every run still stranded its
# whole set.
#
# So teardown stopped asking the Auth API, which cannot do this, and does what
# `scripts/purge_dev_test_accounts.py` already proved works: disable the
# immutability triggers for the length of one transaction, delete, switch them back
# on. The trigger list is imported from that script rather than copied, because a
# teardown that knew about one trigger fewer would fail on exactly the trigger the
# other list knew about.
#
# This is a superuser connection doing something the application may never do, and
# that is the point: the rule protects the product, not the test harness. It runs
# against DEV only - `_dsn()` is hard-coded to the DEV project ref above.

_undeleted: list[str] = []

#: Why each failed batch failed, in the order it happened. The summary used to state
#: the cause from memory - "system_events is append-only" - which was true of the
#: teardown that asked the Auth API and is false of this one, which disables exactly
#: that trigger. So a leftover account was explained by a cause that could not have
#: produced it. Whatever refuses next is by definition something nobody predicted,
#: and the only way to learn it is to keep the message.
_reasons: list[str] = []

#: One connection for the whole session. Teardown runs once per test module, and
#: opening a pooled Postgres connection each time is slower than the delete.
_purge_conn: psycopg.Connection | None = None


def _purge_connection() -> psycopg.Connection | None:
    global _purge_conn

    if _purge_conn is None or _purge_conn.closed:
        value = _dsn()
        if not value:
            return None
        _purge_conn = psycopg.connect(value, connect_timeout=20, autocommit=True)
    return _purge_conn


def delete_accounts(admin_sdk, user_ids: list[str]) -> None:
    """Remove these accounts, immutable history and all.

    `admin_sdk` is accepted and ignored. Every caller has one to hand and the
    signature is what fifteen test modules already pass; the Auth admin API is
    simply not the thing that can do this.
    """
    ids = [str(user_id) for user_id in user_ids]
    if not ids:
        return

    conn = _purge_connection()
    if conn is None:
        _record(ids, "no database connection: SUPABASE_DB_PASSWORD is not available")
        return

    try:
        with conn.transaction():
            for table, trigger in IMMUTABLE_TRIGGERS + CONSTRAINT_TRIGGERS:
                conn.execute(f"alter table public.{table} disable trigger {trigger}")

            # The one foreign key the cascade cannot order around on its own;
            # `scripts/purge_dev_test_accounts.py` explains how it was found.
            conn.execute(
                """
                delete from public.health_assessment_images
                 where health_assessment_id in (
                   select id from public.health_assessments where user_id = any(%s)
                 )
                """,
                (ids,),
            )

            conn.execute("delete from auth.users where id = any(%s)", (ids,))

            # No `finally` around the delete, deliberately. Postgres aborts the
            # whole transaction on the first error, so re-enabling here would raise
            # `InFailedSqlTransaction` and that exception would replace the real
            # one. `ALTER TABLE ... DISABLE TRIGGER` is transactional, so a
            # rollback restores them anyway.
            for table, trigger in IMMUTABLE_TRIGGERS + CONSTRAINT_TRIGGERS:
                conn.execute(f"alter table public.{table} enable trigger {trigger}")
    except Exception as error:
        # Still reported rather than swallowed - that silence is what let this
        # reach 1,375 accounts the first time. The message travels with the count,
        # because a number on its own sent the last investigation to the wrong
        # trigger.
        _record(ids, f"{type(error).__name__}: {error}")


def _record(ids: list[str], reason: str) -> None:
    """Remember the accounts and the one-line reason they survived."""
    _undeleted.extend(ids)
    # First line only, and bounded: a psycopg error carries a DETAIL/HINT block that
    # would push the test summary off the screen, which is where this has to be read.
    _reasons.append(reason.strip().splitlines()[0][:200])


def undeleted_accounts() -> list[str]:
    return list(_undeleted)


def undeleted_reasons() -> list[str]:
    """The distinct reasons, most recent batch last, each kept once."""
    return list(dict.fromkeys(_reasons))
