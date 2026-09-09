"""What the Add Plant flow says when an identification does not produce a species.

Reported from real use: *"just made identification attempt, the agent failed yet I
got 'unable to identify' notification."* Google had refused the call on quota - the
model never looked at anything - and the screen told the user their photographs
were inadequate and asked for better ones, which could not have helped. The agent
had already recorded `request_more_photos = false` to say exactly that.

Three states, three different things to say, and the tests are here rather than
against the agent because the defect was entirely in what the user was told:

* the vendor was unavailable -> the service is busy, try again shortly;
* something else failed     -> the run did not finish, try again;
* the model looked and could not tell -> its own reason, and only *then* a request
  for better photographs.

Nothing in the first two may mention photographs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "add_plant.py")

IDENTIFICATION_ID = "cccccccc-0000-0000-0000-000000000001"


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(*, request_state: dict | None = None, identification: dict | None = None) -> AppTest:
        from app.ui.components import agent_progress
        from app.ui.state import api_client

        monkeypatch.setattr(agent_progress, "POLL_INTERVAL_SECONDS", 0)

        def fake_get(path: str, **kwargs: Any) -> Any:
            if "/agent-requests/" in path:
                return request_state
            if "/identifications/" in path:
                return identification
            return []

        monkeypatch.setattr(api_client, "get", fake_get)
        # `agent_progress` binds `get` at import time and is cached in
        # `sys.modules`, so patching only `api_client` would leave the waiter
        # talking to the real API.
        monkeypatch.setattr(agent_progress, "get", fake_get)

        app = AppTest.from_file(PAGE, default_timeout=30)
        app.session_state["add_plant_step"] = "confirm" if identification else "identifying"
        app.session_state["add_plant_request_id"] = "req-1"
        app.session_state["add_plant_identification_id"] = IDENTIFICATION_ID
        return app

    return _build


def messages(app: AppTest) -> str:
    parts: list[str] = []
    for collection in (app.warning, app.error, app.info, app.caption, app.markdown):
        parts.extend(str(element.value) for element in collection)
    return " ".join(parts)


def alerts(app: AppTest) -> str:
    """Only what the page *tells* the user, not the progress checklist.

    The checklist's first step is literally "התמונות התקבלו", which is true and
    unrelated - the claim under test is about the message that explains the
    outcome.
    """
    parts: list[str] = []
    for collection in (app.warning, app.error, app.info):
        parts.extend(str(element.value) for element in collection)
    return " ".join(parts)


def labels(app: AppTest) -> list[str]:
    return [button.label for button in app.button]


def failed(error_code: str | None) -> dict:
    return {"status": "FAILED", "stage": "COMPLETE", "error_code": error_code}


# --- step 2: the run failed -----------------------------------------------------


def test_an_unavailable_service_says_it_is_busy(page):
    """The reported bug. A 429 is capacity, and "try again in a few minutes" is an
    instruction the user can act on."""
    app = page(request_state=failed("AGENT_UNAVAILABLE"))
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    assert "עמוס" in messages(app)


def test_a_failed_run_never_blames_the_photographs(page):
    """Neither failure looked at them, so neither may mention them."""
    for code in ("AGENT_UNAVAILABLE", "AGENT_SCHEMA_INVALID", None):
        app = page(request_state=failed(code))
        app.run()

        assert "תמונות" not in alerts(app), f"photographs blamed for {code}"


def test_any_other_failure_says_the_run_did_not_finish(page):
    app = page(request_state=failed("AGENT_SCHEMA_INVALID"))
    app.run()

    assert "הזיהוי לא הושלם" in messages(app)


def test_a_failure_offers_a_way_onwards(page):
    """FINAL §25 asks for graceful failure, and a dead end is not graceful. The
    plant was archived with the failure, so this starts a new one rather than
    retrying a row that no longer exists."""
    app = page(request_state=failed("AGENT_UNAVAILABLE"))
    app.run()

    assert "התחלה מחדש" in labels(app)


# --- step 3: the model answered, and could not tell -----------------------------


def test_the_models_own_reason_is_shown(page):
    """It was persisted from the start and exposed by nothing, so every
    unsuccessful identification got the same generic sentence."""
    app = page(
        identification={
            "id": IDENTIFICATION_ID,
            "status": "NEEDS_MORE_INFORMATION",
            "request_more_photos": True,
            "insufficient_reason": "העלים מטושטשים ולא נראה מבנה הגבעול.",
            "candidates": [],
        }
    )
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    assert "העלים מטושטשים" in messages(app)


def test_photographs_are_asked_for_only_when_they_would_help(page):
    """`request_more_photos` is the field whose entire job is to answer this."""
    app = page(
        identification={
            "id": IDENTIFICATION_ID,
            "status": "NEEDS_MORE_INFORMATION",
            "request_more_photos": True,
            "insufficient_reason": None,
            "candidates": [],
        }
    )
    app.run()

    assert "העלאת תמונות אחרות" in labels(app)


def test_photographs_are_not_asked_for_when_they_would_not(page):
    """A model that says more photographs will not help is not overruled by the
    screen. Sending the user back to the camera wastes their time and ends in the
    same place."""
    app = page(
        identification={
            "id": IDENTIFICATION_ID,
            "status": "NEEDS_MORE_INFORMATION",
            "request_more_photos": False,
            "insufficient_reason": "הצמח בתמונה אינו צמח בית מזוהה.",
            "candidates": [],
        }
    )
    app.run()

    assert "העלאת תמונות אחרות" not in labels(app)
    assert "התחלה מחדש" in labels(app)
