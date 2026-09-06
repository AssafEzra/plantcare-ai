"""Approving a plan, in a window, knowing what changes (PR 33, FINAL §12).

Reported: the approve/reject decision sat inline on a scrolling page beside the
health card and the timeline, and showed the new plan in full without ever saying
what was different from the one already running.

Two things these defend. The decision has its own window. And the diff above the
plan is the *what* under the agent's *why* — in that order, because numbers
arriving before the reason have nothing to explain them.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

CURRENT = [
    {
        "action_type": "WATERING",
        "interval_days": 7,
        "preferred_time_local": "08:00:00",
        "preferred_weekday": None,
        "is_active": True,
    },
    {
        "action_type": "ROTATING",
        "interval_days": 7,
        "preferred_time_local": "09:00:00",
        "preferred_weekday": None,
        "is_active": True,
    },
]

PROPOSED = [
    {
        "id": "r1",
        "action_type": "WATERING",
        "interval_days": 5,
        "preferred_time_local": "08:00:00",
        "preferred_weekday": None,
        "instructions": None,
        "is_active": True,
    },
    {
        "id": "r2",
        "action_type": "FERTILIZING",
        "interval_days": 14,
        "preferred_time_local": "08:30:00",
        "preferred_weekday": None,
        "instructions": None,
        "is_active": True,
    },
]


def render(proposal, decided):
    import streamlit as st

    from app.ui.components.proposal_dialog import open_dialog, proposal_dialog

    open_dialog(str(proposal["id"]))
    proposal_dialog(
        [proposal],
        on_approve=lambda v: decided.append(("approve", v)),
        on_reject=lambda v: decided.append(("reject", v)),
    )
    st.session_state["decided"] = list(decided)


def proposal(**overrides):
    base = {
        "id": "v2",
        "care_plan_id": "p1",
        "version_number": 2,
        "status": "PROPOSED",
        "source_type": "HEALTH_DRIVEN",
        "change_summary": "העלים מראים סימני יובש, לכן צופפנו את ההשקיה.",
        "professional_recommendations": {"summary": "השקיה תכופה יותר בקיץ."},
        "operational_preferences": {},
        "created_at": "2026-09-06T08:00:00Z",
        "rules": PROPOSED,
        "current_rules": CURRENT,
        "knowledge_review": "reviewed",
    }
    return {**base, **overrides}


@pytest.fixture
def dialog(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(card=None) -> AppTest:
        decided: list = []
        app = AppTest.from_function(
            render, kwargs={"proposal": card or proposal(), "decided": decided}, default_timeout=30
        )
        app.run()
        assert not app.exception, [str(e) for e in app.exception]
        app.decided = decided  # type: ignore[attr-defined]
        return app

    return _build


def in_order(app: AppTest) -> list[str]:
    """Everything the dialog draws, in the order it draws it.

    Walked from the dialog block rather than collected by element type. Gathering
    all the markdown and then all the info would make an ordering assertion a test
    of the helper rather than of the screen — which is what the first version of
    this file accidentally did, and it passed.

    The dialog's contents also do not live under `app.main`; `st.dialog` renders
    into its own block beside it.
    """
    found: list[str] = []

    def walk(node) -> None:
        for child in getattr(node, "children", {}).values():
            value = getattr(child, "value", None)
            if value is not None:
                found.append(str(value))
            walk(child)

    for block in app.get("dialog"):
        walk(block)
    return found


def rendered(app: AppTest) -> str:
    parts = []
    for collection in (app.markdown, app.caption, app.info, app.warning, app.error, app.subheader):
        parts.extend(str(e.value) for e in collection)
    return " ".join(parts)


def test_the_agents_reason_comes_before_the_numbers(dialog):
    """The sentence is the *why* and the diff is the *what*. Reversed, the numbers
    arrive with nothing to explain them."""
    app = dialog()

    drawn = " || ".join(in_order(app))
    assert "צופפנו את ההשקיה" in drawn, drawn
    assert drawn.index("צופפנו את ההשקיה") < drawn.index("מה משתנה"), drawn


def test_a_changed_interval_is_spelled_out(dialog):
    """The whole point: the user should not have to read two schedules side by
    side to notice that watering moved from seven days to five."""
    app = dialog()

    text = rendered(app)
    assert "השקיה" in text
    assert "כל 7 ימים ← כל 5 ימים" in text


def test_an_added_rule_says_it_is_new(dialog):
    app = dialog()

    assert "דישון" in rendered(app)
    assert "נוסף" in rendered(app)


def test_a_dropped_rule_says_it_is_going(dialog):
    """The easiest change to miss, and the one most worth knowing: a reminder is
    about to stop arriving."""
    app = dialog()

    text = rendered(app)
    assert "סיבוב" in text
    assert "הוסר" in text


def test_a_first_plan_shows_no_diff(dialog):
    """Nothing to compare against. A diff listing every rule as "added" would be
    noise dressed as information."""
    app = dialog(proposal(current_rules=[], source_type="INITIAL_PLAN", change_summary=None))

    assert "מה משתנה" not in rendered(app)


def test_a_proposal_that_changes_no_rule_says_so(dialog):
    """Otherwise a user approves expecting a new schedule and discovers by
    watching for one that never changes."""
    app = dialog(proposal(rules=CURRENT, current_rules=CURRENT))

    assert "לוח הזמנים נשאר כפי שהוא" in rendered(app)


def test_unreviewed_knowledge_is_flagged_on_the_plan(dialog):
    """PR 33: a plan may rest on research nobody has approved. The plan inherits
    the uncertainty, so the dialog carries the badge too."""
    app = dialog(proposal(knowledge_review="pending"))

    assert "ממתין לאישור מומחה" in " ".join(str(w.value) for w in app.warning)


def test_a_rejected_source_is_stated_plainly(dialog):
    app = dialog(proposal(knowledge_review="rejected"))

    assert "לא אושר" in " ".join(str(e.value) for e in app.error)


def test_both_decisions_are_offered_and_reported(dialog):
    app = dialog()

    labels = [b.label for b in app.button]
    assert "אישור התוכנית" in labels
    assert "דחייה" in labels

    next(b for b in app.button if b.label == "אישור התוכנית").click().run()
    assert app.session_state["decided"] == [("approve", "v2")]
