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
import uuid
from collections.abc import Iterator

import psycopg
import pytest

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
