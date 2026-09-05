"""Growing conditions can be entered and changed (FINAL §18).

Reported from real use: *"i couldnt add or edit תנאי הגידול"*. `PUT
/v1/plants/{id}/environment` shipped in PR 11 and no screen ever called it — the
section displayed whatever was stored and, when nothing was, said so and stopped.

It also carried a caption promising that updating the conditions triggers a review
of the care plan. Nothing could update them, and nothing reviewed anything. A
promise a page makes is part of its behaviour, so it is asserted here too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "plant_dashboard.py")

PLAN = {
    "id": "bbbbbbbb-0000-0000-0000-000000000001",
    "version_number": 1,
    "status": "ACTIVE",
    "professional_recommendations": {"summary": "השקיה מתונה."},
    "operational_preferences": {},
    "source_type": "INITIAL_PLAN",
    "created_at": "2026-09-05T20:00:00Z",
    "rules": [],
}

STORED = {
    "plant_id": "plant-1",
    "location_type": "INDOOR",
    "light_level": "BRIGHT",
    "light_direction": "NORTH",
    "temperature_c": 22.0,
    "humidity_percent": 45.0,
    "room": "הסלון",
    "notes": None,
}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    sent: list[tuple[str, dict | None]] = []

    def _build(*, environment: dict | None, plan: dict | None = None) -> AppTest:
        from app.ui.components import agent_progress
        from app.ui.state import api_client

        monkeypatch.setattr(agent_progress, "POLL_INTERVAL_SECONDS", 0)

        def fake_get(path: str, **kwargs: Any) -> Any:
            if path.endswith("/dashboard"):
                return {
                    "id": "plant-1",
                    "name": "קולאוס",
                    "status": "ACTIVE",
                    "created_at": "2026-09-05T20:47:00Z",
                    "species": None,
                    "pending_identification": None,
                    "main_image": None,
                    "gallery": [],
                    "environment": environment,
                    "health": {"current_status": "UNKNOWN"},
                    "upcoming_tasks": [],
                    "care_plan": plan,
                    "open_proposals": 0,
                }
            if "/agent-requests/" in path:
                return {"status": "SUCCEEDED", "stage": "COMPLETE", "output_summary": {}}
            return []

        def record(path: str, *, json: dict | None = None, **kwargs: Any) -> Any:
            sent.append((path, json))
            return {"agent_request_id": "req-1", "status": "QUEUED"}

        monkeypatch.setattr(api_client, "get", fake_get)
        monkeypatch.setattr(agent_progress, "get", fake_get)
        monkeypatch.setattr(api_client, "post", record)
        monkeypatch.setattr(api_client, "put", record)

        app = AppTest.from_file(PAGE, default_timeout=30)
        app.session_state["pc_selected_plant"] = "plant-1"
        return app

    _build.sent = sent  # type: ignore[attr-defined]
    return _build


def submit(app: AppTest) -> AppTest:
    next(
        button for button in app.button if getattr(button, "label", "") == "שמירת תנאי הגידול"
    ).click().run()
    return app


def test_the_conditions_can_be_entered_when_there_are_none(page):
    """The regression. An empty section that only says it is empty is a dead end."""
    app = page(environment=None)
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    app.selectbox("pd_env_location").select("בתוך הבית").run()
    submit(app)

    path, payload = page.sent[0]  # type: ignore[attr-defined]
    assert path.endswith("/v1/plants/plant-1/environment")
    assert payload["location_type"] == "INDOOR"


def test_stored_conditions_are_shown_in_hebrew(page):
    """`INDOOR` is a database value, not something to put in front of a reader."""
    app = page(environment=STORED)
    app.run()

    text = " ".join(str(element.value) for element in app.markdown)
    assert "בתוך הבית" in text
    assert "INDOOR" not in text


def test_the_form_opens_on_what_is_already_stored(page):
    """An edit form that starts blank is a form that silently erases the answer
    the user gave last time."""
    app = page(environment=STORED)
    app.run()

    assert app.selectbox("pd_env_light").value == "BRIGHT"
    assert app.text_input("pd_env_room").value == "הסלון"


def test_a_field_can_be_cleared(page):
    """ "I no longer know the humidity" is a real edit. The endpoint replaces the
    row, so an unset field has to travel as null rather than be omitted."""
    app = page(environment=STORED)
    app.run()

    app.selectbox("pd_env_direction").select("—").run()
    submit(app)

    _, payload = page.sent[0]  # type: ignore[attr-defined]
    assert payload["light_direction"] is None


def test_saving_asks_for_the_care_plan_to_be_reviewed(page):
    """FINAL §12, and the promise the caption has been making since PR 20: a
    change to the environment produces a proposal, never a silent rewrite."""
    app = page(environment=STORED, plan=PLAN)
    app.run()

    app.number_input("pd_env_temperature").set_value(30.0).run()
    submit(app)

    paths = [path for path, _ in page.sent]  # type: ignore[attr-defined]
    assert any(path.endswith("/care-plan/proposals") for path in paths)
    reason = next(body for path, body in page.sent if path.endswith("/proposals"))  # type: ignore[attr-defined]
    assert reason["reason"] == "ENVIRONMENT_CHANGE"


def test_no_review_is_requested_when_there_is_no_plan_yet(page):
    """Queueing one here would put a second, competing INITIAL_PLAN in front of a
    user who has not been offered the first one."""
    app = page(environment=None, plan=None)
    app.run()

    app.text_input("pd_env_room").set_value("המטבח").run()
    submit(app)

    paths = [path for path, _ in page.sent]  # type: ignore[attr-defined]
    assert not any(path.endswith("/proposals") for path in paths)
