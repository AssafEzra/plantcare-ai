"""Every 202 is waited on, and every ending is shown (FINAL §24, §25).

Reported from real use: *"did a health check and nothing happened. didnt get
result or status update."* Two defects behind one sentence — the run failed for
its own reasons, and the page would not have said so either way. It fired the
202, promised "the results will appear here in a moment", and never polled again.
The care-plan proposal, which takes about 105 seconds, had the identical dead end.

`FINAL §25` asks for graceful and *visible* failure. A page that never looks at
the outcome cannot show it, so these tests assert on what the user is told rather
than on which request was sent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "plant_dashboard.py")

IMAGE = {
    "id": "aaaaaaaa-0000-0000-0000-000000000001",
    "url": "https://example.test/signed/full.jpg",
    "thumbnail_url": "https://example.test/signed/thumb.jpg",
    "context_type": "gallery",
    "is_main": True,
    "created_at": "2026-09-05T20:50:00Z",
}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    polls: list[str] = []

    def _build(*, outcome: str | None) -> AppTest:
        """`outcome` is what the agent request finally reports, or None to never
        finish — which is a run still going, not a failed one."""
        from app.ui.components import agent_progress
        from app.ui.state import api_client

        # The waiter sleeps between polls; a test that honoured that would take
        # as long as a real analysis.
        monkeypatch.setattr(agent_progress, "POLL_INTERVAL_SECONDS", 0)
        if outcome is None:
            monkeypatch.setattr(agent_progress, "await_request", lambda *a, **k: None)

        def fake_get(path: str, **kwargs: Any) -> Any:
            if path.endswith("/dashboard"):
                return {
                    "id": "plant-1",
                    "name": "קולאוס",
                    "status": "ACTIVE",
                    "created_at": "2026-09-05T20:47:00Z",
                    "species": None,
                    "pending_identification": None,
                    "main_image": IMAGE,
                    "gallery": [IMAGE],
                    "environment": None,
                    "health": {"current_status": "UNKNOWN"},
                    "upcoming_tasks": [],
                    "care_plan": None,
                    "open_proposals": 0,
                }
            if "/agent-requests/" in path:
                polls.append(path)
                return {"status": outcome, "stage": "COMPLETE", "output_summary": {}}
            return []

        monkeypatch.setattr(api_client, "get", fake_get)
        # `agent_progress` binds `get` at import time and is cached in
        # `sys.modules`, so patching only the api_client module would leave the
        # waiter talking to the real API.
        monkeypatch.setattr(agent_progress, "get", fake_get)
        monkeypatch.setattr(
            api_client,
            "post",
            lambda path, **kwargs: {"agent_request_id": "req-1", "status": "QUEUED"},
        )

        app = AppTest.from_file(PAGE, default_timeout=30)
        app.session_state["pc_selected_plant"] = "plant-1"
        return app

    _build.polls = polls  # type: ignore[attr-defined]
    return _build


def messages(app: AppTest) -> str:
    parts: list[str] = []
    for collection in (app.info, app.warning, app.success, app.error, app.markdown):
        parts.extend(str(element.value) for element in collection)
    return " ".join(parts)


def start_health_check(app: AppTest) -> AppTest:
    next(button for button in app.button if button.label == "בדיקת בריאות").click().run()
    # The submit button is disabled until an image is chosen, which is the
    # product rule: a health check with no photograph has nothing to assess.
    app.multiselect("pd_health_images").select(IMAGE["id"]).run()
    next(button for button in app.button if button.label == "שליחה לבדיקה").click().run()
    return app


def test_a_health_check_is_polled_to_completion(page):
    """The regression: the 202 was fired and never followed up."""
    app = page(outcome="SUCCEEDED")
    app.run()
    start_health_check(app)

    assert page.polls, "the health check was started and never polled"  # type: ignore[attr-defined]


def test_a_finished_health_check_says_so(page):
    app = page(outcome="SUCCEEDED")
    app.run()
    start_health_check(app)

    assert "הבדיקה הושלמה" in messages(app)


def test_a_failed_health_check_says_so_too(page):
    """FINAL §25. Silence after a failure is the worst of the three outcomes: the
    user cannot tell it apart from still waiting, so they wait forever."""
    app = page(outcome="FAILED")
    app.run()
    start_health_check(app)

    text = messages(app)
    assert "לא הושלמה" in text
    assert "הבדיקה הושלמה" not in text


def test_a_slow_health_check_is_not_reported_as_a_failure(page):
    """A run that has not finished has not failed. Care took 105 seconds live and
    Knowledge minutes; calling either of those broken would be wrong and would
    teach the user to distrust a working product."""
    app = page(outcome=None)
    app.run()
    start_health_check(app)

    text = messages(app)
    assert "נמשכת" in text
    assert "לא הושלמה" not in text


def test_a_queued_care_proposal_is_waited_on(page):
    """Same dead end, same fix: the empty state invited the user to press a button
    and then showed them the same empty state."""
    app = page(outcome="SUCCEEDED")
    app.run()

    next(button for button in app.button if button.label == "הכנת תוכנית").click().run()

    assert page.polls, "the proposal was queued and never polled"  # type: ignore[attr-defined]
    assert "ממתינה לאישור" in messages(app)
