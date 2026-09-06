"""Who may read research nobody has approved yet (PR 33).

This is the first time a non-admin can read AI content that no human has checked,
and it is the change in this PR that most deserves scrutiny. The policy is
deliberately narrow, and every clause of it is a test here:

* `READY_FOR_REVIEW` only — a DRAFT is empty, RESEARCHING is half-written, and
  FAILED and REJECTED are content nobody should act on;
* only for a species the reader actually owns a plant of;
* SELECT only. Every write stays admin-only, as it was.

Run against the real database with the connection dropped to `authenticated`,
because a superuser bypasses RLS and would make all of this pass vacuously.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.conftest import as_postgres, as_user, unique_species_name

pytestmark = pytest.mark.integration


def _species(conn: psycopg.Connection) -> uuid.UUID:
    return conn.execute(
        "insert into public.species (scientific_name) values (%s) returning id",
        (unique_species_name(),),
    ).fetchone()[0]


def _draft(
    conn: psycopg.Connection, species_id: uuid.UUID, status: str = "READY_FOR_REVIEW"
) -> uuid.UUID:
    return conn.execute(
        """
        insert into public.knowledge_drafts (species_id, status, content)
        values (%s, %s, %s::jsonb) returning id
        """,
        (species_id, status, '{"sections": {"watering": {"text": "כל 7 ימים"}}}'),
    ).fetchone()[0]


def _plant(conn: psycopg.Connection, user_id: uuid.UUID, species_id: uuid.UUID) -> uuid.UUID:
    return conn.execute(
        """
        insert into public.plants (user_id, species_id, name, status)
        values (%s, %s, 'בדיקה', 'ACTIVE') returning id
        """,
        (user_id, species_id),
    ).fetchone()[0]


def _visible(conn: psycopg.Connection, draft_id: uuid.UUID) -> int:
    return conn.execute(
        "select count(*) from public.knowledge_drafts where id = %s", (draft_id,)
    ).fetchone()[0]


def test_an_owner_can_read_the_research_their_plan_rests_on(db, make_user):
    """The whole point of the feature. Without this the plant shows a care plan
    and no way to see what it was built from."""
    owner = make_user()
    species = _species(db)
    draft = _draft(db, species)
    _plant(db, owner, species)

    as_user(db, owner)
    assert _visible(db, draft) == 1


def test_a_stranger_cannot(db, make_user):
    """Owning *a* plant is not owning a plant of *this* species. Without the
    correlated subquery this policy would expose every unreviewed article in the
    database to every signed-in user."""
    owner, stranger = make_user(), make_user()
    species, other_species = _species(db), _species(db)
    draft = _draft(db, species)
    _plant(db, owner, species)
    _plant(db, stranger, other_species)

    as_user(db, stranger)
    assert _visible(db, draft) == 0


def test_a_user_with_no_plants_sees_nothing(db, make_user):
    stranger = make_user()
    draft = _draft(db, _species(db))

    as_user(db, stranger)
    assert _visible(db, draft) == 0


@pytest.mark.parametrize("status", ["DRAFT", "RESEARCHING", "REJECTED", "FAILED"])
def test_only_finished_research_is_readable(db, make_user, status):
    """A DRAFT is empty and RESEARCHING is half-written, so both would render as a
    broken article. REJECTED is the one that matters: an administrator judged that
    content wrong, and showing it to the user afterwards would be worse than
    having shown nothing."""
    owner = make_user()
    species = _species(db)
    draft = _draft(db, species, status=status)
    _plant(db, owner, species)

    as_user(db, owner)
    assert _visible(db, draft) == 0


def test_reading_is_all_it_grants(db, make_user):
    """SELECT only. A plant owner may read the research behind their plan and must
    not be able to edit the knowledge base — FINAL §10 is explicit that users
    report errors and never edit."""
    owner = make_user()
    species = _species(db)
    draft = _draft(db, species)
    _plant(db, owner, species)

    as_user(db, owner)
    db.execute("update public.knowledge_drafts set status = 'APPROVED' where id = %s", (draft,))

    as_postgres(db)
    status = db.execute(
        "select status from public.knowledge_drafts where id = %s", (draft,)
    ).fetchone()[0]
    assert status == "READY_FOR_REVIEW", "a plant owner was able to approve their own knowledge"


def test_an_owner_cannot_create_knowledge(db, make_user):
    owner = make_user()
    species = _species(db)
    _plant(db, owner, species)

    as_user(db, owner)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(
            "insert into public.knowledge_drafts (species_id, status) values (%s, 'READY_FOR_REVIEW')",
            (species,),
        )


# --- provenance -----------------------------------------------------------------


def test_a_plan_cannot_cite_both_a_draft_and_a_version(db, make_user):
    """Exactly one source, or the question "what is this plan based on?" has two
    answers and the badge showing whether it was reviewed becomes a guess."""
    owner = make_user()
    species = _species(db)
    draft = _draft(db, species)
    plant = _plant(db, owner, species)
    version = db.execute(
        """
        insert into public.knowledge_versions (species_id, version_number, content, is_current)
        values (%s, 1, '{}'::jsonb, true) returning id
        """,
        (species,),
    ).fetchone()[0]
    plan = db.execute(
        "insert into public.care_plans (user_id, plant_id) values (%s, %s) returning id",
        (owner, plant),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            """
            insert into public.care_plan_versions
              (care_plan_id, version_number, professional_recommendations, source_type,
               knowledge_version_id, knowledge_draft_id)
            values (%s, 1, '{}'::jsonb, 'INITIAL_PLAN', %s, %s)
            """,
            (plan, version, draft),
        )


def test_provenance_cannot_be_rewritten_afterwards(db, make_user):
    """`care_plan_versions` is content-immutable, and which knowledge it rests on
    is content. Otherwise a plan built from an unreviewed draft could be quietly
    re-pointed at the published version and stop reporting that it was
    provisional."""
    owner = make_user()
    species = _species(db)
    draft = _draft(db, species)
    plant = _plant(db, owner, species)
    plan = db.execute(
        "insert into public.care_plans (user_id, plant_id) values (%s, %s) returning id",
        (owner, plant),
    ).fetchone()[0]
    version_id = db.execute(
        """
        insert into public.care_plan_versions
          (care_plan_id, version_number, professional_recommendations, source_type,
           knowledge_draft_id)
        values (%s, 1, '{}'::jsonb, 'INITIAL_PLAN', %s) returning id
        """,
        (plan, draft),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute(
            "update public.care_plan_versions set knowledge_draft_id = null where id = %s",
            (version_id,),
        )
