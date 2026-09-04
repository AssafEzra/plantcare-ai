"""Behavioural tests for the plants and identification schema.

Two constraints here are worth singling out, because they turn spec rules into
database guarantees rather than conventions in application code:

* `identifications_failure_carries_no_verdict` makes FINAL §25 ("AI failure never
  creates an authoritative record") impossible to violate, even by a bug in the
  orchestration layer.
* `plants_archived_at_matches_status` keeps the archive flag and its timestamp
  from disagreeing, so a plant can never be archived by one and active by the other.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.conftest import as_postgres, as_user

pytestmark = pytest.mark.integration


def _make_plant(conn: psycopg.Connection, user_id: uuid.UUID, **kw) -> uuid.UUID:
    row = conn.execute(
        "insert into public.plants (user_id, name, status) values (%s, %s, %s) returning id",
        (user_id, kw.get("name"), kw.get("status", "PENDING_IDENTIFICATION")),
    ).fetchone()
    return row[0]


def _make_identification(
    conn: psycopg.Connection, user_id: uuid.UUID, plant_id: uuid.UUID, **kw
) -> uuid.UUID:
    row = conn.execute(
        """
        insert into public.identifications (user_id, plant_id, status, confidence_score)
        values (%s, %s, %s, %s) returning id
        """,
        (user_id, plant_id, kw.get("status", "SUCCESS"), kw.get("confidence_score")),
    ).fetchone()
    return row[0]


# --- scientific name normalisation (A23) --------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Monstera deliciosa", "monstera deliciosa"),
        ("monstera deliciosa", "monstera deliciosa"),
        ("  Monstera   deliciosa  ", "monstera deliciosa"),
        ("Monstera deliciosa Liebm.", "monstera deliciosa"),
        ("Monstera deliciosa (L.) Schott", "monstera deliciosa"),
        ("MONSTERA DELICIOSA", "monstera deliciosa"),
        # Infraspecific ranks distinguish real taxa and must survive.
        ("Monstera deliciosa var. borsigiana", "monstera deliciosa var. borsigiana"),
        ("Ficus elastica subsp. decora", "ficus elastica subsp. decora"),
    ],
)
def test_normalisation_collapses_spelling_variants(db: psycopg.Connection, raw: str, expected: str):
    value = db.execute("select public.normalize_scientific_name(%s)", (raw,)).fetchone()[0]
    assert value == expected


def test_normalisation_keeps_distinct_species_distinct(db: psycopg.Connection):
    """The failure mode that matters is over-merging, not under-merging."""
    a = db.execute("select public.normalize_scientific_name('Monstera deliciosa')").fetchone()[0]
    b = db.execute("select public.normalize_scientific_name('Monstera adansonii')").fetchone()[0]
    c = db.execute(
        "select public.normalize_scientific_name('Monstera deliciosa var. borsigiana')"
    ).fetchone()[0]

    assert len({a, b, c}) == 3


def test_normalisation_of_unusable_input_is_null(db: psycopg.Connection):
    assert db.execute("select public.normalize_scientific_name('')").fetchone()[0] is None
    assert db.execute("select public.normalize_scientific_name('123 456')").fetchone()[0] is None


def test_species_normalized_name_is_set_by_trigger(db: psycopg.Connection):
    db.execute(
        "insert into public.species (scientific_name, normalized_name) values (%s, %s)",
        ("Monstera deliciosa Liebm.", "deliberately-wrong"),
    )
    value = db.execute(
        "select normalized_name from public.species where scientific_name = %s",
        ("Monstera deliciosa Liebm.",),
    ).fetchone()[0]
    assert value == "monstera deliciosa", "a client-supplied normalized_name must be overwritten"


def test_species_variants_collide_on_one_row(db: psycopg.Connection):
    """The whole point of A23: three spellings must not become three lineages."""
    db.execute("insert into public.species (scientific_name) values ('Monstera deliciosa')")

    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into public.species (scientific_name) values ('monstera  deliciosa Liebm.')"
        )


def test_genus_is_derived_when_absent(db: psycopg.Connection):
    db.execute("insert into public.species (scientific_name) values ('Ficus elastica')")
    genus = db.execute(
        "select genus from public.species where normalized_name = 'ficus elastica'"
    ).fetchone()[0]
    assert genus == "ficus"


# --- upsert_species() ---------------------------------------------------------


def test_upsert_species_deduplicates(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)

    first = db.execute("select id from public.upsert_species('Monstera deliciosa')").fetchone()[0]
    second = db.execute(
        "select id from public.upsert_species('  monstera deliciosa Liebm. ')"
    ).fetchone()[0]

    assert first == second, "the confirm flow would have forked the species lineage"


def test_upsert_species_fills_gaps_without_overwriting(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)

    db.execute("select public.upsert_species('Monstera deliciosa', 'Swiss Cheese Plant')")
    row = db.execute(
        "select common_name, family from public.upsert_species("
        "'Monstera deliciosa', 'Something Else', 'Araceae')"
    ).fetchone()

    assert row[0] == "Swiss Cheese Plant", "an existing common_name must not be overwritten"
    assert row[1] == "Araceae", "a missing family should be filled in"


def test_upsert_species_requires_authentication(db: psycopg.Connection):
    db.execute("set local role authenticated")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select public.upsert_species('Monstera deliciosa')")


def test_user_cannot_insert_species_directly(db: psycopg.Connection, make_user):
    """Direct writes are admin-only; users go through upsert_species()."""
    user_id = make_user()
    as_user(db, user_id)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("insert into public.species (scientific_name) values ('Fakus inventus')")


def test_any_authenticated_user_can_read_species(db: psycopg.Connection, make_user):
    as_postgres(db)
    db.execute("insert into public.species (scientific_name) values ('Ficus lyrata')")

    user_id = make_user()
    as_user(db, user_id)
    rows = db.execute(
        "select id from public.species where normalized_name = 'ficus lyrata'"
    ).fetchall()
    assert len(rows) == 1


# --- plants -------------------------------------------------------------------


def test_plant_can_be_created_without_a_name(db: psycopg.Connection, make_user):
    """A2: the plant exists before the user names it (FINAL §3 step 5)."""
    user_id = make_user()
    as_user(db, user_id)

    plant_id = _make_plant(db, user_id)
    row = db.execute(
        "select name, status, current_health_status from public.plants where id = %s",
        (plant_id,),
    ).fetchone()

    assert row[0] is None
    assert row[1] == "PENDING_IDENTIFICATION"
    assert row[2] == "UNKNOWN"


def test_plant_name_cannot_be_blank(db: psycopg.Connection, make_user):
    """Null means "not yet named"; an empty string is a bug that would render as one."""
    user_id = make_user()
    as_user(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        _make_plant(db, user_id, name="   ")


def test_archived_status_requires_a_timestamp(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        _make_plant(db, user_id, status="ARCHIVED")


def test_archive_and_restore_round_trip(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id, name="מונסטרה")

    db.execute(
        "update public.plants set status = 'ARCHIVED', archived_at = now() where id = %s",
        (plant_id,),
    )
    db.execute(
        "update public.plants set status = 'ACTIVE', archived_at = null where id = %s",
        (plant_id,),
    )

    row = db.execute(
        "select status, archived_at from public.plants where id = %s", (plant_id,)
    ).fetchone()
    assert row[0] == "ACTIVE"
    assert row[1] is None


def test_timestamp_without_archived_status_is_rejected(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("update public.plants set archived_at = now() where id = %s", (plant_id,))


def test_user_cannot_see_another_users_plant(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_postgres(db)
    bob_plant = _make_plant(db, bob, name="bob's plant")

    as_user(db, alice)
    rows = db.execute("select id from public.plants where id = %s", (bob_plant,)).fetchall()
    assert rows == []


def test_user_cannot_create_a_plant_owned_by_someone_else(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_user(db, alice)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _make_plant(db, bob)


def test_plants_cannot_be_deleted_by_their_owner(db: psycopg.Connection, make_user):
    """FINAL §21: archive is the normal action; there is no user DELETE policy."""
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)

    db.execute("delete from public.plants where id = %s", (plant_id,))

    as_postgres(db)
    still_there = db.execute(
        "select count(*) from public.plants where id = %s", (plant_id,)
    ).fetchone()[0]
    assert still_there == 1


# --- plant_environments -------------------------------------------------------


def test_environment_is_one_row_per_plant(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)

    db.execute("insert into public.plant_environments (plant_id) values (%s)", (plant_id,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("insert into public.plant_environments (plant_id) values (%s)", (plant_id,))


def test_environment_fields_are_all_optional(db: psycopg.Connection, make_user):
    """FINAL §18: the Care Agent works with partial environment data."""
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)

    db.execute("insert into public.plant_environments (plant_id) values (%s)", (plant_id,))
    row = db.execute(
        "select location_type, light_level, temperature_c from public.plant_environments "
        "where plant_id = %s",
        (plant_id,),
    ).fetchone()
    assert row == (None, None, None)


@pytest.mark.parametrize(
    ("column", "value"),
    [("temperature_c", "999"), ("temperature_c", "-100"), ("humidity_percent", "150")],
)
def test_environment_rejects_out_of_range_readings(
    db: psycopg.Connection, make_user, column: str, value: str
):
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            f"insert into public.plant_environments (plant_id, {column}) values (%s, {value})",
            (plant_id,),
        )


def test_user_cannot_write_environment_for_another_users_plant(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_postgres(db)
    bob_plant = _make_plant(db, bob)

    as_user(db, alice)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("insert into public.plant_environments (plant_id) values (%s)", (bob_plant,))


# --- plant_images -------------------------------------------------------------


def _insert_image(conn: psycopg.Connection, user_id, plant_id, **kw):
    return conn.execute(
        """
        insert into public.plant_images
          (user_id, plant_id, storage_path_original, mime_type, size_bytes,
           context_type, ai_used, user_visible, retention_reason)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id
        """,
        (
            user_id,
            plant_id,
            kw.get("path", f"{user_id}/{plant_id}/gallery/a.jpg"),
            kw.get("mime_type", "image/jpeg"),
            kw.get("size_bytes", 1024),
            kw.get("context_type", "gallery"),
            kw.get("ai_used", False),
            kw.get("user_visible", True),
            kw.get("retention_reason"),
        ),
    ).fetchone()[0]


@pytest.mark.parametrize("mime", ["image/gif", "application/pdf", "image/svg+xml"])
def test_unsupported_mime_types_are_rejected(db: psycopg.Connection, make_user, mime: str):
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_image(db, user_id, plant_id, mime_type=mime)


def test_oversized_image_is_rejected(db: psycopg.Connection, make_user):
    """FINAL §20: 10 MB maximum."""
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_image(db, user_id, plant_id, size_bytes=10485761)


def test_hidden_image_must_carry_a_retention_reason(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_image(db, user_id, plant_id, user_visible=False)


def test_ai_used_image_cannot_be_deleted_by_its_owner(db: psycopg.Connection, make_user):
    """FINAL §20 retention: hidden from the user, but never physically removed."""
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)
    image_id = _insert_image(db, user_id, plant_id, ai_used=True)

    db.execute("delete from public.plant_images where id = %s", (image_id,))

    as_postgres(db)
    still_there = db.execute(
        "select count(*) from public.plant_images where id = %s", (image_id,)
    ).fetchone()[0]
    assert still_there == 1


def test_unused_image_can_be_deleted_by_its_owner(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)
    image_id = _insert_image(db, user_id, plant_id, ai_used=False)

    db.execute("delete from public.plant_images where id = %s", (image_id,))

    gone = db.execute(
        "select count(*) from public.plant_images where id = %s", (image_id,)
    ).fetchone()[0]
    assert gone == 0


def test_user_cannot_attach_an_image_to_another_users_plant(db: psycopg.Connection, make_user):
    """The user_id column alone is not enough — the plant must match too."""
    alice = make_user()
    bob = make_user()
    as_postgres(db)
    bob_plant = _make_plant(db, bob)

    as_user(db, alice)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _insert_image(db, alice, bob_plant)


def test_main_image_can_be_set_and_survives_image_deletion(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)
    plant_id = _make_plant(db, user_id)
    image_id = _insert_image(db, user_id, plant_id)

    db.execute("update public.plants set main_image_id = %s where id = %s", (image_id, plant_id))
    db.execute("delete from public.plant_images where id = %s", (image_id,))

    value = db.execute(
        "select main_image_id from public.plants where id = %s", (plant_id,)
    ).fetchone()[0]
    assert value is None, "ON DELETE SET NULL should clear the reference, not orphan it"


# --- identifications ----------------------------------------------------------


def test_failed_identification_cannot_carry_a_species(db: psycopg.Connection, make_user):
    """FINAL §25 as a database guarantee, not a convention in application code."""
    user_id = make_user()
    as_postgres(db)
    species_id = db.execute(
        "insert into public.species (scientific_name) values ('Monstera deliciosa') returning id"
    ).fetchone()[0]
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            """
            insert into public.identifications
              (user_id, plant_id, status, primary_species_id)
            values (%s, %s, 'FAILED', %s)
            """,
            (user_id, plant_id, species_id),
        )


def test_needs_more_information_cannot_carry_a_confidence_verdict(
    db: psycopg.Connection, make_user
):
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            """
            insert into public.identifications (user_id, plant_id, status, confidence_level)
            values (%s, %s, 'NEEDS_MORE_INFORMATION', 'HIGH')
            """,
            (user_id, plant_id),
        )


def test_confidence_above_one_violates_the_check(db: psycopg.Connection, make_user):
    """A18 fixes the scale at 0.000-1.000. 1.5 fits numeric(4,3), so this is the
    CHECK constraint doing the work."""
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        _make_identification(db, user_id, plant_id, confidence_score="1.5")


def test_percentage_style_confidence_cannot_be_stored(db: psycopg.Connection, make_user):
    """A model or a caller emitting 85 instead of 0.85 must fail loudly rather than
    be silently truncated. numeric(4,3) rejects it at the type level, before the
    CHECK is even reached — which is why this asserts a different error class."""
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.NumericValueOutOfRange):
        _make_identification(db, user_id, plant_id, confidence_score=85)


def test_valid_confidence_is_stored_at_three_decimals(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)
    ident_id = _make_identification(db, user_id, plant_id, confidence_score="0.912")

    value = db.execute(
        "select confidence_score from public.identifications where id = %s", (ident_id,)
    ).fetchone()[0]
    assert str(value) == "0.912"


@pytest.mark.parametrize(
    "url",
    ["http://en.wikipedia.org/wiki/X", "https://example.com/wiki/X", "/wiki/Monstera"],
)
def test_invented_wikipedia_urls_are_rejected(db: psycopg.Connection, make_user, url: str):
    """FINAL §8: the URL must never be invented. Only a verified page is stored."""
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            """
            insert into public.identifications (user_id, plant_id, status, wikipedia_url)
            values (%s, %s, 'SUCCESS', %s)
            """,
            (user_id, plant_id, url),
        )


def test_verified_wikipedia_url_is_accepted(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)

    db.execute(
        """
        insert into public.identifications (user_id, plant_id, status, wikipedia_url)
        values (%s, %s, 'SUCCESS', 'https://he.wikipedia.org/wiki/%%D7%%9E%%D7%%95%%D7%%A0')
        """,
        (user_id, plant_id),
    )


def test_identification_history_is_append_only_for_users(db: psycopg.Connection, make_user):
    """Re-identification adds a row; the previous one is retained (FINAL §8)."""
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)
    ident_id = _make_identification(db, user_id, plant_id)

    as_user(db, user_id)
    db.execute(
        "update public.identifications set user_description = 'rewritten' where id = %s",
        (ident_id,),
    )
    db.execute("delete from public.identifications where id = %s", (ident_id,))

    as_postgres(db)
    row = db.execute(
        "select user_description from public.identifications where id = %s", (ident_id,)
    ).fetchone()
    assert row is not None, "a user was able to delete identification history"
    assert row[0] is None, "a user was able to rewrite identification history"


def test_user_cannot_see_another_users_identifications(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_postgres(db)
    bob_plant = _make_plant(db, bob)
    bob_ident = _make_identification(db, bob, bob_plant)

    as_user(db, alice)
    rows = db.execute(
        "select id from public.identifications where id = %s", (bob_ident,)
    ).fetchall()
    assert rows == []


# --- identification_candidates ------------------------------------------------


def test_candidate_species_id_is_optional(db: psycopg.Connection, make_user):
    """Plan decision 2: candidates hold raw names; the species row is made at confirm."""
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)
    ident_id = _make_identification(db, user_id, plant_id)

    db.execute(
        """
        insert into public.identification_candidates
          (identification_id, scientific_name, rank, confidence_score)
        values (%s, 'Monstera deliciosa', 1, 0.91)
        """,
        (ident_id,),
    )
    row = db.execute(
        "select species_id, scientific_name from public.identification_candidates "
        "where identification_id = %s",
        (ident_id,),
    ).fetchone()
    assert row[0] is None
    assert row[1] == "Monstera deliciosa"


def test_candidate_ranks_are_unique_per_identification(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)
    ident_id = _make_identification(db, user_id, plant_id)

    db.execute(
        "insert into public.identification_candidates (identification_id, scientific_name, rank) "
        "values (%s, 'A a', 1)",
        (ident_id,),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into public.identification_candidates "
            "(identification_id, scientific_name, rank) values (%s, 'B b', 1)",
            (ident_id,),
        )


@pytest.mark.parametrize("rank", [0, 4, -1])
def test_candidate_rank_is_limited_to_three(db: psycopg.Connection, make_user, rank: int):
    """FINAL §8: a primary candidate plus up to two alternatives."""
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)
    ident_id = _make_identification(db, user_id, plant_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into public.identification_candidates "
            "(identification_id, scientific_name, rank) values (%s, 'A a', %s)",
            (ident_id, rank),
        )


def test_user_cannot_see_another_users_candidates(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_postgres(db)
    bob_plant = _make_plant(db, bob)
    bob_ident = _make_identification(db, bob, bob_plant)
    db.execute(
        "insert into public.identification_candidates "
        "(identification_id, scientific_name, rank) values (%s, 'A a', 1)",
        (bob_ident,),
    )

    as_user(db, alice)
    rows = db.execute("select id from public.identification_candidates").fetchall()
    assert rows == []


# --- cross-cutting ------------------------------------------------------------


def test_every_public_table_still_has_rls(db: psycopg.Connection):
    rows = db.execute(
        """
        select c.relname from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity
        """
    ).fetchall()
    assert rows == [], f"tables without RLS: {[r[0] for r in rows]}"


def test_deleting_a_user_cascades_to_their_plants(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_postgres(db)
    plant_id = _make_plant(db, user_id)

    db.execute("delete from auth.users where id = %s", (user_id,))

    remaining = db.execute(
        "select count(*) from public.plants where id = %s", (plant_id,)
    ).fetchone()[0]
    assert remaining == 0


def test_species_with_plants_cannot_be_deleted(db: psycopg.Connection, make_user):
    """ON DELETE RESTRICT: a species must not vanish from under a user's plant."""
    user_id = make_user()
    as_postgres(db)
    species_id = db.execute(
        "insert into public.species (scientific_name) values ('Ficus benjamina') returning id"
    ).fetchone()[0]
    db.execute(
        "insert into public.plants (user_id, species_id, status) values (%s, %s, 'ACTIVE')",
        (user_id, species_id),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute("delete from public.species where id = %s", (species_id,))
