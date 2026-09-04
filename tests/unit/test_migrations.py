"""Static checks over the SQL migrations.

These run without a database. They cannot prove the schema behaves correctly —
that needs the integration suite against a real Supabase project — but they do
catch the three mistakes that are cheapest to make and most expensive to ship:

1. SQL that does not parse (checked with PostgreSQL's own parser via pglast);
2. a table created without RLS enabled, which would silently expose user data
   (FINAL §26: "Supabase RLS on every user-owned table");
3. drift between the SQL enums and their Python mirror in app/common/enums.py,
   which is claimed to be the single source of truth.
"""

from __future__ import annotations

import re
from pathlib import Path

import pglast
import pytest

from app.common import enums as py_enums

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

# Tables intentionally exempt from RLS. Empty for now — every application table
# is user-owned or admin-managed. Add an entry only with a written reason.
RLS_EXEMPT: set[str] = set()


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def all_sql() -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in migration_files())


def all_sql_without_comments() -> str:
    """Strip `--` comments so assertions about the schema cannot match prose about it."""
    return re.sub(r"--[^\n]*", "", all_sql())


def test_migrations_directory_is_not_empty():
    assert migration_files(), "no migrations found — expected supabase/migrations/*.sql"


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.name)
def test_migration_parses(path: Path):
    """Uses libpg_query, the real PostgreSQL parser, not a regex approximation."""
    statements = pglast.parse_sql(path.read_text(encoding="utf-8"))
    assert statements, f"{path.name} parsed to zero statements"


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.name)
def test_migration_filename_is_a_supabase_version(path: Path):
    """Supabase orders migrations by a numeric timestamp prefix."""
    assert re.match(r"^\d{14}_[a-z0-9_]+\.sql$", path.name), (
        f"{path.name} must look like 20260905000100_name.sql"
    )


def test_every_created_table_enables_rls():
    """FINAL §26 / DATABASE_SCHEMA: RLS is the real boundary, so it is never optional."""
    sql = all_sql()

    created = set(re.findall(r"create table (?:if not exists )?public\.(\w+)", sql, re.I))
    rls_enabled = set(
        re.findall(r"alter table public\.(\w+)\s+enable row level security", sql, re.I)
    )

    missing = created - rls_enabled - RLS_EXEMPT
    assert not missing, f"tables created without RLS enabled: {sorted(missing)}"


def test_no_table_is_created_outside_the_public_schema():
    sql = all_sql()
    stray = re.findall(r"create table (?:if not exists )?(?!public\.)([a-z_]+)\s*\(", sql, re.I)
    assert not stray, f"tables must be schema-qualified as public.<name>: {stray}"


# --- SQL enum <-> Python enum parity ------------------------------------------


def _sql_enums() -> dict[str, list[str]]:
    sql = all_sql()
    found: dict[str, list[str]] = {}
    for name, body in re.findall(r"create type (\w+) as enum\s*\((.*?)\)\s*;", sql, re.I | re.S):
        found[name.lower()] = re.findall(r"'([^']+)'", body)
    return found


def _python_enum_for(sql_name: str):
    """care_rule_action_type -> CareRuleActionType"""
    pascal = "".join(part.capitalize() for part in sql_name.split("_"))
    return getattr(py_enums, pascal, None)


def test_sql_enums_were_found():
    found = _sql_enums()
    assert len(found) >= 20, f"expected the full enum set, parsed only {sorted(found)}"


@pytest.mark.parametrize("sql_name", sorted(_sql_enums()))
def test_sql_enum_has_a_python_mirror(sql_name: str):
    assert _python_enum_for(sql_name) is not None, (
        f"SQL enum '{sql_name}' has no counterpart in app/common/enums.py"
    )


@pytest.mark.parametrize("sql_name", sorted(_sql_enums()))
def test_sql_enum_values_match_python(sql_name: str):
    py_enum = _python_enum_for(sql_name)
    if py_enum is None:
        pytest.skip("covered by test_sql_enum_has_a_python_mirror")

    assert sorted(_sql_enums()[sql_name]) == sorted(m.value for m in py_enum), (
        f"'{sql_name}' has drifted from {py_enum.__name__}"
    )


# --- Foundation-specific invariants -------------------------------------------


def test_is_admin_is_security_definer():
    """Without SECURITY DEFINER an RLS policy on profiles that reads profiles.role recurses."""
    sql = all_sql()
    match = re.search(r"create or replace function public\.is_admin\(\).*?\$fn\$", sql, re.I | re.S)
    assert match, "is_admin() not found"
    assert "security definer" in match.group(0).lower()
    assert "set search_path" in match.group(0).lower(), (
        "a SECURITY DEFINER function must pin search_path"
    )


def test_every_security_definer_function_pins_search_path():
    """An unpinned search_path in a SECURITY DEFINER function is a privilege-escalation path."""
    sql = all_sql()
    offenders = []
    for match in re.finditer(
        r"create or replace function public\.(\w+)\(.*?\)(.*?)as \$fn\$", sql, re.I | re.S
    ):
        name, header = match.group(1), match.group(2).lower()
        if "security definer" in header and "set search_path" not in header:
            offenders.append(name)
    assert not offenders, f"SECURITY DEFINER without search_path: {offenders}"


def test_profiles_has_no_care_level_column():
    """FINAL §2 and §36 exclude care_level from MVP; DATABASE_SCHEMA says do not reintroduce it."""
    assert "care_level" not in all_sql_without_comments().lower()


def test_signup_trigger_creates_notification_preferences():
    """A27: a user must never exist without notification preferences."""
    sql = all_sql()
    match = re.search(
        r"create or replace function public\.handle_new_user\(\).*?\$fn\$(.*?)\$fn\$",
        sql,
        re.I | re.S,
    )
    assert match, "handle_new_user() not found"
    body = match.group(1).lower()
    assert "insert into public.profiles" in body
    assert "insert into public.notification_preferences" in body


def test_profiles_privileged_columns_are_guarded():
    """TESTING §7: a client-supplied role must not be able to grant admin access."""
    sql = all_sql()
    match = re.search(
        r"function public\.profiles_guard_privileged_columns\(\).*?\$fn\$(.*?)\$fn\$",
        sql,
        re.I | re.S,
    )
    assert match, "profiles_guard_privileged_columns() not found"
    body = match.group(1).lower()
    for column in ("role", "anonymized_at", "is_active"):
        assert f"new.{column} is distinct from old.{column}" in body, (
            f"{column} is not guarded against client modification"
        )


def test_profiles_have_no_delete_policy():
    """FINAL §21: accounts are anonymised, never physically deleted."""
    sql = all_sql()
    assert not re.search(r"create policy \w+\s+on public\.profiles for delete", sql, re.I), (
        "profiles must not expose a DELETE policy"
    )
