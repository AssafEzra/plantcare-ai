"""Behavioural tests for care, health and system infrastructure.

Several plan decisions became database constraints in this migration rather than
rules the scheduler has to remember. Those are the ones worth testing hardest:
A7 (weekday only anchors weekly recurrences), the one-pending-task-per-rule
materialisation invariant, duplicate done/skip rejection, and the retry ceiling.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.conftest import as_postgres, as_user

pytestmark = pytest.mark.integration


# --- builders -----------------------------------------------------------------


def _plant(conn: psycopg.Connection, user_id: uuid.UUID) -> uuid.UUID:
    return conn.execute(
        "insert into public.plants (user_id, status) values (%s, 'ACTIVE') returning id",
        (user_id,),
    ).fetchone()[0]


def _plan(conn: psycopg.Connection, user_id: uuid.UUID, plant_id: uuid.UUID) -> uuid.UUID:
    return conn.execute(
        "insert into public.care_plans (user_id, plant_id) values (%s, %s) returning id",
        (user_id, plant_id),
    ).fetchone()[0]


def _version(
    conn: psycopg.Connection,
    plan_id: uuid.UUID,
    number: int = 1,
    status: str = "PROPOSED",
    source: str = "INITIAL_PLAN",
    summary: str | None = None,
) -> uuid.UUID:
    return conn.execute(
        """
        insert into public.care_plan_versions
          (care_plan_id, version_number, status, professional_recommendations,
           source_type, change_summary)
        values (%s, %s, %s, %s::jsonb, %s, %s) returning id
        """,
        (plan_id, number, status, '{"light": "אור בהיר"}', source, summary),
    ).fetchone()[0]


def _rule(
    conn: psycopg.Connection,
    version_id: uuid.UUID,
    interval_days: int = 7,
    weekday: str | None = None,
    action: str = "WATERING",
) -> uuid.UUID:
    return conn.execute(
        """
        insert into public.care_rules
          (care_plan_version_id, action_type, interval_days, preferred_weekday)
        values (%s, %s, %s, %s) returning id
        """,
        (version_id, action, interval_days, weekday),
    ).fetchone()[0]


def _task(
    conn: psycopg.Connection,
    user_id: uuid.UUID,
    plant_id: uuid.UUID,
    rule_id: uuid.UUID,
    status: str = "PENDING",
) -> uuid.UUID:
    return conn.execute(
        """
        insert into public.care_tasks
          (user_id, plant_id, care_rule_id, due_at_utc, status, overdue_since, completed_at)
        values (%s, %s, %s, now(), %s, %s, %s) returning id
        """,
        (
            user_id,
            plant_id,
            rule_id,
            status,
            "now()" if status == "OVERDUE" else None,
            None,
        ),
    ).fetchone()[0]


def _assessment(
    conn: psycopg.Connection,
    user_id: uuid.UUID,
    plant_id: uuid.UUID,
    status: str = "HEALTHY",
    reason: str | None = None,
) -> uuid.UUID:
    return conn.execute(
        """
        insert into public.health_assessments
          (user_id, plant_id, overall_status, insufficient_information_reason)
        values (%s, %s, %s, %s) returning id
        """,
        (user_id, plant_id, status, reason),
    ).fetchone()[0]


# =============================================================================
# CARE
# =============================================================================


def test_only_one_active_version_per_plan(db: psycopg.Connection, make_user):
    """Two active versions would silently double every generated task."""
    user_id = make_user()
    plan_id = _plan(db, user_id, _plant(db, user_id))
    _version(db, plan_id, 1, status="ACTIVE")

    with pytest.raises(psycopg.errors.UniqueViolation):
        _version(db, plan_id, 2, status="ACTIVE", summary="second")


def test_version_status_can_advance(db: psycopg.Connection, make_user):
    """PROPOSED -> ACTIVE -> SUPERSEDED is the lifecycle the plan depends on."""
    user_id = make_user()
    plan_id = _plan(db, user_id, _plant(db, user_id))
    v = _version(db, plan_id, 1, status="PROPOSED")

    db.execute("update public.care_plan_versions set status = 'ACTIVE' where id = %s", (v,))
    db.execute("update public.care_plan_versions set status = 'SUPERSEDED' where id = %s", (v,))

    assert (
        db.execute("select status from public.care_plan_versions where id = %s", (v,)).fetchone()[0]
        == "SUPERSEDED"
    )


def test_professional_recommendations_cannot_be_edited(db: psycopg.Connection, make_user):
    """FINAL §12: professional recommendation content is not directly editable."""
    user_id = make_user()
    plan_id = _plan(db, user_id, _plant(db, user_id))
    v = _version(db, plan_id, 1)

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute(
            "update public.care_plan_versions set professional_recommendations = %s::jsonb "
            "where id = %s",
            ('{"light": "tampered"}', v),
        )


def test_operational_preferences_remain_editable(db: psycopg.Connection, make_user):
    """The user may change frequency and preferred time; that is the whole point of
    an operational adjustment."""
    user_id = make_user()
    plan_id = _plan(db, user_id, _plant(db, user_id))
    v = _version(db, plan_id, 1)

    db.execute(
        "update public.care_plan_versions set operational_preferences = %s::jsonb where id = %s",
        ('{"preferred_time_local": "07:00"}', v),
    )


def test_source_type_is_immutable(db: psycopg.Connection, make_user):
    """source_type is the single provenance trail; rewriting it would erase why a
    version exists."""
    user_id = make_user()
    plan_id = _plan(db, user_id, _plant(db, user_id))
    v = _version(db, plan_id, 1)

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute(
            "update public.care_plan_versions set source_type = 'HEALTH_DRIVEN' where id = %s",
            (v,),
        )


def test_later_versions_require_a_change_summary(db: psycopg.Connection, make_user):
    user_id = make_user()
    plan_id = _plan(db, user_id, _plant(db, user_id))
    _version(db, plan_id, 1)

    with pytest.raises(psycopg.errors.CheckViolation):
        _version(db, plan_id, 2, source="OPERATIONAL_ADJUSTMENT")


# --- A7: preferred_weekday --------------------------------------------------


@pytest.mark.parametrize("interval_days", [7, 14, 28])
def test_weekday_allowed_on_weekly_multiples(db: psycopg.Connection, make_user, interval_days: int):
    user_id = make_user()
    plan_id = _plan(db, user_id, _plant(db, user_id))
    v = _version(db, plan_id, 1)

    _rule(db, v, interval_days=interval_days, weekday="FRIDAY")


@pytest.mark.parametrize("interval_days", [1, 5, 10, 30])
def test_weekday_rejected_on_non_weekly_intervals(
    db: psycopg.Connection, make_user, interval_days: int
):
    """A7 as a database guarantee: anchoring a weekday to a 30-day interval is
    incoherent, so it is rejected rather than silently ignored by the scheduler."""
    user_id = make_user()
    plan_id = _plan(db, user_id, _plant(db, user_id))
    v = _version(db, plan_id, 1)

    with pytest.raises(psycopg.errors.CheckViolation):
        _rule(db, v, interval_days=interval_days, weekday="FRIDAY")


@pytest.mark.parametrize("interval_days", [0, -1, 400])
def test_insane_intervals_are_rejected(db: psycopg.Connection, make_user, interval_days: int):
    user_id = make_user()
    plan_id = _plan(db, user_id, _plant(db, user_id))
    v = _version(db, plan_id, 1)

    with pytest.raises(psycopg.errors.CheckViolation):
        _rule(db, v, interval_days=interval_days)


# --- task materialisation ---------------------------------------------------


def test_only_one_pending_task_per_rule(db: psycopg.Connection, make_user):
    """The materialisation invariant: generate near-term work only, never a
    thousand future rows."""
    user_id = make_user()
    plant_id = _plant(db, user_id)
    rule_id = _rule(db, _version(db, _plan(db, user_id, plant_id), 1))
    _task(db, user_id, plant_id, rule_id)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _task(db, user_id, plant_id, rule_id)


def test_an_overdue_task_does_not_block_the_next_recurrence(db: psycopg.Connection, make_user):
    """FINAL §13: a missed task becomes overdue, and the next recurrence remains
    scheduled."""
    user_id = make_user()
    plant_id = _plant(db, user_id)
    rule_id = _rule(db, _version(db, _plan(db, user_id, plant_id), 1))
    first = _task(db, user_id, plant_id, rule_id)

    db.execute(
        "update public.care_tasks set status = 'OVERDUE', overdue_since = now() where id = %s",
        (first,),
    )
    second = _task(db, user_id, plant_id, rule_id)

    assert second != first


def test_overdue_status_requires_a_timestamp(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    rule_id = _rule(db, _version(db, _plan(db, user_id, plant_id), 1))
    task_id = _task(db, user_id, plant_id, rule_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("update public.care_tasks set status = 'OVERDUE' where id = %s", (task_id,))


def test_done_status_requires_a_completion_timestamp(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    rule_id = _rule(db, _version(db, _plan(db, user_id, plant_id), 1))
    task_id = _task(db, user_id, plant_id, rule_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("update public.care_tasks set status = 'DONE' where id = %s", (task_id,))


# --- care events ------------------------------------------------------------


def test_a_task_cannot_be_completed_twice(db: psycopg.Connection, make_user):
    """API_CONTRACTS: duplicate action events are rejected. The 409 is backed by an
    index rather than a read-then-write race in application code."""
    user_id = make_user()
    plant_id = _plant(db, user_id)
    rule_id = _rule(db, _version(db, _plan(db, user_id, plant_id), 1))
    task_id = _task(db, user_id, plant_id, rule_id)

    db.execute(
        "insert into public.care_events (user_id, plant_id, care_task_id, event_type) "
        "values (%s, %s, %s, 'DONE')",
        (user_id, plant_id, task_id),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into public.care_events (user_id, plant_id, care_task_id, event_type) "
            "values (%s, %s, %s, 'DONE')",
            (user_id, plant_id, task_id),
        )


def test_a_task_cannot_be_done_and_skipped(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    rule_id = _rule(db, _version(db, _plan(db, user_id, plant_id), 1))
    task_id = _task(db, user_id, plant_id, rule_id)

    db.execute(
        "insert into public.care_events (user_id, plant_id, care_task_id, event_type) "
        "values (%s, %s, %s, 'DONE')",
        (user_id, plant_id, task_id),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into public.care_events (user_id, plant_id, care_task_id, event_type) "
            "values (%s, %s, %s, 'SKIPPED')",
            (user_id, plant_id, task_id),
        )


def test_a_missed_event_does_not_consume_the_action_slot(db: psycopg.Connection, make_user):
    """MISSED is written by the scheduler sweep, not by the user, so it must not
    collide with a later corrective DONE."""
    user_id = make_user()
    plant_id = _plant(db, user_id)
    rule_id = _rule(db, _version(db, _plan(db, user_id, plant_id), 1))
    task_id = _task(db, user_id, plant_id, rule_id)

    db.execute(
        "insert into public.care_events (user_id, plant_id, care_task_id, event_type) "
        "values (%s, %s, %s, 'MISSED')",
        (user_id, plant_id, task_id),
    )
    db.execute(
        "insert into public.care_events (user_id, plant_id, care_task_id, event_type) "
        "values (%s, %s, %s, 'DONE')",
        (user_id, plant_id, task_id),
    )


def test_care_events_are_immutable(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    event_id = db.execute(
        "insert into public.care_events (user_id, plant_id, event_type) "
        "values (%s, %s, 'DONE') returning id",
        (user_id, plant_id),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update public.care_events set note = 'changed' where id = %s", (event_id,))


def test_a_correction_must_reference_what_it_corrects(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into public.care_events (user_id, plant_id, event_type) "
            "values (%s, %s, 'CORRECTED')",
            (user_id, plant_id),
        )


def test_a_non_correction_cannot_reference_another_event(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    original = db.execute(
        "insert into public.care_events (user_id, plant_id, event_type) "
        "values (%s, %s, 'DONE') returning id",
        (user_id, plant_id),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into public.care_events "
            "(user_id, plant_id, event_type, correction_of_event_id) "
            "values (%s, %s, 'DONE', %s)",
            (user_id, plant_id, original),
        )


def test_user_cannot_see_another_users_tasks(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_postgres(db)
    bob_plant = _plant(db, bob)
    rule_id = _rule(db, _version(db, _plan(db, bob, bob_plant), 1))
    _task(db, bob, bob_plant, rule_id)

    as_user(db, alice)
    assert db.execute("select id from public.care_tasks").fetchall() == []


# =============================================================================
# HEALTH
# =============================================================================


def test_unknown_assessment_requires_a_reason(db: psycopg.Connection, make_user):
    """FINAL §16: save UNKNOWN *with the reason*. An unexplained UNKNOWN is
    indistinguishable from a bug."""
    user_id = make_user()
    plant_id = _plant(db, user_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        _assessment(db, user_id, plant_id, status="UNKNOWN")


def test_unknown_assessment_with_a_reason_is_accepted(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)

    _assessment(db, user_id, plant_id, status="UNKNOWN", reason="התמונות מטושטשות")


def test_unknown_assessment_cannot_claim_confidence(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    assessment = _assessment(db, user_id, plant_id, status="UNKNOWN", reason="לא ברור")

    # Immutability means this must fail on the trigger, not the check — either way
    # the contradiction cannot be persisted.
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute(
            "update public.health_assessments set confidence_level = 'HIGH' where id = %s",
            (assessment,),
        )


def test_assessments_are_immutable(db: psycopg.Connection, make_user):
    """FINAL §16: previous assessments remain unchanged."""
    user_id = make_user()
    plant_id = _plant(db, user_id)
    assessment = _assessment(db, user_id, plant_id)

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute(
            "update public.health_assessments set overall_status = 'CRITICAL' where id = %s",
            (assessment,),
        )


def test_findings_are_immutable(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    assessment = _assessment(db, user_id, plant_id)
    issue = db.execute(
        "insert into public.health_issues (health_assessment_id, issue_name) "
        "values (%s, 'השקיית יתר אפשרית') returning id",
        (assessment,),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update public.health_issues set severity = 5 where id = %s", (issue,))


def test_health_sources_follow_the_same_provenance_rule(db: psycopg.Connection, make_user):
    """The table this migration adds to close a spec gap."""
    user_id = make_user()
    plant_id = _plant(db, user_id)
    assessment = _assessment(db, user_id, plant_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into public.health_assessment_sources "
            "(health_assessment_id, source_class, title) values (%s, 'APPROVED', 'no url')",
            (assessment,),
        )


def _add_images(db, user_id, plant_id, assessment, count: int) -> None:
    for i in range(count):
        image_id = db.execute(
            """
            insert into public.plant_images
              (user_id, plant_id, storage_path_original, mime_type, size_bytes, context_type)
            values (%s, %s, %s, 'image/jpeg', 1024, 'health') returning id
            """,
            (user_id, plant_id, f"{user_id}/{plant_id}/health/{i}.jpg"),
        ).fetchone()[0]
        db.execute(
            "insert into public.health_assessment_images "
            "(health_assessment_id, plant_image_id, display_order) values (%s, %s, %s)",
            (assessment, image_id, i + 1),
        )


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_between_one_and_four_images_is_accepted(db: psycopg.Connection, make_user, count: int):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    assessment = _assessment(db, user_id, plant_id)

    _add_images(db, user_id, plant_id, assessment, count)
    db.execute("set constraints all immediate")


def test_zero_images_is_rejected(db: psycopg.Connection, make_user):
    """FINAL §16 requires at least one image. The rule spans rows, so it is a
    deferred constraint trigger checked when the set is complete.

    No `set constraints all immediate` before the delete: that switches the mode
    for the remainder of the transaction, which would fire the check inside the
    DELETE rather than at the point we choose to force it.
    """
    user_id = make_user()
    plant_id = _plant(db, user_id)
    assessment = _assessment(db, user_id, plant_id)
    _add_images(db, user_id, plant_id, assessment, 1)

    db.execute(
        "delete from public.health_assessment_images where health_assessment_id = %s",
        (assessment,),
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("set constraints all immediate")


def test_an_assessment_with_no_images_at_all_is_rejected(db: psycopg.Connection, make_user):
    """The likelier bug in practice: persisting the assessment and forgetting to
    attach the images it was based on.

    The image-side guard cannot catch this — it is row-level and never fires when
    no image row is written — which is why migration 0010 adds the mirror trigger
    on health_assessments.
    """
    user_id = make_user()
    plant_id = _plant(db, user_id)
    _assessment(db, user_id, plant_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("set constraints all immediate")


def test_five_images_is_rejected(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    assessment = _assessment(db, user_id, plant_id)

    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.UniqueViolation)):
        _add_images(db, user_id, plant_id, assessment, 5)
        db.execute("set constraints all immediate")


def test_user_cannot_see_another_users_assessment(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_postgres(db)
    bob_plant = _plant(db, bob)
    _assessment(db, bob, bob_plant)

    as_user(db, alice)
    assert db.execute("select id from public.health_assessments").fetchall() == []


# =============================================================================
# SYSTEM / AI INFRASTRUCTURE
# =============================================================================


def test_idempotency_key_is_unique_per_user(db: psycopg.Connection, make_user):
    user_id = make_user()
    db.execute(
        "insert into public.agent_requests (user_id, agent_type, idempotency_key) "
        "values (%s, 'IDENTIFICATION', 'abc')",
        (user_id,),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into public.agent_requests (user_id, agent_type, idempotency_key) "
            "values (%s, 'IDENTIFICATION', 'abc')",
            (user_id,),
        )


def test_two_users_may_share_an_idempotency_key(db: psycopg.Connection, make_user):
    """Scoping per user matters: keys are client-generated and will collide."""
    alice = make_user()
    bob = make_user()

    for uid in (alice, bob):
        db.execute(
            "insert into public.agent_requests (user_id, agent_type, idempotency_key) "
            "values (%s, 'HEALTH', 'same-key')",
            (uid,),
        )


def test_retry_budget_is_capped_at_three_attempts(db: psycopg.Connection, make_user):
    """FINAL §23 caps structured-output retries at 2, so at most three attempts.
    A fourth means the ceiling was bypassed."""
    user_id = make_user()
    request_id = db.execute(
        "insert into public.agent_requests (user_id, agent_type) values (%s, 'CARE') returning id",
        (user_id,),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            """
            insert into public.agent_executions
              (agent_request_id, agent_type, model, prompt_version, status, attempt)
            values (%s, 'CARE', 'claude-opus-5', 'care.v001', 'FAILED', 4)
            """,
            (request_id,),
        )


def test_agent_executions_have_no_chain_of_thought_column(db: psycopg.Connection):
    """FINAL §23: chain-of-thought is never stored. Structural, not conventional."""
    columns = {
        r[0]
        for r in db.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = 'agent_executions'"
        ).fetchall()
    }
    forbidden = {"chain_of_thought", "reasoning", "thinking", "raw_prompt", "raw_response"}
    assert not (columns & forbidden), f"reasoning-shaped columns present: {columns & forbidden}"


def test_agent_executions_are_admin_only(db: psycopg.Connection, make_user):
    user_id = make_user()
    as_postgres(db)
    request_id = db.execute(
        "insert into public.agent_requests (user_id, agent_type) values (%s, 'CARE') returning id",
        (user_id,),
    ).fetchone()[0]
    db.execute(
        "insert into public.agent_executions "
        "(agent_request_id, agent_type, model, prompt_version, status) "
        "values (%s, 'CARE', 'claude-opus-5', 'care.v001', 'SUCCEEDED')",
        (request_id,),
    )

    as_user(db, user_id)
    assert db.execute("select id from public.agent_executions").fetchall() == [], (
        "cost and prompt-version detail must not be visible to end users"
    )


def test_request_owner_can_poll_their_own_status(db: psycopg.Connection, make_user):
    """The documented exception: minimal request status for the request owner."""
    user_id = make_user()
    as_postgres(db)
    db.execute(
        "insert into public.agent_requests (user_id, agent_type, status) "
        "values (%s, 'IDENTIFICATION', 'PROCESSING')",
        (user_id,),
    )

    as_user(db, user_id)
    rows = db.execute("select status from public.agent_requests").fetchall()
    assert rows == [("PROCESSING",)]


def test_duplicate_notification_is_impossible(db: psycopg.Connection, make_user):
    """A12: the unique dedupe_key fails on insert, before any provider call, so a
    re-run of the scheduler tick cannot double-send."""
    user_id = make_user()
    key = f"digest:{user_id}:2026-09-05"

    db.execute(
        "insert into public.notification_deliveries (user_id, dedupe_key) values (%s, %s)",
        (user_id, key),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into public.notification_deliveries (user_id, dedupe_key) values (%s, %s)",
            (user_id, key),
        )


def test_sent_delivery_requires_a_timestamp(db: psycopg.Connection, make_user):
    user_id = make_user()
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into public.notification_deliveries (user_id, dedupe_key, status) "
            "values (%s, %s, 'SENT')",
            (user_id, f"task:{uuid.uuid4()}:reminder"),
        )


def test_system_events_are_immutable(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    event_id = db.execute(
        "insert into public.system_events (user_id, plant_id, event_type) "
        "values (%s, %s, 'PLANT_CREATED') returning id",
        (user_id, plant_id),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute(
            "update public.system_events set event_type = 'PLANT_ARCHIVED' where id = %s",
            (event_id,),
        )


def test_user_cannot_log_an_event_against_another_users_plant(db: psycopg.Connection, make_user):
    alice = make_user()
    bob = make_user()
    as_postgres(db)
    bob_plant = _plant(db, bob)

    as_user(db, alice)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(
            "insert into public.system_events (user_id, plant_id, event_type) "
            "values (%s, %s, 'CUSTOM_NOTE')",
            (alice, bob_plant),
        )


def test_audit_log_cannot_be_rewritten_even_by_an_admin(db: psycopg.Connection, make_user):
    """An audit trail an admin can edit is not an audit trail."""
    admin = make_user()
    as_postgres(db)
    db.execute("update public.profiles set role = 'ADMIN' where id = %s", (admin,))
    entry = db.execute(
        "insert into public.admin_audit_log (admin_user_id, action) "
        "values (%s, 'knowledge.approve') returning id",
        (admin,),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update public.admin_audit_log set action = 'nothing' where id = %s", (entry,))
    with pytest.raises(psycopg.errors.InFailedSqlTransaction):
        db.execute("delete from public.admin_audit_log where id = %s", (entry,))


def test_user_cannot_read_the_audit_log(db: psycopg.Connection, make_user):
    admin = make_user()
    user_id = make_user()
    as_postgres(db)
    db.execute(
        "insert into public.admin_audit_log (admin_user_id, action) values (%s, 'x')", (admin,)
    )

    as_user(db, user_id)
    assert db.execute("select id from public.admin_audit_log").fetchall() == []


# --- forward foreign keys now closed ------------------------------------------


def test_identification_links_to_its_agent_request(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)
    request_id = db.execute(
        "insert into public.agent_requests (user_id, plant_id, agent_type) "
        "values (%s, %s, 'IDENTIFICATION') returning id",
        (user_id, plant_id),
    ).fetchone()[0]

    db.execute(
        "insert into public.identifications (user_id, plant_id, status, agent_request_id) "
        "values (%s, %s, 'SUCCESS', %s)",
        (user_id, plant_id, request_id),
    )


def test_a_dangling_agent_request_reference_is_rejected(db: psycopg.Connection, make_user):
    user_id = make_user()
    plant_id = _plant(db, user_id)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "insert into public.identifications (user_id, plant_id, status, agent_request_id) "
            "values (%s, %s, 'SUCCESS', %s)",
            (user_id, plant_id, uuid.uuid4()),
        )


# --- cross-cutting ------------------------------------------------------------


def test_every_public_table_has_rls(db: psycopg.Connection):
    rows = db.execute(
        """
        select c.relname from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity
        """
    ).fetchall()
    assert rows == [], f"tables without RLS: {[r[0] for r in rows]}"


def test_full_schema_is_present(db: psycopg.Connection):
    """Every table DATABASE_SCHEMA §27 names, plus the additions recorded there."""
    expected = {
        "profiles",
        "notification_preferences",
        "species",
        "plants",
        "plant_environments",
        "plant_images",
        "identifications",
        "identification_candidates",
        "knowledge_drafts",
        "knowledge_versions",
        "knowledge_sources",
        "approved_sources",
        "knowledge_reports",
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
        "agent_requests",
        "agent_executions",
        "notification_deliveries",
        "system_events",
        "admin_audit_log",
    }
    actual = {
        r[0]
        for r in db.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' and table_type = 'BASE TABLE'"
        ).fetchall()
    }
    assert expected - actual == set(), f"missing tables: {sorted(expected - actual)}"
