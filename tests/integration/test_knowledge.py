"""Behavioural tests for the knowledge schema.

The guarantees under test are the ones FINAL §10 and §29 care about: published
knowledge is immutable and never deleted, exactly one version is current per
species and language, users can read but never write, and a source's
classification cannot lie about its provenance.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.conftest import as_postgres, as_user, unique_domain

pytestmark = pytest.mark.integration


def _species(conn: psycopg.Connection, name: str | None = None) -> uuid.UUID:
    name = name or f"Testus {uuid.uuid4().hex[:10]}"
    return conn.execute(
        "insert into public.species (scientific_name) values (%s) returning id", (name,)
    ).fetchone()[0]


def _version(
    conn: psycopg.Connection, species_id: uuid.UUID, number: int = 1, current: bool = True
) -> uuid.UUID:
    return conn.execute(
        """
        insert into public.knowledge_versions
          (species_id, version_number, content, is_current)
        values (%s, %s, %s::jsonb, %s) returning id
        """,
        (species_id, number, '{"watering": "כל 7 ימים"}', current),
    ).fetchone()[0]


def _make_admin(conn: psycopg.Connection, user_id: uuid.UUID) -> None:
    conn.execute("update public.profiles set role = 'ADMIN' where id = %s", (user_id,))


# --- immutability -------------------------------------------------------------


def test_published_content_cannot_be_edited(db: psycopg.Connection):
    """FINAL §10: published versions are immutable."""
    version_id = _version(db, _species(db))

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute(
            "update public.knowledge_versions set content = %s::jsonb where id = %s",
            ('{"watering": "tampered"}', version_id),
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("version_number", "99"),
        ("language", "'en'"),
        # now() returns the transaction timestamp, which equals the value the row
        # was inserted with, so it would be a no-op rather than a rejected change.
        ("published_at", "now() + interval '1 day'"),
        ("source_summary", "'{}'::jsonb"),
    ],
)
def test_other_published_fields_are_immutable(db: psycopg.Connection, column: str, value: str):
    version_id = _version(db, _species(db))

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute(
            f"update public.knowledge_versions set {column} = {value} where id = %s",
            (version_id,),
        )


def test_a_no_op_update_is_not_treated_as_tampering(db: psycopg.Connection):
    """The guard compares values, not the presence of a SET clause, so rewriting a
    column with its existing value is harmless. Worth pinning: an ORM that issues
    full-row updates would otherwise be unable to touch these rows at all."""
    version_id = _version(db, _species(db))

    db.execute(
        "update public.knowledge_versions set content = content, is_current = false where id = %s",
        (version_id,),
    )


def test_is_current_remains_mutable(db: psycopg.Connection):
    """The correction to the plan: a row-immutable table could never demote a
    predecessor, which publishing a newer version requires."""
    version_id = _version(db, _species(db))

    db.execute(
        "update public.knowledge_versions set is_current = false where id = %s", (version_id,)
    )

    value = db.execute(
        "select is_current from public.knowledge_versions where id = %s", (version_id,)
    ).fetchone()[0]
    assert value is False


def test_published_version_cannot_be_deleted(db: psycopg.Connection):
    """FINAL §29: historical published versions are never deleted, by anyone."""
    version_id = _version(db, _species(db))

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("delete from public.knowledge_versions where id = %s", (version_id,))


def _source(db: psycopg.Connection) -> uuid.UUID:
    version_id = _version(db, _species(db))
    return db.execute(
        """
        insert into public.knowledge_sources
          (knowledge_version_id, source_class, title, url)
        values (%s, 'EXTERNAL_UNAPPROVED', 'A page', 'https://example.com/x')
        returning id
        """,
        (version_id,),
    ).fetchone()[0]


def test_source_cannot_be_updated(db: psycopg.Connection):
    source_id = _source(db)

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute(
            "update public.knowledge_sources set title = 'changed' where id = %s", (source_id,)
        )


def test_source_cannot_be_deleted(db: psycopg.Connection):
    """Separate from the update case on purpose: a failed statement aborts the
    transaction, so two expected failures cannot share one."""
    source_id = _source(db)

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("delete from public.knowledge_sources where id = %s", (source_id,))


# --- one current version ------------------------------------------------------


def test_only_one_version_can_be_current_per_species(db: psycopg.Connection):
    species_id = _species(db)
    _version(db, species_id, number=1, current=True)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _version(db, species_id, number=2, current=True)


def test_publishing_a_new_version_after_demoting_works(db: psycopg.Connection):
    """The real publication sequence: demote, then insert, in one transaction."""
    species_id = _species(db)
    v1 = _version(db, species_id, number=1, current=True)

    db.execute("update public.knowledge_versions set is_current = false where id = %s", (v1,))
    v2 = _version(db, species_id, number=2, current=True)

    rows = db.execute(
        "select id, is_current from public.knowledge_versions where species_id = %s "
        "order by version_number",
        (species_id,),
    ).fetchall()
    assert rows == [(v1, False), (v2, True)]


def test_history_survives_publication_of_a_newer_version(db: psycopg.Connection):
    species_id = _species(db)
    v1 = _version(db, species_id, number=1, current=True)
    db.execute("update public.knowledge_versions set is_current = false where id = %s", (v1,))
    _version(db, species_id, number=2, current=True)

    content = db.execute(
        "select content->>'watering' from public.knowledge_versions where id = %s", (v1,)
    ).fetchone()[0]
    assert content == "כל 7 ימים", "the superseded version's content must be untouched"


def test_a_language_publishes_independently(db: psycopg.Connection):
    """Decision 4: uniqueness keys on (species_id, language), so a future English
    localisation can publish without colliding with Hebrew."""
    species_id = _species(db)
    _version(db, species_id, number=1, current=True)

    db.execute(
        """
        insert into public.knowledge_versions
          (species_id, language, version_number, content, is_current)
        values (%s, 'en', 1, '{"watering": "every 7 days"}'::jsonb, true)
        """,
        (species_id,),
    )
    count = db.execute(
        "select count(*) from public.knowledge_versions where species_id = %s and is_current",
        (species_id,),
    ).fetchone()[0]
    assert count == 2


def test_version_numbers_are_unique_per_species_and_language(db: psycopg.Connection):
    species_id = _species(db)
    _version(db, species_id, number=1, current=True)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _version(db, species_id, number=1, current=False)


# --- source provenance --------------------------------------------------------


def test_external_source_must_carry_a_url(db: psycopg.Connection):
    """FINAL §10: every external claim requires a real source."""
    version_id = _version(db, _species(db))

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into public.knowledge_sources (knowledge_version_id, source_class, title) "
            "values (%s, 'EXTERNAL_UNAPPROVED', 'No URL')",
            (version_id,),
        )


def test_approved_source_must_link_to_an_approved_domain(db: psycopg.Connection):
    """Only a real domain match may be classified APPROVED."""
    version_id = _version(db, _species(db))

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            """
            insert into public.knowledge_sources
              (knowledge_version_id, source_class, url)
            values (%s, 'APPROVED', 'https://rhs.org.uk/x')
            """,
            (version_id,),
        )


def test_ai_generated_claim_may_have_no_url(db: psycopg.Connection):
    """That is precisely what AI_GENERATED_REQUIRES_VERIFICATION means (FINAL §10)."""
    version_id = _version(db, _species(db))

    db.execute(
        """
        insert into public.knowledge_sources (knowledge_version_id, source_class, citation_text)
        values (%s, 'AI_GENERATED_REQUIRES_VERIFICATION', 'לא אומת')
        """,
        (version_id,),
    )


def test_ai_generated_claim_cannot_borrow_an_approved_source(db: psycopg.Connection):
    """An unverified claim must not masquerade as a cited one."""
    species_id = _species(db)
    version_id = _version(db, species_id)
    approved_id = db.execute(
        "insert into public.approved_sources (name, domain) values ('RHS', %s) returning id",
        (unique_domain(),),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            """
            insert into public.knowledge_sources
              (knowledge_version_id, source_class, approved_source_id)
            values (%s, 'AI_GENERATED_REQUIRES_VERIFICATION', %s)
            """,
            (version_id, approved_id),
        )


def test_a_version_with_sources_cannot_be_removed(db: psycopg.Connection):
    """ON DELETE RESTRICT keeps provenance from being orphaned."""
    version_id = _version(db, _species(db))
    db.execute(
        "insert into public.knowledge_sources (knowledge_version_id, source_class, url) "
        "values (%s, 'EXTERNAL_UNAPPROVED', 'https://example.com/x')",
        (version_id,),
    )
    # The delete trigger fires first, which is itself the guarantee we want.
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("delete from public.knowledge_versions where id = %s", (version_id,))


@pytest.mark.parametrize("domain", ["https://rhs.org.uk", "rhs.org.uk/plants", "RHS.org.uk", "x"])
def test_approved_source_domain_must_be_a_bare_hostname(db: psycopg.Connection, domain: str):
    """Classification is a suffix match on a URL's host, so a scheme or path here
    would silently never match anything."""
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into public.approved_sources (name, domain) values ('X', %s)", (domain,))


# --- access control -----------------------------------------------------------


def test_user_reads_the_current_version(db: psycopg.Connection, make_user):
    species_id = _species(db)
    _version(db, species_id, number=1, current=True)

    user_id = make_user()
    as_user(db, user_id)
    rows = db.execute(
        "select id from public.knowledge_versions where species_id = %s", (species_id,)
    ).fetchall()
    assert len(rows) == 1


def test_user_cannot_read_superseded_versions(db: psycopg.Connection, make_user):
    species_id = _species(db)
    v1 = _version(db, species_id, number=1, current=True)
    db.execute("update public.knowledge_versions set is_current = false where id = %s", (v1,))
    _version(db, species_id, number=2, current=True)

    user_id = make_user()
    as_user(db, user_id)
    rows = db.execute(
        "select id from public.knowledge_versions where species_id = %s", (species_id,)
    ).fetchall()
    assert [r[0] for r in rows] != [v1]
    assert v1 not in [r[0] for r in rows]


def test_admin_can_read_version_history(db: psycopg.Connection, make_user):
    """The policy the gap audit caught missing. Without it the Admin Panel's
    "Published Knowledge · history" view returns nothing under a JWT-scoped client."""
    species_id = _species(db)
    v1 = _version(db, species_id, number=1, current=True)
    db.execute("update public.knowledge_versions set is_current = false where id = %s", (v1,))
    _version(db, species_id, number=2, current=True)

    admin = make_user()
    _make_admin(db, admin)
    as_user(db, admin)

    rows = db.execute(
        "select id from public.knowledge_versions where species_id = %s", (species_id,)
    ).fetchall()
    assert len(rows) == 2, "an admin must be able to see superseded versions"


def test_user_cannot_publish_knowledge(db: psycopg.Connection, make_user):
    """FINAL §10: users read published knowledge and cannot edit it."""
    species_id = _species(db)
    user_id = make_user()
    as_user(db, user_id)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _version(db, species_id)


def test_user_cannot_see_drafts(db: psycopg.Connection, make_user):
    species_id = _species(db)
    db.execute(
        "insert into public.knowledge_drafts (species_id, status) values (%s, 'RESEARCHING')",
        (species_id,),
    )

    user_id = make_user()
    as_user(db, user_id)
    rows = db.execute("select id from public.knowledge_drafts").fetchall()
    assert rows == []


def test_user_cannot_see_approved_sources(db: psycopg.Connection, make_user):
    """FINAL §29 puts Approved Sources under Admin. The assertion covers every row,
    not just this test's, because a user must see none of them at all."""
    db.execute(
        "insert into public.approved_sources (name, domain) values ('RHS', %s)", (unique_domain(),)
    )

    user_id = make_user()
    as_user(db, user_id)
    assert db.execute("select id from public.approved_sources").fetchall() == []


