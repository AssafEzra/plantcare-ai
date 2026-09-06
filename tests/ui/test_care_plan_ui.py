"""The proposal card and plan view (FINAL §12).

The rule being defended is that a user can tell by *looking* which half of a plan
is theirs. Professional recommendations render as text with no control near them;
frequency sits in a number input. A test that only checked "the page renders"
would pass just as happily if an editable box appeared under the advice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "plant_dashboard.py")

RECOMMENDATIONS = {
    "summary": "הצמח נמצא בחדר מואר ודורש השקיה מתונה לאורך כל השנה.",
    "watering": "להשקות כשהמצע יבש לעומק שלושה סנטימטרים.",
    "light": "אור עקיף בהיר, כמטר מהחלון.",
    "warnings": ["הצמח רעיל לחתולים."],
}

RULES = [
    {
        "id": "aaaaaaaa-0000-0000-0000-000000000001",
        "action_type": "WATERING",
        "interval_days": 7,
        "preferred_time_local": "08:00:00",
        "preferred_weekday": None,
        "instructions": "להשקות עד שהמים מנקזים מלמטה.",
        "is_active": True,
    },
    {
        "id": "aaaaaaaa-0000-0000-0000-000000000002",
        "action_type": "FERTILIZING",
        "interval_days": 30,
        "preferred_time_local": "09:00:00",
        "preferred_weekday": None,
        "instructions": None,
        "is_active": True,
    },
]


def version(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "bbbbbbbb-0000-0000-0000-000000000001",
        "care_plan_id": "cccccccc-0000-0000-0000-000000000001",
        "version_number": 1,
        "status": "PROPOSED",
        "professional_recommendations": RECOMMENDATIONS,
        "operational_preferences": {"missing_context": ["גודל העציץ"]},
        "change_summary": None,
        "source_type": "INITIAL_PLAN",
        "created_at": "2026-09-05T08:00:00Z",
        "rules": RULES,
    }
    return {**base, **overrides}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    """The plant dashboard with its API stubbed.

    PR 20 moved the page onto a single `GET /v1/plants/{id}/dashboard` view model,
    so the stub serves that shape. The assertions below are unchanged: they are
    about what the card lets a user do, which is a product rule rather than a
    transport detail.
    """
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(*, proposals: list[dict] | None = None, plan: dict | None = None) -> AppTest:
        from app.ui.state import api_client

        def fake_get(path: str, **kwargs: Any) -> Any:
            if path.endswith("/dashboard"):
                return {
                    "id": "plant-1",
                    "name": "מונסטרה",
                    "status": "ACTIVE",
                    "created_at": "2026-09-01T08:00:00Z",
                    "species": None,
                    "main_image": None,
                    "gallery": [],
                    "environment": None,
                    "health": {"current_status": "HEALTHY"},
                    "upcoming_tasks": [],
                    "care_plan": plan,
                    "open_proposals": len(proposals or []),
                }
            if path.endswith("/care-plan/proposals"):
                return proposals or []
            if path.endswith("/history"):
                return []
            return {}

        monkeypatch.setattr(api_client, "get", fake_get)

        app = AppTest.from_file(PAGE, default_timeout=30)
        app.session_state["pc_selected_plant"] = "plant-1"
        return app

    return _build


def rendered(app: AppTest) -> str:
    parts: list[str] = []
    for collection in (app.markdown, app.caption, app.info, app.warning, app.subheader):
        parts.extend(str(e.value) for e in collection)
    parts.extend(e.label for e in app.expander)
    return " ".join(parts)


# --- the separation FINAL §12 depends on ---------------------------------------


def _render_proposal(card: dict) -> None:
    # No annotations, and every import inside: `AppTest.from_function` execs the
    # source in a bare module, so a name from this file would be undefined.
    from app.ui.components.proposal_dialog import open_dialog, proposal_dialog

    open_dialog(str(card["id"]))
    proposal_dialog([card], on_approve=lambda _: None, on_reject=lambda _: None)


def _render_active(card: dict) -> None:
    from app.ui.components.care_plan import active_plan_card

    active_plan_card(card, on_adjust=lambda *_: None)


def card_only(render, card: dict) -> AppTest:
    """Render one card and nothing else.

    These two assertions are about what sits *beside the advice*, and they used to
    be written as "the page has no inputs" — true when the plant dashboard had
    none anywhere. PR 31 added the growing-conditions form further down the same
    page and both went red, having caught nothing: the advice was still
    uneditable. Scoping them to the card says what they actually mean, and keeps
    them from failing again the next time an unrelated section grows a field.
    """
    app = AppTest.from_function(render, kwargs={"card": card}, default_timeout=30)
    app.run()
    assert not app.exception, [str(e) for e in app.exception]
    return app


def test_the_advice_has_no_input_beside_it():
    """A proposal offers two buttons and no fields.

    The user's decision here is yes or no. An input anywhere on this card would
    suggest the advice is theirs to rewrite, which §12 says it is not.
    """
    app = card_only(_render_proposal, version())

    assert app.number_input.values == []
    assert app.text_area.values == []


def test_the_active_plan_offers_frequency_and_nothing_else():
    """The editable half, and only it.

    One number input per rule — no field for the summary, the watering advice or
    the warnings.
    """
    app = card_only(_render_active, version(status="ACTIVE"))

    assert len(app.number_input) == len(RULES)
    labels = " ".join(n.label for n in app.number_input)
    assert "השקיה" in labels
    assert "השקיה" not in " ".join(t.label for t in app.text_input if "מה השתנה" not in t.label)


def test_the_recommendations_are_shown_in_full():
    """Inside the dialog since PR 33. The plant page shows a one-line summary and
    a button; the decision itself gets the screen to itself."""
    app = card_only(_render_proposal, version())

    assert RECOMMENDATIONS["summary"] in rendered(app)


def test_a_warning_from_the_recommendations_is_surfaced():
    """Toxicity is the case that matters: a user with a cat has to see it."""
    app = card_only(_render_proposal, version())

    assert "רעיל לחתולים" in " ".join(str(w.value) for w in app.warning)


# --- the schedule --------------------------------------------------------------


def test_intervals_are_written_the_way_a_person_says_them():
    """ "כל שבוע", not "כל 7 ימים". Correct either way; only one is memorable."""
    app = card_only(_render_proposal, version())

    text = rendered(app)
    assert "כל שבוע" in text
    assert "כל 7 ימים" not in text


def test_each_rule_shows_its_action_and_time():
    app = card_only(_render_proposal, version())

    text = rendered(app)
    assert "השקיה" in text
    assert "דישון" in text
    assert "08:00" in text


# --- A20 -----------------------------------------------------------------------


def test_missing_context_is_shown_as_information_not_a_question():
    """A20: the MVP cannot carry an answer back, so nothing here may look like a
    prompt. It renders as "what would have helped", with no input to answer it."""
    app = card_only(_render_proposal, version())

    text = rendered(app)
    assert "גודל העציץ" in text
    assert "?" not in text.split("גודל העציץ")[0][-60:]
    assert app.text_input.values == [] or all("גודל" not in t.label for t in app.text_input)


# --- states --------------------------------------------------------------------


def test_a_plant_with_no_plan_invites_one(page):
    """404 from `/care-plan` is an ordinary state — every plant looks like this
    between confirmation and the first approval — so it must not render as an
    error."""
    app = page(proposals=[], plan=None)
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    assert app.error.values == []
    assert "אין עדיין תוכנית טיפול" in rendered(app)


def test_an_open_proposal_is_shown_above_the_plan(page):
    app = page(proposals=[version(version_number=2, change_summary="עודכן לאחר שינוי סביבה")])
    app.run()

    text = rendered(app)
    assert "ממתין לאישור שלך" in text
    assert "עודכן לאחר שינוי סביבה" in text


def test_the_source_of_a_proposal_is_named(page):
    """A user should know why they are being asked, not just what for."""
    app = page(proposals=[version(source_type="HEALTH_DRIVEN")])
    app.run()

    assert "בעקבות בדיקת בריאות" in rendered(app)


# --- why the save button is disabled (PR 33) -----------------------------------
#
# Reported from real use: "manual changing in שינוי תדירות או שעה does nothing, it
# wont let you save changes". Both conditions were real - a version after the
# first cannot be written without a change summary, and an adjustment with no
# override is not an adjustment - but the screen enforced them in silence. A
# greyed-out primary button with no reason beside it is indistinguishable from a
# broken one.


def _adjust_form(card: dict) -> AppTest:
    def render(card):
        from app.ui.components.care_plan import active_plan_card

        active_plan_card(card, on_adjust=lambda *_: None)

    app = AppTest.from_function(render, kwargs={"card": card}, default_timeout=30)
    app.run()
    assert not app.exception, [str(e) for e in app.exception]
    return app


def _save(app: AppTest):
    return next(b for b in app.button if "שמירת השינוי" in b.label)


def _reasons(app: AppTest) -> str:
    return " ".join(str(c.value) for c in app.caption)


def test_the_field_is_marked_required():
    """The blocker was invisible in two ways at once: the button gave no reason,
    and the field it was waiting on did not look mandatory."""
    app = _adjust_form(version(status="ACTIVE"))

    assert any("חובה" in t.label for t in app.text_input)


def test_an_untouched_form_says_what_is_missing():
    app = _adjust_form(version(status="ACTIVE"))

    assert _save(app).disabled
    assert "תדירות" in _reasons(app)
    assert "לתאר" in _reasons(app)


def test_changing_a_number_leaves_only_the_description_outstanding():
    """The exact sequence that was reported: change 7 to 5, look for the save
    button, find it still greyed out with nothing explaining why."""
    app = _adjust_form(version(status="ACTIVE"))
    app.number_input[0].set_value(5).run()

    assert _save(app).disabled
    assert "יש לתאר את השינוי כדי לשמור." in _reasons(app)


def test_describing_the_change_alone_is_not_enough():
    """A description with no changed interval is not an adjustment, and the
    message says which half is missing rather than repeating itself."""
    app = _adjust_form(version(status="ACTIVE"))
    app.text_input[0].set_value("הדירה חמה יותר").run()

    assert _save(app).disabled
    assert "תדירות" in _reasons(app)
    assert "לתאר" not in _reasons(app)


def test_both_together_enable_it_and_the_reason_goes_away():
    app = _adjust_form(version(status="ACTIVE"))
    app.number_input[0].set_value(5).run()
    app.text_input[0].set_value("הדירה חמה יותר").run()

    assert not _save(app).disabled
    assert "כדי לשמור" not in _reasons(app)


def test_the_form_says_the_change_becomes_a_proposal():
    """The other half of "manual changing does nothing": an adjustment produces a
    proposal, and the schedule does not move until it is approved. The caption
    said the professional recommendations are preserved - true, and not the thing
    the user was about to be surprised by."""
    app = _adjust_form(version(status="ACTIVE"))

    caption = _reasons(app)
    assert "הצעה" in caption
    assert "לוח הזמנים" in caption
