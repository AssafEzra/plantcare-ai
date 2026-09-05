"""The grid is the only route to a plant's dashboard.

Found in the browser: `my_plants.py` rendered every card without an open action,
so the plant dashboard — and with it the entire care plan built in PR 16 — was
unreachable from the interface. Everything worked; nothing could be got to.

The sidebar entry does not substitute for it: it lands on an empty state until a
plant has been selected, and selecting one is what the card does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "my_plants.py")

PLANTS = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "המונסטרה בסלון",
        "status": "ACTIVE",
        "current_health_status": "HEALTHY",
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "הפותוס במטבח",
        "status": "ACTIVE",
        "current_health_status": "UNKNOWN",
    },
]


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
        return AppTest.from_file(PAGE, default_timeout=30)

    return _build


def test_every_plant_card_offers_a_way_in(page):
    """One open control per plant. Without it the grid is a dead end."""
    app = page(PLANTS)
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    opens = [b for b in app.button if b.label == "פתיחה"]
    assert len(opens) == len(PLANTS)


def test_opening_a_plant_selects_it_for_the_dashboard(page):
    """The dashboard reads `pc_selected_plant`; the card is what sets it."""
    app = page(PLANTS)
    app.run()

    opens = [b for b in app.button if b.label == "פתיחה"]
    opens[0].click().run()

    assert app.session_state["pc_selected_plant"] == PLANTS[0]["id"]


def test_one_plant_is_counted_in_words(page):
    """ "1 צמחים" is what a format string produces and not what Hebrew does."""
    app = page(PLANTS[:1])
    app.run()

    captions = " ".join(str(c.value) for c in app.caption)
    assert "צמח אחד" in captions
    assert "1 צמחים" not in captions