def test_admin_manages_approved_sources(db: psycopg.Connection, make_user):
    admin = make_user()
    _make_admin(db, admin)
    as_user(db, admin)

    domain = unique_domain()
    db.execute("insert into public.approved_sources (name, domain) values ('RHS', %s)", (domain,))
    rows = db.execute(
        "select name from public.approved_sources where domain = %s", (domain,)
    ).fetchall()
    assert rows == [("RHS",)]


def test_user_reads_sources_of_the_current_version_only(db: psycopg.Connection, make_user):
    species_id = _species(db)
    v1 = _version(db, species_id, number=1, current=True)
    db.execute(
        "insert into public.knowledge_sources (knowledge_version_id, source_class, url) "
        "values (%s, 'EXTERNAL_UNAPPROVED', 'https://example.com/old')",
        (v1,),
    )
    db.execute("update public.knowledge_versions set is_current = false where id = %s", (v1,))

    user_id = make_user()
    as_user(db, user_id)
    # Scoped to this test's own version: seeded knowledge has sources of its own,
    # which the user legitimately can see because those versions are current.
    assert (
        db.execute(
            "select id from public.knowledge_sources where knowledge_version_id = %s", (v1,)
        ).fetchall()
        == []
    )


# --- knowledge reports --------------------------------------------------------


