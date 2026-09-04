"""Storage access control, against the real DEV bucket.

FINAL §20 and §26 require owner-only access to plant images, with admins able to
reach retained AI-used images that are hidden from their owner. The object key
layout is {user_id}/{plant_id}/{context}/{filename}, so every policy keys on the
first path segment.

These tests insert rows into storage.objects directly. That exercises the RLS
policies, which is the security boundary — the HTTP storage API sits on top of
exactly these policies.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.conftest import as_postgres, as_user

pytestmark = pytest.mark.integration

BUCKET = "plant-images"


def _key(user_id: uuid.UUID, context: str = "gallery", filename: str = "a.jpg") -> str:
    return f"{user_id}/{uuid.uuid4()}/{context}/{filename}"


def _insert_object(conn: psycopg.Connection, user_id: uuid.UUID, key: str) -> None:
    conn.execute(
        "insert into storage.objects (bucket_id, name, owner_id) values (%s, %s, %s)",
        (BUCKET, key, str(user_id)),
    )


# --- bucket configuration -----------------------------------------------------


def test_bucket_is_private(db: psycopg.Connection):
    """A public bucket would make every plant photo world-readable by URL."""
    public = db.execute("select public from storage.buckets where id = %s", (BUCKET,)).fetchone()[0]
    assert public is False


def test_bucket_enforces_the_ten_megabyte_limit(db: psycopg.Connection):
    limit = db.execute(
        "select file_size_limit from storage.buckets where id = %s", (BUCKET,)
    ).fetchone()[0]
    assert limit == 10 * 1024 * 1024


def test_bucket_allows_only_the_supported_image_types(db: psycopg.Connection):
    """FINAL §20: JPG/JPEG/PNG/WEBP only."""
    types = db.execute(
        "select allowed_mime_types from storage.buckets where id = %s", (BUCKET,)
    ).fetchone()[0]
    assert set(types) == {"image/jpeg", "image/png", "image/webp"}


def test_storage_objects_has_rls_enabled(db: psycopg.Connection):
    enabled = db.execute(
        """
        select c.relrowsecurity from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'storage' and c.relname = 'objects'
        """
    ).fetchone()[0]
    assert enabled is True


# --- owner access -------------------------------------------------------------


def test_user_can_write_into_their_own_namespace(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)

    _insert_object(db, user_id, _key(user_id))

    rows = db.execute(
        "select count(*) from storage.objects where bucket_id = %s", (BUCKET,)
    ).fetchone()[0]
    assert rows == 1


def test_user_cannot_write_into_another_users_namespace(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_user(db, alice)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _insert_object(db, alice, _key(bob))


def test_user_cannot_read_another_users_objects(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()

    as_postgres(db)
    _insert_object(db, bob, _key(bob))

    as_user(db, alice)
    rows = db.execute("select name from storage.objects where bucket_id = %s", (BUCKET,)).fetchall()
    assert rows == [], "a user could read another user's plant images"


def test_user_reads_only_their_own_objects(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    alice_key = _key(alice)

    as_postgres(db)
    _insert_object(db, alice, alice_key)
    _insert_object(db, bob, _key(bob))

    as_user(db, alice)
    rows = db.execute("select name from storage.objects where bucket_id = %s", (BUCKET,)).fetchall()
    assert [r[0] for r in rows] == [alice_key]


def test_direct_sql_deletion_is_blocked_entirely(db: psycopg.Connection, make_user):
    """Supabase installs storage.protect_delete(), which refuses every direct SQL
    delete from storage.objects regardless of RLS, so that rows can never be
    orphaned from the underlying blobs.

    That means cross-user deletion cannot be exercised at the SQL layer at all —
    the plant_images_delete_own policy is only reachable through the Storage API,
    and is covered by the API-level tests in Phase 6. This test pins the guard
    itself, so that if a future Supabase change removes it we find out here rather
    than through orphaned objects.
    """
    owner = make_user()
    key = _key(owner)

    as_postgres(db)
    _insert_object(db, owner, key)

    as_user(db, owner)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="Direct deletion"):
        db.execute("delete from storage.objects where name = %s", (key,))


def test_delete_policy_exists_and_is_owner_scoped(db: psycopg.Connection):
    """Since the behaviour cannot be exercised in SQL (see above), assert the
    policy's definition instead."""
    row = db.execute(
        """
        select qual from pg_policies
        where schemaname = 'storage' and tablename = 'objects'
          and policyname = 'plant_images_delete_own'
        """
    ).fetchone()

    assert row is not None, "the owner-scoped delete policy is missing"
    qual = row[0].lower()
    assert "plant-images" in qual
    assert "auth.uid()" in qual


def test_anonymous_role_sees_no_objects(db: psycopg.Connection, make_user):
    owner = make_user()
    as_postgres(db)
    _insert_object(db, owner, _key(owner))

    db.execute("set local role anon")
    rows = db.execute("select name from storage.objects where bucket_id = %s", (BUCKET,)).fetchall()
    assert rows == []


# --- admin access -------------------------------------------------------------


def test_admin_can_read_retained_images_of_any_user(db: psycopg.Connection, make_user):
    """FINAL §20: AI-used images are hidden from the user but retained for audit,
    with admin access. That is only possible if admins can read across owners."""
    owner = make_user()
    admin = make_user()
    owner_key = _key(owner, context="identification")

    as_postgres(db)
    _insert_object(db, owner, owner_key)
    db.execute("update public.profiles set role = 'ADMIN' where id = %s", (admin,))

    as_user(db, admin)
    rows = db.execute("select name from storage.objects where bucket_id = %s", (BUCKET,)).fetchall()
    assert owner_key in [r[0] for r in rows]


def test_admin_cannot_write_into_a_users_namespace(db: psycopg.Connection, make_user):
    """Admin access to images is deliberately read-only: there is no reason for an
    administrator to author objects inside someone's plant gallery."""
    owner = make_user()
    admin = make_user()

    as_postgres(db)
    db.execute("update public.profiles set role = 'ADMIN' where id = %s", (admin,))

    as_user(db, admin)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _insert_object(db, admin, _key(owner))
