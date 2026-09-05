"""A finished identification must be answerable from the plant's own page.

The defect this file exists for, found by a user rather than by a test: they
added a plant, the identification succeeded, and the interface told them the
plant was not identified. Both halves worked. The confirmation screen lived in
`add_plant.py` behind `st.session_state`, so it existed only for the tab that
started the flow — a refresh, a closed tab, or a walk to the kettle stranded the
plant in `PENDING_IDENTIFICATION` forever with nothing anywhere to press.

The same shape as PR 25 and PR 27: two correct halves and nothing joining them.
So these tests assert on what a user can reach, not on what a function returns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "plant_dashboard.py")

PENDING = {
    "id": "dddddddd-0000-0000-0000-000000000001",
    "confidence_level": "HIGH",
    "image_quality": "תמונות ברורות ומוארות היטב.",
    "created_at": "2026-09-05T20:51:00Z",
    "candidates": [
        {
            "id": "eeeeeeee-0000-0000-0000-000000000001",
            "scientific_name": "Coleus scutellarioides",
            "common_name": "כנף נזירים",
            "rank": 1,
            "confidence_score": 0.91,
        },
        {
            "id": "eeeeeeee-0000-0000-0000-000000000002",
            "scientific_name": "Perilla frutescens",
            "common_name": "פרילה",
            "rank": 2,
            "confidence_score": 0.12,
        },
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

    posted: list[tuple[str, dict | None]] = []

    def _build(*, pending: dict | None, species: dict | None = None) -> AppTest:
        from app.ui.state import api_client

        def fake_get(path: str, **kwargs: Any) -> Any:
            if path.endswith("/dashboard"):
                return {
                    "id": "plant-1",
                    "name": None,
                    "status": "PENDING_IDENTIFICATION" if pending else "ACTIVE",
                    "created_at": "2026-09-05T20:47:00Z",
                    "species": species,
                    "pending_identification": pending,
                    "main_image": None,
                    "gallery": [],
                    "environment": None,
                    "health": {"current_status": "UNKNOWN"},
                    "upcoming_tasks": [],
                    "care_plan": None,
                    "open_proposals": 0,
                }
            return []

        def fake_post(path: str, *, json: dict | None = None, **kwargs: Any) -> Any:
            posted.append((path, json))
            return {"status": "KNOWLEDGE_PENDING"}

        monkeypatch.setattr(api_client, "get", fake_get)
        monkeypatch.setattr(api_client, "post", fake_post)

        app = AppTest.from_file(PAGE, default_timeout=30)
        app.session_state["pc_selected_plant"] = "plant-1"
        return app

    _build.posted = posted  # type: ignore[attr-defined]
    return _build


def rendered(app: AppTest) -> str:
    parts: list[str] = []
    for collection in (app.markdown, app.caption, app.subheader, app.info, app.warning):
        parts.extend(str(element.value) for element in collection)
    return " ".join(parts)


def test_a_waiting_identification_is_shown_on_the_plant_page(page):
    """The regression. The species the model found appears where the plant is."""
    app = page(pending=PENDING)
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    text = rendered(app)
    assert "כנף נזירים" in text
    assert "Coleus scutellarioides" in text
    assert "הצמח עדיין לא זוהה" not in text, "an identified plant was called unidentified"


def test_the_user_can_answer_it_from_there(page):
    """A result the user cannot act on is the bug, not the display of it."""
    app = page(pending=PENDING)
    app.run()

    confirm = [button for button in app.button if button.label == "זה הצמח שלי"]
    assert confirm, "the identification could be seen but not confirmed"

    confirm[0].click().run()

    path, payload = page.posted[-1]  # type: ignore[attr-defined]
    assert path.endswith(f"/v1/identifications/{PENDING['id']}/confirm")
    assert payload["candidate_id"] == PENDING["candidates"][0]["id"]


def test_the_alternatives_are_offered_too(page):
    """FINAL §8: the user chooses. A single option is a decision already made."""
    app = page(pending=PENDING)
    app.run()

    assert app.radio, "no way to pick an alternative candidate"
    assert any("Perilla frutescens" in str(option) for option in app.radio[0].options)


def test_the_plant_can_be_named_while_confirming(page):
    """A2: `plants.name` is nullable only until confirmation. The field is optional
    — an empty one lets the API fall back to the candidate's common name — so it
    must never block the button."""
    app = page(pending=PENDING)
    app.run()

    names = [field for field in app.text_input if field.label == "איך לקרוא לצמח?"]
    assert names, "no way to name the plant at the moment it stops being anonymous"

    names[0].set_value("המונסטרה בסלון").run()
    next(button for button in app.button if button.label == "זה הצמח שלי").click().run()

    _, payload = page.posted[-1]  # type: ignore[attr-defined]
    assert payload["name"] == "המונסטרה בסלון"


def test_nothing_is_asked_once_the_plant_has_a_species(page):
    """The question disappears when it has been answered. A dashboard that keeps
    asking is asking the user to confirm what they already confirmed."""
    app = page(
        pending=None,
        species={
            "id": "ffffffff-0000-0000-0000-000000000001",
            "scientific_name": "Coleus scutellarioides",
            "common_name": "כנף נזירים",
        },
    )
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    assert not [button for button in app.button if button.label == "זה הצמח שלי"]


# --- the wizard still asks the same question ------------------------------------

WIZARD = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "add_plant.py")


def test_the_wizard_asks_it_the_same_way(monkeypatch: pytest.MonkeyPatch):
    """The card is shared, so the two routes cannot drift apart.

    Worth its own test because the wizard reaches step 3 through session state
    that no other test sets up: a refactor that broke only this entry point would
    otherwise be found by a user, which is how this PR started.
    """
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    from app.ui.state import api_client

    posted: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(api_client, "get", lambda path, **kwargs: {**PENDING, "status": "SUCCESS"})
    monkeypatch.setattr(
        api_client,
        "post",
        lambda path, *, json=None, **kwargs: (
            posted.append((path, json)),
            {"status": "KNOWLEDGE_PENDING", "knowledge_pending": True},
        )[1],
    )

    app = AppTest.from_file(WIZARD, default_timeout=30)
    app.session_state["add_plant_step"] = "confirm"
    app.session_state["add_plant_identification_id"] = PENDING["id"]
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    confirm = [button for button in app.button if button.label == "זה הצמח שלי"]
    assert confirm, "the wizard's own confirmation button is gone"

    confirm[0].click().run()
    path, payload = posted[-1]
    assert path.endswith(f"/v1/identifications/{PENDING['id']}/confirm")
    assert payload["candidate_id"] == PENDING["candidates"][0]["id"]
