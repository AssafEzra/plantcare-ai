"""When was this check run? (PR 33)

Reported: the בריאות הצמח section showed תוצאות הבדיקה with no date anywhere, so a
result from three weeks ago was indistinguishable from one taken this morning. A
health assessment is a statement about a moment — "the lower leaves are
yellowing" means something different from a week ago than from an hour ago.

`created_at` has been on `AssessmentResponse` since PR 21. The screen simply never
read it: the same shape as every other defect this month.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV


def render(assessment, history):
    from app.ui.components.health_card import render_assessment, render_history

    render_assessment(assessment)
    render_history(history)


def assessment(**overrides):
    base = {
        "id": "a1",
        "overall_status": "HEALTHY",
        "trend": "STABLE",
        "created_at": "2026-09-04T06:30:00Z",
        "observations": [{"observation_text": "העלים ירוקים ומלאים."}],
        "possible_issues": [],
        "recommendations": [],
        "sources": [],
    }
    return {**base, **overrides}


@pytest.fixture
def card(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(current=None, history=None) -> AppTest:
        app = AppTest.from_function(
            render,
            kwargs={"assessment": current or assessment(), "history": history or []},
            default_timeout=30,
        )
        app.run()
        assert not app.exception, [str(e) for e in app.exception]
        return app

    return _build


def captions(app: AppTest) -> str:
    return " ".join(str(c.value) for c in app.caption)


def test_the_check_says_when_it_ran(card):
    app = card()

    assert "נבדק ב-" in captions(app)
    assert "04/09/2026" in captions(app)


def test_the_time_is_shown_too(card):
    """Two checks on the same day are ordinary — a user photographs a plant in the
    morning and again after moving it. A date alone cannot tell them apart."""
    app = card()

    assert "בשעה" in captions(app)


def test_it_is_rendered_in_the_readers_own_zone(card):
    """Stored in UTC, read by someone in Jerusalem. A check run at 23:30 local is
    21:30 the previous day in UTC, and showing the raw value would put it on the
    wrong date."""
    utc_evening = datetime(2026, 9, 4, 21, 30, tzinfo=UTC)
    app = card(assessment(created_at=utc_evening.isoformat()))

    local = utc_evening.astimezone()
    assert f"{local:%d/%m/%Y}" in captions(app)
    assert f"{local:%H:%M}" in captions(app)


def test_past_checks_are_dated_the_same_way(card):
    """The same helper in both places, so a check reads the same in the card and
    in the history beneath it."""
    older = assessment(id="a0", created_at=(datetime.now(UTC) - timedelta(days=9)).isoformat())
    app = card(history=[older])

    assert captions(app).count("נבדק ב-") >= 2


def test_a_missing_timestamp_is_not_an_error(card):
    """Defensive: an assessment with no `created_at` should render without one
    rather than take the whole card down."""
    app = card(assessment(created_at=None))

    assert not app.exception
