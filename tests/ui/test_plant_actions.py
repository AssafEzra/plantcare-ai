"""Endpoints that had no way in, until the seam audit found them (PR 31).

A static pass over the codebase — every route against every path literal in the
interface, and every response field against what any screen reads — turned up
eight capabilities that were built, tested, ticked in `PROGRESS`, and reachable by
nobody:

* a plant could not be renamed (`PATCH /v1/plants/{id}`, PR 11);
* a photograph could not be removed (`DELETE …/images/{id}`, PR 10);
* a due task was read-only on the plant's own page (`care_task_card` was given no
  callbacks, so it drew no buttons);
* knowledge showed its prose and never its sources, though the endpoint returns
  them and its docstring promises "where it came from";
* a user could not say the identification was wrong (`POST …/correct`, A13).

Each is the shape that has produced every serious defect in this build. These
tests assert the control exists and sends the right request, because "the
endpoint works" was already true for all five.
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
    "url": "https://example.test/full.jpg",
    "thumbnail_url": "https://example.test/thumb.jpg",
    "context_type": "gallery",
    "is_main": True,
    "created_at": "2026-09-05T20:50:00Z",
}

TASK = {
    "id": "cccccccc-0000-0000-0000-000000000001",
    "plant_id": "plant-1",
    "action_type": "WATERING",
    "due_at_utc": "2026-09-06T06:00:00+00:00",
    "status": "PENDING",
    "plant_name": "קולאוס",
}

SPECIES = {
    "id": "dddddddd-0000-0000-0000-000000000001",
    "scientific_name": "Coleus scutellarioides",
    "common_name": "כנף נזירים",
}

KNOWLEDGE = {
    "id": "eeeeeeee-0000-0000-0000-000000000001",
    "species_id": SPECIES["id"],
    "language": "he",
    "version_number": 3,
    "published_at": "2026-09-05T22:00:00Z",
    "content": {"watering": {"text": "להשקות כשהמצע יבש.", "confidence": 0.8}},
    "source_summary": {},
    "sources": [
        {
            "source_class": "APPROVED",
            "title": "NC State Extension",
            "publisher": "NC State",
            "url": "https://plants.ces.ncsu.edu/plants/coleus-scutellarioides/",
        }
    ],
}

ADJUSTED_VERSION = "bbbbbbbb-0000-0000-0000-000000000004"

ACTIVE_PLAN = {
    "id": "bbbbbbbb-0000-0000-0000-000000000003",
    "care_plan_id": "cccccccc-0000-0000-0000-000000000009",
    "version_number": 3,
    "status": "ACTIVE",
    "source_type": "HEALTH_DRIVEN",
    "professional_recommendations": {"summary": "השקיה מתונה."},
    "operational_preferences": {},
    "change_summary": None,
    "created_at": "2026-09-05T22:00:00Z",
    "knowledge_review": "reviewed",
    "rules": [
        {
            "id": "eeee1111-0000-0000-0000-000000000001",
            "action_type": "ROTATING",
            "interval_days": 7,
            "preferred_time_local": "09:00:00",
            "preferred_weekday": "SUNDAY",
            "instructions": None,
            "is_active": True,
        }
    ],
}

PENDING = {
    "id": "ffffffff-0000-0000-0000-000000000001",
    "confidence_level": "HIGH",
    "created_at": "2026-09-05T20:51:00Z",
    "candidates": [
        {
            "id": "99999999-0000-0000-0000-000000000001",
            "scientific_name": "Coleus scutellarioides",
            "common_name": "כנף נזירים",
            "rank": 1,
            "confidence_score": 0.91,
        }
    ],
}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    sent: list[tuple[str, str, dict | None]] = []

    def _build(
        *,
        species: dict | None = None,
        tasks: list[dict] | None = None,
        pending: dict | None = None,
        delete_outcome: str = "deleted",
        plan: dict | None = None,
    ) -> AppTest:
        from app.ui.components import agent_progress
        from app.ui.state import api_client

        monkeypatch.setattr(agent_progress, "POLL_INTERVAL_SECONDS", 0)

        def fake_get(path: str, **kwargs: Any) -> Any:
            if path.endswith("/dashboard"):
                return {
                    "id": "plant-1",
                    "name": "קולאוס",
                    "notes": "מתנה מחבר",
                    "status": "ACTIVE",
                    "created_at": "2026-09-05T20:47:00Z",
                    "species": species,
                    "pending_identification": pending,
                    "main_image": IMAGE,
                    "gallery": [IMAGE],
                    "environment": None,
                    "health": {"current_status": "HEALTHY"},
                    "upcoming_tasks": tasks or [],
                    "care_plan": plan,
                    "open_proposals": 0,
                }
            if path.endswith("/knowledge"):
                return KNOWLEDGE
            if "/agent-requests/" in path:
                return {"status": "SUCCEEDED", "stage": "COMPLETE", "output_summary": {}}
            return []

        def record(verb: str):
            def _call(path: str, *, json: dict | None = None, **kwargs: Any) -> Any:
                sent.append((verb, path, json))
                if verb == "DELETE":
                    return {"outcome": delete_outcome}
                if path.endswith("/operational-adjustment"):
                    # What the endpoint really answers. `adjust` reads the id back
                    # to point the dialog at the version it just created.
                    return {
                        "version_id": ADJUSTED_VERSION,
                        "version_number": 4,
                        "status": "PROPOSED",
                    }
                return {"agent_request_id": "req-1", "status": "QUEUED"}

            return _call

        monkeypatch.setattr(api_client, "get", fake_get)
        monkeypatch.setattr(agent_progress, "get", fake_get)
        for verb in ("post", "put", "patch", "delete"):
            monkeypatch.setattr(api_client, verb, record(verb.upper()))

        app = AppTest.from_file(PAGE, default_timeout=30)
        app.session_state["pc_selected_plant"] = "plant-1"
        return app

    _build.sent = sent  # type: ignore[attr-defined]
    return _build


def rendered(app: AppTest) -> str:
    parts: list[str] = []
    for collection in (app.markdown, app.caption, app.subheader, app.info, app.success):
        parts.extend(str(element.value) for element in collection)
    parts.extend(element.label for element in app.expander)
    return " ".join(parts)


def press(app: AppTest, label: str) -> AppTest:
    next(button for button in app.button if getattr(button, "label", "") == label).click().run()
    return app


# --- renaming -------------------------------------------------------------------


def test_a_plant_can_be_renamed(page):
    """PR 28 finally gave plants a name at confirmation. Until this, that was the
    only name a plant could ever have."""
    app = page()
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    app.text_input("pd_rename_name").set_value("המונסטרה בסלון").run()
    press(app, "שמירה")

    verb, path, payload = page.sent[-1]  # type: ignore[attr-defined]
    assert verb == "PATCH"
    assert path.endswith("/v1/plants/plant-1")
    assert payload["name"] == "המונסטרה בסלון"


def test_the_rename_form_opens_on_the_current_values(page):
    app = page()
    app.run()

    assert app.text_input("pd_rename_name").value == "קולאוס"
    assert app.text_area("pd_rename_notes").value == "מתנה מחבר"


# --- images ---------------------------------------------------------------------


def test_a_photograph_can_be_removed(page):
    app = page()
    app.run()

    press(app, "מחיקה")

    verb, path, _ = page.sent[-1]  # type: ignore[attr-defined]
    assert verb == "DELETE"
    assert path.endswith(f"/images/{IMAGE['id']}")


def test_an_ai_used_photograph_says_it_was_kept(page):
    """FINAL §20: an image the AI has used is hidden, not destroyed, because an
    assessment that cited it must stay legible. The user is told which happened —
    "deleted" would be a lie about a row that is still there."""
    app = page(delete_outcome="hidden")
    app.run()
    press(app, "מחיקה")

    assert "נשמרת כראיה" in rendered(app)


# --- today's work ---------------------------------------------------------------


def test_a_due_task_can_be_completed_from_the_plant(page):
    """The card draws Done and Skip only when given the callbacks, and this page
    gave none — so the same task was actionable on Home and read-only here."""
    app = page(tasks=[TASK])
    app.run()

    press(app, "בוצע")

    verb, path, _ = page.sent[-1]  # type: ignore[attr-defined]
    assert verb == "POST"
    assert path.endswith(f"/v1/care-tasks/{TASK['id']}/done")


def test_a_due_task_can_be_skipped_from_the_plant(page):
    """Skip is not the absence of Done: the scheduler anchors the next occurrence
    differently, so silence and a skip mean different things (A8)."""
    app = page(tasks=[TASK])
    app.run()

    press(app, "דילוג")

    _, path, _ = page.sent[-1]  # type: ignore[attr-defined]
    assert path.endswith(f"/v1/care-tasks/{TASK['id']}/skip")


# --- provenance -----------------------------------------------------------------


def test_the_knowledge_shows_where_it_came_from(page):
    """`GET /v1/species/{id}/knowledge` has always returned `sources`, and its own
    docstring says "what a user sees: the current version *and where it came
    from*". The second half reached nobody."""
    app = page(species=SPECIES)
    app.run()

    text = rendered(app)
    assert "מקורות (1)" in text
    assert "גרסה 3" in text


