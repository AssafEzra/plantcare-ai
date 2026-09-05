"""The RLS matrix: every user-owned table, every axis (FINAL §26, TESTING §11).

`FINAL §26` says Row Level Security is mandatory on user-owned tables and that
Python authorization checks are not a substitute. Individual tests elsewhere prove
individual policies; this file proves the *property* — that the rule holds
uniformly, on every table, with no gaps.

That distinction is not theoretical. Two policies were found missing during this
build (`agent_requests` had no INSERT policy in PR 13, `admin_audit_log` had none
in PR 15) and both were invisible precisely because the code paths that touched
them ran as the service role. A table added without a policy passes every test
written about the feature it belongs to. It fails here.

Four axes per table:

* **read own** — the row is visible to its owner. Without this the other three
  assertions could all pass on a table nobody can read at all.
* **read other** — invisible to a second authenticated user.
* **write other** — an UPDATE or DELETE aimed at another user's row touches
  nothing. On tables with no UPDATE policy this holds for a second reason (there
  is no policy to satisfy); that is the point of a uniform matrix.
* **anonymous** — invisible without a JWT.

Plus a fifth, applied to the tables a user inserts into directly: a row carrying
someone else's `user_id` is refused by the policy's WITH CHECK. That one is not
about reading — it is the difference between a database that enforces ownership
and one that merely filters it.

The connection runs as `authenticated` with a `request.jwt.claims` setting, which
is exactly what PostgREST does for a user token. Running as `postgres` would
bypass RLS and make the whole file vacuous, so `as_user` is called in every test
and never skipped.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest

from tests.integration.conftest import as_postgres, as_user, unique_species_name

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Row:
    """One row, and the column that identifies it.

    A column rather than always `id` because `health_assessment_images` has a
    composite key and no `id` at all — a detail that would otherwise have quietly
    excluded it from the matrix.
    """

    table: str
    key: str
    value: str


def _build(conn: psycopg.Connection, user_id: uuid.UUID) -> dict[str, Row]:
    """One row in every user-owned table, all belonging to `user_id`.

    Built as `postgres` on purpose: this is arranging the world, not exercising
    it. Every assertion afterwards runs as `authenticated`.
    """

    def one(table: str, columns: str, values: str, params: tuple, key: str = "id") -> Row:
        result = conn.execute(
            f"insert into public.{table} ({columns}) values ({values}) returning {key}", params
        ).fetchone()
        assert result is not None
        return Row(table, key, str(result[0]))

    world: dict[str, Row] = {}

    # Reference data, not user-owned, but a knowledge report has a CHECK
    # requiring a subject — it must be about a species or a published version.
    species = one("species", "scientific_name", "%s", (unique_species_name(),))
    world["_species"] = species

    # profiles and notification_preferences already exist — the signup trigger
    # wrote them when make_user inserted into auth.users.
    world["profiles"] = Row("profiles", "id", str(user_id))
    world["notification_preferences"] = Row("notification_preferences", "user_id", str(user_id))

    plant = one("plants", "user_id, name", "%s, %s", (user_id, "צמח מטריצה"))
    world["plants"] = plant

    world["plant_environments"] = one(
        "plant_environments", "plant_id, room", "%s, %s", (plant.value, "סלון")
    )
    image = one(
        "plant_images",
        "user_id, plant_id, storage_path_original, mime_type, size_bytes, context_type",
        "%s, %s, %s, %s, %s, %s",
        (
            user_id,
            plant.value,
            f"{user_id}/{plant.value}/gallery/a.jpg",
            "image/jpeg",
            1024,
            "gallery",
        ),
    )
    world["plant_images"] = image

    identification = one(
        "identifications",
        "user_id, plant_id, status",
        "%s, %s, %s",
        (user_id, plant.value, "SUCCESS"),
    )
    world["identifications"] = identification
    world["identification_candidates"] = one(
        "identification_candidates",
        "identification_id, scientific_name, rank",
        "%s, %s, %s",
        (identification.value, "Testus matrixensis", 1),
    )

    care_plan = one("care_plans", "user_id, plant_id", "%s, %s", (user_id, plant.value))
    world["care_plans"] = care_plan
    version = one(
        "care_plan_versions",
        "care_plan_id, version_number, professional_recommendations, source_type, status",
        "%s, %s, %s::jsonb, %s, %s",
        (care_plan.value, 1, '{"summary": "המלצה"}', "INITIAL_PLAN", "ACTIVE"),
    )
    world["care_plan_versions"] = version
    rule = one(
        "care_rules",
        "care_plan_version_id, action_type, interval_days",
        "%s, %s, %s",
        (version.value, "WATERING", 7),
    )
    world["care_rules"] = rule
    world["care_tasks"] = one(
        "care_tasks",
        "user_id, plant_id, care_rule_id, due_at_utc",
        "%s, %s, %s, now()",
        (user_id, plant.value, rule.value),
    )
    world["care_events"] = one(
        "care_events",
        "user_id, plant_id, event_type",
        "%s, %s, %s",
        (user_id, plant.value, "DONE"),
    )

    assessment = one(
        "health_assessments",
        "user_id, plant_id, overall_status",
        "%s, %s, %s",
        (user_id, plant.value, "HEALTHY"),
    )
    world["health_assessments"] = assessment
    world["health_assessment_images"] = one(
        "health_assessment_images",
        "health_assessment_id, plant_image_id",
        "%s, %s",
        (assessment.value, image.value),
        key="health_assessment_id",
    )
    world["health_observations"] = one(
        "health_observations",
        "health_assessment_id, observation_text",
        "%s, %s",
        (assessment.value, "העלים ירוקים ובריאים."),
    )
    world["health_issues"] = one(
        "health_issues",
        "health_assessment_id, issue_name, evidence",
        "%s, %s, %s",
        (assessment.value, "ייתכן יובש", "קצוות עלים חומים."),
    )
    world["health_recommendations"] = one(
        "health_recommendations",
        "health_assessment_id, recommendation_text",
        "%s, %s",
        (assessment.value, "להמשיך בשגרה הנוכחית."),
    )
    world["health_assessment_sources"] = one(
        "health_assessment_sources",
        "health_assessment_id, source_class, citation_text",
        "%s, %s, %s",
        (assessment.value, "AI_GENERATED_REQUIRES_VERIFICATION", "ידע כללי."),
    )

    world["knowledge_reports"] = one(
        "knowledge_reports",
        "user_id, plant_id, species_id, report_text",
        "%s, %s, %s, %s",
        (user_id, plant.value, species.value, "נראה שהמידע על ההשקיה שגוי."),
    )
    world["agent_requests"] = one(
        "agent_requests",
        "user_id, plant_id, agent_type",
        "%s, %s, %s",
        (user_id, plant.value, "HEALTH"),
    )
    world["notification_deliveries"] = one(
        "notification_deliveries",
        "user_id, dedupe_key",
        "%s, %s",
        (user_id, f"digest:{user_id}:{uuid.uuid4().hex[:8]}"),
    )
    world["system_events"] = one(
        "system_events",
        "user_id, plant_id, event_type",
        "%s, %s, %s",
        (user_id, plant.value, "PLANT_CREATED"),
    )
    return world


@pytest.fixture(scope="module")
def matrix(dsn: str) -> Iterator[tuple[psycopg.Connection, uuid.UUID, uuid.UUID, dict[str, Row]]]:
    """Two users and a full object graph for the first, built once.

    Once rather than per test: the matrix is ~90 cases and this graph is twenty
    inserts against a remote database. Each test gets a SAVEPOINT instead, so a
    statement that fails — several are *supposed* to — does not poison the rest,
    and the whole module still rolls back at the end.
    """
    conn = psycopg.connect(dsn, connect_timeout=20, autocommit=False)
    try:
        owner = _make_auth_user(conn)
        stranger = _make_auth_user(conn)
        yield conn, owner, stranger, _build(conn, owner)
    finally:
        conn.rollback()
        conn.close()


def _make_auth_user(conn: psycopg.Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        """
        insert into auth.users (
            instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
            raw_app_meta_data, raw_user_meta_data, created_at, updated_at
        ) values (
            '00000000-0000-0000-0000-000000000000', %s, 'authenticated', 'authenticated', %s,
            'x', now(), '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
            now(), now()
        )
        """,
        (user_id, f"{user_id}@example.test"),
    )
    return user_id


@pytest.fixture
def conn(matrix) -> Iterator[psycopg.Connection]:
    connection, _, _, _ = matrix
    connection.execute("savepoint axis")
    try:
        yield connection
    finally:
        connection.execute("rollback to savepoint axis")
        as_postgres(connection)


@pytest.fixture
def owner(matrix) -> uuid.UUID:
    return matrix[1]


@pytest.fixture
def stranger(matrix) -> uuid.UUID:
    return matrix[2]


@pytest.fixture
def world(matrix) -> dict[str, Row]:
    return matrix[3]


TABLES = [
    "profiles",
    "notification_preferences",
    "plants",
    "plant_environments",
    "plant_images",
    "identifications",
    "identification_candidates",
    "care_plans",
    "care_plan_versions",
    "care_rules",
    "care_tasks",
    "care_events",
    "health_assessments",
    "health_assessment_images",
    "health_observations",
    "health_issues",
    "health_recommendations",
    "health_assessment_sources",
    "knowledge_reports",
    "agent_requests",
    "notification_deliveries",
    "system_events",
]

# Tables a user inserts into through the application, with the column carrying
# ownership. Child tables are absent because their ownership is derived from the
# parent, which is a different guarantee and is covered by the read axes.
USER_INSERT_TABLES: list[tuple[str, str, str]] = [
    ("plants", "user_id, name", "%s, 'זר'"),
    (
        "plant_images",
        "user_id, plant_id, storage_path_original, mime_type, size_bytes, context_type",
        "%s, %s, 'x/y/z.jpg', 'image/jpeg', 100, 'gallery'",
    ),
    ("identifications", "user_id, plant_id, status", "%s, %s, 'SUCCESS'"),
    ("care_plans", "user_id, plant_id", "%s, %s"),
    ("care_events", "user_id, plant_id, event_type", "%s, %s, 'DONE'"),
    (
        "knowledge_reports",
        "user_id, plant_id, species_id, report_text",
        "%s, %s, %s, 'דיווח על טעות במידע.'",
    ),
    ("agent_requests", "user_id, plant_id, agent_type", "%s, %s, 'HEALTH'"),
    ("system_events", "user_id, plant_id, event_type", "%s, %s, 'PLANT_CREATED'"),
]


def _count(conn: psycopg.Connection, row: Row) -> int:
    result = conn.execute(
        f"select count(*) from public.{row.table} where {row.key} = %s", (row.value,)
    ).fetchone()
    assert result is not None
    return int(result[0])


# --- read own -------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
def test_the_owner_can_read_their_own_row(conn, owner, world, table):
    """The control. Without it, "the stranger sees nothing" would also pass on a
    table nobody can read, and a policy that denies everyone would look correct."""
    as_user(conn, owner)

    assert _count(conn, world[table]) == 1


# --- read other -----------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
def test_a_second_user_cannot_read_it(conn, stranger, world, table):
    as_user(conn, stranger)

    assert _count(conn, world[table]) == 0


# --- anonymous ------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
def test_an_anonymous_caller_cannot_read_it(conn, world, table):
    """The `anon` role is what an unauthenticated PostgREST request runs as."""
    conn.execute("set local role anon")
    conn.execute("select set_config('request.jwt.claims', null, true)")

    assert _count(conn, world[table]) == 0


# --- write other ----------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
def test_a_second_user_cannot_update_it(conn, stranger, world, table):
    """A no-op UPDATE, which still has to find the row before it can change it.

    RLS filters before any trigger fires, so this is 0 rows even on the tables
    whose immutability trigger would otherwise raise — and it stays 0 if that
    trigger is ever removed.
    """
    as_user(conn, stranger)
    row = world[table]

    result = conn.execute(
        f"update public.{row.table} set {row.key} = {row.key} where {row.key} = %s", (row.value,)
    )

    assert result.rowcount == 0


@pytest.mark.parametrize("table", TABLES)
def test_a_second_user_cannot_delete_it(conn, stranger, world, table):
    as_user(conn, stranger)
    row = world[table]

    result = conn.execute(f"delete from public.{row.table} where {row.key} = %s", (row.value,))

    assert result.rowcount == 0


@pytest.mark.parametrize("table", TABLES)
def test_the_row_survives_every_attempt(conn, owner, stranger, world, table):
    """The other half of the two tests above.

    `rowcount == 0` says the statement matched nothing. This says the row is still
    there afterwards — which is what actually matters, and what a policy that
    silently allowed the write would fail.
    """
    as_user(conn, stranger)
    row = world[table]
    conn.execute(f"delete from public.{row.table} where {row.key} = %s", (row.value,))

    as_user(conn, owner)
    assert _count(conn, row) == 1


# --- insert as someone else -----------------------------------------------------


@pytest.mark.parametrize(
    ("table", "columns", "values"), USER_INSERT_TABLES, ids=[t[0] for t in USER_INSERT_TABLES]
)
def test_a_user_cannot_insert_a_row_owned_by_someone_else(
    conn, owner, stranger, world, table, columns, values
):
    """The WITH CHECK half of ownership, and the one the read axes cannot reach.

    A database that filters reads by owner but accepts a write claiming another
    owner is not enforcing ownership — it is decorating it. The row would be
    invisible to the user who wrote it and visible to a victim who did not.
    """
    as_user(conn, stranger)
    supplied = (owner, world["plants"].value, world["_species"].value)
    params: tuple = supplied[: values.count("%s")]

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(f"insert into public.{table} ({columns}) values ({values})", params)


# --- the shape of the matrix itself ---------------------------------------------


def test_every_user_owned_table_is_in_the_matrix(conn):
    """A table added with RLS enabled but no entry here would never be tested.

    Read from `pg_tables`, not from a list, so the matrix cannot fall behind the
    schema silently. The exclusions are the tables that are not user-owned:
    reference data, admin-only tables, and the two the service role writes.
    """
    as_postgres(conn)
    not_user_owned = {
        "species",
        "approved_sources",
        "knowledge_drafts",
        "knowledge_versions",
        "knowledge_sources",
        "agent_executions",
        "admin_audit_log",
    }

    rows = conn.execute(
        """
        select tablename from pg_tables
         where schemaname = 'public' and rowsecurity
        """
    ).fetchall()
    present = {row[0] for row in rows} - not_user_owned

    assert present == set(TABLES), f"not covered by the matrix: {sorted(present - set(TABLES))}"