def test_user_can_report_an_error_and_read_it_back(db: psycopg.Connection, make_user):
    species_id = _species(db)
    user_id = make_user()
    as_user(db, user_id)

    db.execute(
        "insert into public.knowledge_reports (user_id, species_id, report_text) "
        "values (%s, %s, %s)",
        (user_id, species_id, "המידע על ההשקיה נראה לי לא נכון."),
    )
    rows = db.execute("select status from public.knowledge_reports").fetchall()
    assert rows == [("OPEN",)]


def test_report_must_name_a_subject(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_user(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into public.knowledge_reports (user_id, report_text) values (%s, 'x')",
            (user_id,),
        )


def test_user_cannot_see_another_users_report(db: psycopg.Connection, make_user):
    species_id = _species(db)
    alice = make_user()
    bob = make_user()
    as_postgres(db)
    db.execute(
        "insert into public.knowledge_reports (user_id, species_id, report_text) "
        "values (%s, %s, 'bob''s report')",
        (bob, species_id),
    )

    as_user(db, alice)
    assert db.execute("select id from public.knowledge_reports").fetchall() == []


def test_user_cannot_edit_the_admin_triage_fields(db: psycopg.Connection, make_user):
    """status and admin_note are the admin's record, not the reporter's."""
    species_id = _species(db)
    user_id = make_user()
    as_user(db, user_id)
    db.execute(
        "insert into public.knowledge_reports (user_id, species_id, report_text) "
        "values (%s, %s, 'x')",
        (user_id, species_id),
    )

    db.execute("update public.knowledge_reports set status = 'DISMISSED'")

    as_postgres(db)
    status = db.execute(
        "select status from public.knowledge_reports where user_id = %s", (user_id,)
    ).fetchone()[0]
    assert status == "OPEN", "a reporter was able to close their own report"


def test_admin_triages_reports(db: psycopg.Connection, make_user):
    species_id = _species(db)
    reporter = make_user()
    admin = make_user()
    as_postgres(db)
    db.execute(
        "insert into public.knowledge_reports (user_id, species_id, report_text) "
        "values (%s, %s, 'x')",
        (reporter, species_id),
    )
    _make_admin(db, admin)

    as_user(db, admin)
    db.execute("update public.knowledge_reports set status = 'REVIEWING', admin_note = 'looking'")
    status = db.execute("select status from public.knowledge_reports").fetchone()[0]
    assert status == "REVIEWING"


# --- drafts -------------------------------------------------------------------


def test_only_one_open_draft_per_species(db: psycopg.Connection):
    """Two concurrent research runs would race to publish the same knowledge."""
    species_id = _species(db)
    db.execute(
        "insert into public.knowledge_drafts (species_id, status) values (%s, 'RESEARCHING')",
        (species_id,),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into public.knowledge_drafts (species_id, status) values (%s, 'DRAFT')",
            (species_id,),
        )


def test_a_closed_draft_does_not_block_a_retry(db: psycopg.Connection):
    """A17: a rejected or failed draft must leave the species retriable, or plants
    stranded in KNOWLEDGE_PENDING can never be released."""
    species_id = _species(db)
    db.execute(
        "insert into public.knowledge_drafts (species_id, status) values (%s, 'FAILED')",
        (species_id,),
    )
    db.execute(
        "insert into public.knowledge_drafts (species_id, status) values (%s, 'REJECTED')",
        (species_id,),
    )
    db.execute(
        "insert into public.knowledge_drafts (species_id, status) values (%s, 'RESEARCHING')",
        (species_id,),
    )

    count = db.execute(
        "select count(*) from public.knowledge_drafts where species_id = %s", (species_id,)
    ).fetchone()[0]
    assert count == 3


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
