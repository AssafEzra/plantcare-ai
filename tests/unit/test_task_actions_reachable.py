"""Done and Skip, from the two screens that offer them (PR 32).

Reported from real use: *"done/skip at tasks doesnt seem to work. it doesnt creat
a history log, and it still shows on screen after selecting"*.

The cause was a required request body. `complete_task` and `skip_task` declared
`payload: ActionRequest` with no default, so FastAPI demanded a JSON body; both
call sites send none, and every press returned

    422 {"code": "VALIDATION_FAILED", "fields": [{"field": "", ...}]}

before the scheduler was reached. No `care_event`, no status change, the card
redrawn exactly as it was. Every API test passed `json={}` and never saw it, and
the browser suite never pressed the button because no task had ever been
materialised to press it on.

These tests send what the UI sends - nothing - and assert the scheduler is
reached.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(env, monkeypatch: pytest.MonkeyPatch):
    from app.api.dependencies import CurrentUser, get_current_user
    from app.api.main import create_app
    from app.orchestration.services import scheduler

    calls: list[tuple[str, Any]] = []

    def fake_complete(client, *, task_id, user_id, note=None):
        calls.append(("done", note))
        return {"task_id": str(task_id), "status": "DONE", "next_due_at_utc": None}

    def fake_skip(client, *, task_id, user_id, note=None):
        calls.append(("skip", note))
        return {"task_id": str(task_id), "status": "SKIPPED", "next_due_at_utc": None}

    monkeypatch.setattr(scheduler, "complete", fake_complete)
    monkeypatch.setattr(scheduler, "skip", fake_skip)

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=uuid4(), email="t@example.com", client=object(), access_token="token"
    )

    test_client = TestClient(app)
    test_client.calls = calls  # type: ignore[attr-defined]
    return test_client


@pytest.mark.parametrize("action", ["done", "skip"])
def test_the_ui_call_with_no_body_is_accepted(client, action):
    """`api_client.post(path)` sends no body at all. That is the exact call both
    screens make, and it must reach the scheduler."""
    response = client.post(f"/v1/care-tasks/{uuid4()}/{action}")

    assert response.status_code == 200, response.text
    assert client.calls == [(action, None)]  # type: ignore[attr-defined]


@pytest.mark.parametrize("action", ["done", "skip"])
def test_a_note_still_arrives(client, action):
    response = client.post(f"/v1/care-tasks/{uuid4()}/{action}", json={"note": "השקיתי בערב"})

    assert response.status_code == 200, response.text
    assert client.calls == [(action, "השקיתי בערב")]  # type: ignore[attr-defined]


@pytest.mark.parametrize("action", ["done", "skip"])
def test_an_unknown_field_is_still_refused(client, action):
    """Optional is not the same as unvalidated: `extra=forbid` still holds."""
    response = client.post(f"/v1/care-tasks/{uuid4()}/{action}", json={"nope": 1})

    assert response.status_code == 422
