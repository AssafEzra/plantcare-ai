"""Streamlit shell tests via AppTest — headless and in-process, no browser.

These assert the two things about the shell that are security-relevant rather
than cosmetic: that an unauthenticated visitor gets only the sign-in page, and
that the admin entry never appears for a non-admin. The second is a courtesy
rather than the control — every admin route and table is gated server-side — but
a regression there would still be a visible bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

APP = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "streamlit_app.py")


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    return AppTest.from_file(APP, default_timeout=30)


def test_the_app_starts_without_errors(app: AppTest):
    app.run()

    assert not app.exception, [str(e) for e in app.exception]


def test_an_unauthenticated_visitor_sees_the_sign_in_page(app: AppTest):
    app.run()

    headers = " ".join(h.value for h in app.header) + " ".join(s.value for s in app.subheader)
    assert "PlantCare AI" in headers


def test_sign_in_register_and_reset_are_all_offered(app: AppTest):
    """FINAL §22 puts registration, login and password reset in MVP scope."""
    app.run()

    labels = {t.label for t in app.tabs}
    assert {"כניסה", "הרשמה", "שכחתי סיסמה"} <= labels


def test_the_sign_in_form_asks_for_email_and_password(app: AppTest):
    app.run()

    labels = {i.label for i in app.text_input}
    assert "אימייל" in labels
    assert "סיסמה" in labels


def test_no_application_navigation_before_signing_in(app: AppTest):
    """An unauthenticated visitor must not be offered plant pages at all."""
    app.run()

    rendered = " ".join(str(element.value) for element in app.markdown)
    assert "הצמחים שלי" not in rendered
    assert "ניהול" not in rendered


def test_signing_in_is_not_implied_by_a_failed_attempt(app: AppTest):
    """A wrong password must leave the visitor unauthenticated."""
    app.run()
    app.text_input(key="si_email").set_value("nobody@example.com")
    app.text_input(key="si_password").set_value("wrong-password")
    app.button[0].click().run()

    assert not app.exception
    # Still on the sign-in page.
    assert {t.label for t in app.tabs} >= {"כניסה"}


def test_registration_rejects_a_short_password(app: AppTest):
    """Supabase enforces a minimum of 8; the UI should say so before the round trip."""
    app.run()
    app.text_input(key="ru_email").set_value("someone@example.com")
    app.text_input(key="ru_password").set_value("short")

    register_button = next(b for b in app.button if b.label == "הרשמה")
    register_button.click().run()

    warnings = " ".join(w.value for w in app.warning)
    assert "8" in warnings


def test_password_reset_does_not_reveal_whether_an_account_exists(app: AppTest):
    """A different message for a known and unknown address is an account oracle."""
    app.run()
    app.text_input(key="rp_email").set_value("definitely-not-registered@example.com")

    reset_button = next(b for b in app.button if "איפוס" in b.label)
    reset_button.click().run()

    success = " ".join(s.value for s in app.success)
    assert "אם קיים חשבון" in success
