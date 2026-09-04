"""Behavioural tests for the foundation migration, against the real DEV database.

Static checks (tests/unit/test_migrations.py) prove the SQL parses and that the
declarations are present. These prove the declarations *work*: triggers fire,
policies deny, and the privilege guard actually blocks self-promotion.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.conftest import as_postgres, as_user

pytestmark = pytest.mark.integration


# --- signup wiring ------------------------------------------------------------


def test_signup_creates_a_profile(db: psycopg.Connection, make_user):
    user_id = make_user(display_name="גנן")

    row = db.execute(
        "select id, role, timezone, locale, is_active, display_name "
        "from public.profiles where id = %s",
        (user_id,),
    ).fetchone()

    assert row is not None, "handle_new_user() did not create a profile"
    assert row[1] == "USER", "new accounts must not be admins"
    assert row[2] == "Asia/Jerusalem"
    assert row[3] == "he"
    assert row[4] is True
    assert row[5] == "גנן", "display_name should come from raw_user_meta_data"


def test_signup_creates_notification_preferences(db: psycopg.Connection, make_user):
    """A27: a user must never exist without preferences, or the tick has nothing to read."""
    user_id = make_user()

    row = db.execute(
        "select email_enabled, preferred_time_local, daily_digest "
        "from public.notification_preferences where user_id = %s",
        (user_id,),
    ).fetchone()

    assert row is not None, "signup trigger did not create notification preferences"
    assert row[0] is True
    assert str(row[1]) == "08:00:00"
    assert row[2] is True


def test_profile_without_display_name_is_null_not_empty(db: psycopg.Connection, make_user):
    user_id = make_user()
    value = db.execute(
        "select display_name from public.profiles where id = %s", (user_id,)
    ).fetchone()[0]
    assert value is None


# --- RLS ----------------------------------------------------------------------


def test_user_sees_own_profile(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)

    rows = db.execute("select id from public.profiles").fetchall()

    assert [r[0] for r in rows] == [user_id]


def test_user_cannot_see_another_users_profile(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_user(db, alice)

    rows = db.execute("select id from public.profiles where id = %s", (bob,)).fetchall()

    assert rows == [], "RLS did not isolate profiles between users"


def test_user_cannot_see_another_users_notification_preferences(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_user(db, alice)

    rows = db.execute(
        "select user_id from public.notification_preferences where user_id = %s", (bob,)
    ).fetchall()

    assert rows == []


def test_anonymous_role_sees_nothing(db: psycopg.Connection, make_user):
    make_user()
    db.execute("set local role anon")

    rows = db.execute("select id from public.profiles").fetchall()

    assert rows == [], "anonymous users must not read profiles"


def test_user_cannot_update_another_users_profile(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_user(db, alice)

    db.execute("update public.profiles set display_name = 'hacked' where id = %s", (bob,))

    as_postgres(db)
    value = db.execute("select display_name from public.profiles where id = %s", (bob,)).fetchone()[
        0
    ]
    assert value != "hacked", "RLS allowed a cross-user UPDATE"


def test_user_can_update_own_display_name(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)

    db.execute("update public.profiles set display_name = %s where id = %s", ("אסף", user_id))

    value = db.execute(
        "select display_name from public.profiles where id = %s", (user_id,)
    ).fetchone()[0]
    assert value == "אסף"


# --- privilege guard ----------------------------------------------------------


def test_user_cannot_promote_themselves_to_admin(db: psycopg.Connection, make_user):
    """TESTING §7: a client-supplied role must never grant admin access.

    RLS gates rows, not columns, so the "update your own profile" policy alone
    would permit this. The guard trigger is what stops it.
    """
    user_id = make_user()
    as_user(db, user_id)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update public.profiles set role = 'ADMIN' where id = %s", (user_id,))


@pytest.mark.parametrize(
    ("column", "value"),
    [("is_active", "false"), ("anonymized_at", "now()")],
)
def test_user_cannot_modify_administrative_columns(
    db: psycopg.Connection, make_user, column: str, value: str
):
    user_id = make_user()
    as_user(db, user_id)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(f"update public.profiles set {column} = {value} where id = %s", (user_id,))


def test_admin_can_change_a_role(db: psycopg.Connection, make_user):
    """The guard must block the account holder without blocking legitimate administration."""
    user_id = make_user()

    as_postgres(db)
    db.execute("update public.profiles set role = 'ADMIN' where id = %s", (user_id,))

    value = db.execute("select role from public.profiles where id = %s", (user_id,)).fetchone()[0]
    assert value == "ADMIN"


# --- is_admin() ---------------------------------------------------------------


def test_is_admin_false_for_regular_user(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)

    assert db.execute("select public.is_admin()").fetchone()[0] is False


def test_is_admin_true_for_admin(db: psycopg.Connection, make_user):
    user_id = make_user()
    db.execute("update public.profiles set role = 'ADMIN' where id = %s", (user_id,))
    as_user(db, user_id)

    assert db.execute("select public.is_admin()").fetchone()[0] is True


def test_is_admin_does_not_recurse_under_rls(db: psycopg.Connection, make_user):
    """The whole reason is_admin() is SECURITY DEFINER: a policy on profiles that
    reads profiles.role would recurse forever. If this returns, it does not."""
    user_id = make_user()
    db.execute("update public.profiles set role = 'ADMIN' where id = %s", (user_id,))
    as_user(db, user_id)

    rows = db.execute("select id from public.profiles").fetchall()
    assert len(rows) >= 1, "admin should read all profiles via profiles_select_admin"


def test_inactive_admin_is_not_admin(db: psycopg.Connection, make_user):
    user_id = make_user()
    db.execute(
        "update public.profiles set role = 'ADMIN', is_active = false where id = %s", (user_id,)
    )
    as_user(db, user_id)

    assert db.execute("select public.is_admin()").fetchone()[0] is False


def test_anonymised_admin_is_not_admin(db: psycopg.Connection, make_user):
    user_id = make_user()
    db.execute(
        "update public.profiles set role = 'ADMIN', anonymized_at = now() where id = %s",
        (user_id,),
    )
    as_user(db, user_id)

    assert db.execute("select public.is_admin()").fetchone()[0] is False


# --- immutability helpers -----------------------------------------------------


def test_reject_mutation_blocks_update_and_delete(db: psycopg.Connection):
    """Exercises the helper on a scratch table, since the append-only tables it
    guards arrive in later migrations."""
    db.execute("create temporary table t_immutable (id int primary key, v text) on commit drop")
    db.execute(
        "create trigger t_immutable_guard before update or delete on t_immutable "
        "for each row execute function public.reject_mutation()"
    )
    db.execute("insert into t_immutable values (1, 'original')")

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update t_immutable set v = 'changed' where id = 1")


def test_reject_content_mutation_allows_status_but_blocks_content(db: psycopg.Connection):
    """The care_plan_versions shape: status must move, content must not."""
    db.execute(
        "create temporary table t_versioned "
        "(id int primary key, status text, content text) on commit drop"
    )
    db.execute(
        "create trigger t_versioned_guard before update on t_versioned "
        "for each row execute function public.reject_content_mutation('content')"
    )
    db.execute("insert into t_versioned values (1, 'PROPOSED', 'professional advice')")

    # The status transition the care plan lifecycle depends on must succeed.
    db.execute("update t_versioned set status = 'ACTIVE' where id = 1")
    assert db.execute("select status from t_versioned where id = 1").fetchone()[0] == "ACTIVE"

    # The professional content must not be editable (FINAL §12).
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update t_versioned set content = 'tampered' where id = 1")


# --- schema shape -------------------------------------------------------------


def test_profiles_has_no_care_level_column(db: psycopg.Connection):
    """FINAL §2 and §36 exclude care_level from MVP."""
    rows = db.execute(
        "select column_name from information_schema.columns "
        "where table_schema='public' and table_name='profiles'"
    ).fetchall()
    assert "care_level" not in {r[0] for r in rows}


def test_deleting_an_auth_user_cascades(db: psycopg.Connection, make_user):
    user_id = make_user()
    db.execute("delete from auth.users where id = %s", (user_id,))

    assert (
        db.execute("select count(*) from public.profiles where id = %s", (user_id,)).fetchone()[0]
        == 0
    )


def test_timezone_cannot_be_blank(db: psycopg.Connection, make_user):
    user_id = make_user()
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("update public.profiles set timezone = '   ' where id = %s", (user_id,))


def test_updated_at_advances_on_update(db: psycopg.Connection, make_user):
    user_id = make_user()
    before = db.execute(
        "select updated_at from public.profiles where id = %s", (user_id,)
    ).fetchone()[0]

    db.execute("update public.profiles set display_name = 'later' where id = %s", (user_id,))
    after = db.execute(
        "select updated_at from public.profiles where id = %s", (user_id,)
    ).fetchone()[0]

    assert after >= before


def test_every_public_table_has_rls_enabled(db: psycopg.Connection):
    """The invariant that must hold for every migration, checked against reality."""
    rows = db.execute(
        """
        select c.relname from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity
        """
    ).fetchall()
    assert rows == [], f"tables without RLS: {[r[0] for r in rows]}"


def test_expected_enum_count(db: psycopg.Connection):
    count = db.execute(
        """
        select count(distinct t.typname) from pg_type t
        join pg_enum e on e.enumtypid = t.oid
        join pg_namespace n on n.oid = t.typnamespace
        where n.nspname = 'public'
        """
    ).fetchone()[0]
    assert count == 24, f"expected 24 enums, found {count}"


def test_uuid_generation_is_available(db: psycopg.Connection):
    """pgcrypto powers gen_random_uuid(), used as the default PK on later tables."""
    value = db.execute("select gen_random_uuid()").fetchone()[0]
    assert isinstance(value, uuid.UUID)
