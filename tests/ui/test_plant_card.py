"""What a plant card shows (`PROGRESS §10`, `UI_DESIGN_TOKENS` "My Plants").

Found by auditing the checklist against the code rather than by a failing test,
which is the point of writing these down: the card had been reading
`thumbnail_url` since PR 9 and `GET /v1/plants` never set it, so every card in the
grid rendered "no image" no matter how many photographs the plant had. Nothing
failed. The key was simply never there.

Species and the nearest task were missing for the same reason - the endpoint did
not return them - and the card's docstring said they would arrive "once
identification and scheduling exist". Both had existed since PR 13 and PR 17.

So these tests assert on rendered text, not on the shape of a dict. A card that
receives a field and does not show it passes a schema test and fails a user.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "my_plants.py")

FULL = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "המונסטרה בסלון",
    "status": "ACTIVE",
    "current_health_status": "HEALTHY",
    "species_name": "מונסטרה עלת-חורים",
    "thumbnail_url": "https://example.test/signed/thumb.jpg",
    "next_task": {
        "id": "33333333-3333-3333-3333-333333333333",
        "action_type": "WATERING",
        "due_at_utc": "2099-01-01T06:00:00+00:00",
        "status": "PENDING",
    },
}

BARE = {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "צמח חדש",
    "status": "PENDING_IDENTIFICATION",
    "current_health_status": "UNKNOWN",
}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(plants: list[dict[str, Any]]) -> AppTest:
        from app.ui.state import api_client

        monkeypatch.setattr(api_client, "get", lambda path, **kwargs: plants)
        app = AppTest.from_file(PAGE, default_timeout=30)
        app.run()
        assert not app.exception, [str(e) for e in app.exception]
        return app

    return _build


def _text(app: AppTest) -> str:
    return " ".join(element.value for element in app.markdown) + " ".join(
        element.value for element in app.caption
    )


def test_the_card_shows_the_species_under_the_name(page):
    """Two different names for the same plant: the one the user chose and the one
    the identification settled on. The card shows both, because "my monstera" is
    what they call it and the binomial is what the care plan is built from."""
    app = page([FULL])

    assert "המונסטרה בסלון" in _text(app)
    assert "מונסטרה עלת-חורים" in _text(app)


def test_the_card_shows_the_nearest_task_in_words(page):
    """Not a date. `due_text` is shared with the task card so the same task is
    described the same way wherever it appears."""
    app = page([FULL])

    assert "השקיה" in _text(app)


def test_an_overdue_task_says_it_is_late(page):
    """The most actionable thing a card can say. A grid showing only a date makes
    the reader work out whether it has already passed."""
    late = {
        **FULL,
        "next_task": {
            **FULL["next_task"],
            "due_at_utc": "2020-01-01T06:00:00+00:00",
            "status": "OVERDUE",
        },
    }
    app = page([late])

    assert "באיחור" in _text(app)


def test_the_thumbnail_is_rendered_when_there_is_one(page):
    """The regression this file exists for."""
    app = page([FULL])

    assert app.image, "a plant with a main image rendered no image"


def test_a_plant_without_a_photograph_says_so_instead(page):
    """The empty case must stay honest - and must not crash on absent keys, which
    is what a plant looks like between being created and being identified."""
    app = page([BARE])

    text = _text(app)
    assert "אין תמונה" in text
    assert "ממתין לזיהוי" in text


def test_a_plant_with_no_species_or_task_renders_without_them(page):
    """No placeholder text that looks like data. A card that said "no species
    yet" in the same register as a real species would be read as one."""
    app = page([BARE])

    text = _text(app)
    assert "השקיה" not in text
    assert "צמח חדש" in text