# --- disagreeing ----------------------------------------------------------------


def test_the_user_can_report_a_wrong_identification(page):
    """A13. It records history and moves nothing — FINAL §8 keeps confirmation as
    the only thing that changes a plant — so the copy must not promise a fix."""
    app = page(pending=PENDING)
    app.run()

    assert any(b.label == "שליחת דיווח" for b in app.button), "no way to disagree"

    app.text_input("pd_ident_correct_name").set_value("Monstera deliciosa").run()
    press(app, "שליחת דיווח")

    verb, path, payload = page.sent[-1]  # type: ignore[attr-defined]
    assert verb == "POST"
    assert path.endswith(f"/v1/identifications/{PENDING['id']}/correct")
    assert payload["scientific_name"] == "Monstera deliciosa"


# --- saving an adjustment leads somewhere (PR 33) --------------------------------
#
# Reported twice, from real use: first "it wont let you save changes", then "it
# still doesnt show the string after i save". The second was not a missing
# message - it was a message rendered at the top of the page while the user was at
# the bottom of it, because `st.rerun()` keeps the scroll position and the
# adjustment form sits hundreds of pixels below `show_flash()`.
#
# So saving no longer relies on the user finding a confirmation. It opens the
# proposal it just created, which is the decision the save exists to produce.


