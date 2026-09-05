"""Notification preferences in Settings (FINAL §14, A10).

The interesting assertion is the help text on the time field. Two settings in
this product carry a "preferred time" and they answer different questions — one
is when a task is *due*, the other when we may *write*. A10 exists because the
specification never distinguished them, so the interface has to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "settings.py")

PROFILE = {"display_name": "דנה", "timezone": "Asia/Jerusalem", "email": "d@example.com"}
PREFERENCES = {
    "user_id": "u1",
    "email_enabled": True,
    "preferred_time_local": "08:00:00",
    "daily_digest": True,
}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(preferences: dict[str, Any] | None = None) -> AppTest:
        from app.ui.state import api_client

        def fake_get(path: str, **kwargs: Any) -> Any:
            if "notification-preferences" in path:
                return preferences if preferences is not None else PREFERENCES
            return PROFILE

        monkeypatch.setattr(api_client, "get", fake_get)
        return AppTest.from_file(PAGE, default_timeout=30)

    return _build


def test_the_page_renders_the_reminder_controls(page):
    app = page()
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    labels = [t.label for t in app.toggle]
    assert "תזכורות במייל" in labels
    assert "סיכום יומי" in labels


def test_the_controls_are_no_longer_disabled(page):
    """They shipped disabled in PR 9 as an honest placeholder. Leaving them that
    way after the endpoints exist would be the opposite."""
    app = page()
    app.run()

    assert all(not t.disabled for t in app.toggle)
    assert all(not t.disabled for t in app.time_input)


def test_the_stored_preferences_are_reflected(page):
    app = page({**PREFERENCES, "email_enabled": False, "daily_digest": False})
    app.run()

    assert all(t.value is False for t in app.toggle)


def test_the_time_field_explains_which_time_it_governs(page):
    """A10. Two settings in this product carry a preferred time, and a user who
    confuses them ends up with reminders they did not ask for."""
    app = page()
    app.run()

    help_text = " ".join(str(t.help or "") for t in app.time_input)
    assert "תזכורת" in help_text
    assert "תוכנית הטיפול" in help_text


def test_turning_email_off_says_the_work_is_still_tracked(page):
    """A toggle alone would leave the user wondering whether their plants stopped
    being looked after."""
    app = page({**PREFERENCES, "email_enabled": False})
    app.run()

    captions = " ".join(str(c.value) for c in app.caption)
    assert "מסך הבית" in captions
