"""Health results on the plant dashboard (FINAL §16).

    "The Agent must not present definitive diagnosis."

That is a claim about what the user sees, so it is tested here as well as in the
schema. Observations and possible issues must read differently, every issue must
show the evidence behind it, and an UNKNOWN must not be dressed up as a finding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "plant_dashboard.py")

ASSESSMENT: dict[str, Any] = {
    "id": "aaaaaaaa-0000-0000-0000-000000000001",
    "plant_id": "plant-1",
    "overall_status": "NEEDS_ATTENTION",
    "confidence_level": "MEDIUM",
    "trend": "WORSENING",
    "requires_attention": True,
    "created_at": "2026-09-05T08:00:00Z",
    "observations": [{"observation_text": "שלושת העלים התחתונים מצהיבים מהקצה פנימה."}],
    "possible_issues": [
        {
            "issue_name": "ייתכן עודף השקיה",
            "evidence": "הצהבה בעלים התחתונים בלבד, מצע לח למראה.",
            "severity": 3,
        }
    ],
    "recommendations": [
        {
            "recommendation_text": "להאריך את מרווח ההשקיה בשלושה ימים.",
            "requires_care_plan_adjustment": True,
        }
    ],
    "sources": [],
}

UNKNOWN_ASSESSMENT: dict[str, Any] = {
    **ASSESSMENT,
    "overall_status": "UNKNOWN",
    "confidence_level": None,
    "trend": "UNABLE_TO_DETERMINE",
    "insufficient_information_reason": "התמונות מטושטשות. תמונה קרובה של עלה בודד תעזור.",
    "possible_issues": [],
    "recommendations": [],
}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(assessment: dict[str, Any] | None) -> AppTest:
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
                    "health": {
                        "current_status": (assessment or {}).get("overall_status", "UNKNOWN"),
                        "latest_assessment_id": (assessment or {}).get("id"),
                        "trend": (assessment or {}).get("trend"),
                    },
                    "upcoming_tasks": [],
                    "care_plan": None,
                    "open_proposals": 0,
                }
            if "/health-assessments/" in path:
                return assessment
            if path.endswith("/health-history"):
                return [assessment] if assessment else []
            return [] if path.endswith(("/proposals", "/history")) else {}

        monkeypatch.setattr(api_client, "get", fake_get)

        app = AppTest.from_file(PAGE, default_timeout=30)
        app.session_state["pc_selected_plant"] = "plant-1"
        return app

    return _build


def rendered(app: AppTest) -> str:
    parts: list[str] = []
    for collection in (app.markdown, app.caption, app.info, app.warning, app.subheader):
        parts.extend(str(e.value) for e in collection)
    return " ".join(parts)


def test_the_page_renders_an_assessment(page):
    app = page(ASSESSMENT)
    app.run()
    assert not app.exception, [str(e) for e in app.exception]


def test_observations_and_issues_are_shown_under_different_headings(page):
    """What was seen, and what it might mean. Presenting them together would let
    an inference borrow the reliability of an observation."""
    app = page(ASSESSMENT)
    app.run()

    text = rendered(app)
    assert "מה נראה בתמונות" in text
    assert "ממצאים אפשריים" in text


def test_an_issue_always_shows_the_evidence_it_rests_on(page):
    """A finding a user cannot check is one they can only believe or ignore."""
    app = page(ASSESSMENT)
    app.run()

    assert "על סמך" in rendered(app)
    assert "מצע לח" in rendered(app)


def test_findings_are_framed_as_possibilities_not_a_diagnosis(page):
    """FINAL §16 in the interface, not only in the prompt."""
    app = page(ASSESSMENT)
    app.run()

    text = rendered(app)
    assert "לא אבחנה" in text


def test_an_unknown_result_explains_itself_and_lists_nothing(page):
    """§16: an insufficient check is saved with its reason. It is an outcome, not
    an error, and it must not be dressed up as a finding."""
    app = page(UNKNOWN_ASSESSMENT)
    app.run()

    text = rendered(app)
    assert "תמונה קרובה של עלה בודד" in text
    assert "ממצאים אפשריים" not in text


def test_a_recommendation_that_wants_a_plan_change_offers_a_proposal(page):
    """The Health Agent cannot change the plan; this button raises a proposal the
    user approves, which is the only route from a finding to a schedule."""
    app = page(ASSESSMENT)
    app.run()

    labels = [b.label for b in app.button]
    assert "הצעת עדכון לתוכנית הטיפול" in labels


def test_no_such_button_when_nothing_asks_for_a_plan_change(page):
    plain = {
        **ASSESSMENT,
        "recommendations": [
            {"recommendation_text": "להמשיך כרגיל.", "requires_care_plan_adjustment": False}
        ],
    }
    app = page(plain)
    app.run()

    assert "הצעת עדכון לתוכנית הטיפול" not in [b.label for b in app.button]


def test_a_plant_with_no_assessment_says_so_plainly(page):
    app = page(None)
    app.run()

    assert "עדיין לא בוצעה בדיקת בריאות" in rendered(app)


def test_the_health_check_button_is_offered(page):
    app = page(None)
    app.run()

    assert "בדיקת בריאות" in [b.label for b in app.button]
