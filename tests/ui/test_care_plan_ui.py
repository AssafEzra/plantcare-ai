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


def test_the_advice_has_no_input_beside_it(page):
    """A proposal offers two buttons and no fields.

    The user's decision here is yes or no. An input anywhere on this card would
    suggest the advice is theirs to rewrite, which §12 says it is not.
    """
    app = page(proposals=[version()])
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    assert app.number_input.values == []
    assert app.text_area.values == []


def test_the_active_plan_offers_frequency_and_nothing_else(page):
    """The editable half, and only it.

    One number input per rule — no field for the summary, the watering advice or
    the warnings.
    """
    app = page(plan=version(status="ACTIVE"))
    app.run()

    assert len(app.number_input) == len(RULES)
    labels = " ".join(n.label for n in app.number_input)
    assert "השקיה" in labels
    assert "השקיה" not in " ".join(t.label for t in app.text_input if "מה השתנה" not in t.label)


def test_the_recommendations_are_shown_in_full(page):
    app = page(proposals=[version()])
    app.run()

    assert RECOMMENDATIONS["summary"] in rendered(app)


def test_a_warning_from_the_recommendations_is_surfaced(page):
    """Toxicity is the case that matters: a user with a cat has to see it."""
    app = page(proposals=[version()])
    app.run()

    assert "רעיל לחתולים" in " ".join(str(w.value) for w in app.warning)


# --- the schedule --------------------------------------------------------------


def test_intervals_are_written_the_way_a_person_says_them(page):
    """ "כל שבוע", not "כל 7 ימים". Correct either way; only one is memorable."""
    app = page(proposals=[version()])
    app.run()

    text = rendered(app)
    assert "כל שבוע" in text
    assert "כל 7 ימים" not in text


def test_each_rule_shows_its_action_and_time(page):
    app = page(proposals=[version()])
    app.run()

    text = rendered(app)
    assert "השקיה" in text
    assert "דישון" in text
    assert "08:00" in text


# --- A20 -----------------------------------------------------------------------


def test_missing_context_is_shown_as_information_not_a_question(page):
    """A20: the MVP cannot carry an answer back, so nothing here may look like a
    prompt. It renders as "what would have helped", with no input to answer it."""
    app = page(proposals=[version()])
    app.run()

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