def open_adjustment(app: AppTest) -> AppTest:
    app.number_input(key="plan_days_eeee1111-0000-0000-0000-000000000001").set_value(5).run()
    app.text_input(key="plan_summary").set_value("הדירה חמה יותר").run()
    return app


def test_saving_an_adjustment_opens_the_proposal_it_created(page):
    from app.ui.components.proposal_dialog import STATE_KEY

    app = page(plan=ACTIVE_PLAN)
    app.run()
    open_adjustment(app)

    next(b for b in app.button if b.label == "שמירת השינוי").click().run()

    verb, path, payload = page.sent[-1]  # type: ignore[attr-defined]
    assert verb == "POST"
    assert path.endswith("/operational-adjustment")
    assert payload["operational_preferences"] == {"ROTATING": {"interval_days": 5}}
    assert app.session_state[STATE_KEY] == ADJUSTED_VERSION, (
        "the proposal the save created was not opened"
    )


def test_the_confirmation_is_rendered_as_well(page):
    """The dialog is the answer for whoever is looking at it; the message is the
    answer for whoever closes it. Both, not either - the flash is consumed by the
    same rerun that opens the dialog, so it has to be on the page too."""
    app = page(plan=ACTIVE_PLAN)
    app.run()
    open_adjustment(app)
    next(b for b in app.button if b.label == "שמירת השינוי").click().run()

    shown = " ".join(str(i.value) for i in app.info)
    assert "לוח הזמנים" in shown, f"the confirmation was not rendered: {shown[:200]}"


def test_a_failed_adjustment_opens_nothing(page, monkeypatch):
    """A dialog about a version that was never created is worse than no dialog:
    `proposal_dialog` would find no such proposal and close itself, which reads as
    the save having silently worked."""
    from app.ui.components.proposal_dialog import STATE_KEY
    from app.ui.state.api_client import ApiError

    app = page(plan=ACTIVE_PLAN)
    app.run()

    from app.ui.state import api_client

    def boom(path: str, **kwargs: Any) -> Any:
        raise ApiError("VALIDATION_FAILED", "לא ניתן לשמור.", status=422)

    monkeypatch.setattr(api_client, "post", boom)
    open_adjustment(app)
    next(b for b in app.button if b.label == "שמירת השינוי").click().run()

    assert STATE_KEY not in app.session_state
