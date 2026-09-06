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


# --- what each role's application actually is (PR 33) ---------------------------
#
# An administrator gets the operator's application, not the gardener's with an
# extra tab. Home, My Plants, Add Plant and the plant dashboard are somebody
# else's product; carrying them made the admin panel look like a sixth tab of a
# plant-care app rather than the thing an operator opens.
#
# Presentation only, and these tests say so where they can: every plant route is
# still the caller's own by RLS and every admin route is still gated server-side
# (FINAL §22, §26). Navigation has never been the control.


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(role: str, user_id: str) -> AppTest:
        from datetime import UTC, datetime, timedelta

        from app.ui.state import api_client
        from app.ui.state import session as session_module

        monkeypatch.setattr(session_module, "restore", lambda: None)
        monkeypatch.setattr(session_module, "is_signed_in", lambda: True)
        monkeypatch.setattr(
            session_module,
            "current",
            lambda: session_module.AuthSession(
                # A distinct id per role: `_profile` is cached on it, so reusing
                # one would serve the first role's profile to the second and the
                # test would pass for the wrong reason.
                user_id=user_id,
                email="a@example.com",
                access_token="token-that-is-long-enough-to-slice",
                refresh_token="r",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        )

        def fake_get(path: str, **kwargs):
            if path == "/v1/me":
                return {"display_name": "אסף", "role": role, "timezone": "Asia/Jerusalem"}
            if path == "/v1/admin/overview":
                return {
                    "failed_agent_requests": 0,
                    "failed_notifications": 0,
                    "drafts_awaiting_review": 0,
                    "open_knowledge_reports": 0,
                    "window_days": 7,
                    "agent_stats": [],
                    "total_estimated_cost": 0,
                }
            if path == "/v1/dashboard":
                return {
                    "today_care": [],
                    "upcoming_care": [],
                    "overdue_summary": [],
                    "plants_needing_attention": [],
                    "my_plants": [],
                    "counts": {
                        "today_tasks": 0,
                        "attention": 0,
                        "active_plants": 0,
                        "overdue": 0,
                    },
                }
            return []

        monkeypatch.setattr(api_client, "get", fake_get)

        app = AppTest.from_file(APP, default_timeout=30)
        app.run()
        assert not app.exception, [str(e) for e in app.exception]
        return app

    return _build


def headings(app: AppTest) -> str:
    return " ".join(
        [h.value for h in app.header]
        + [s.value for s in app.subheader]
        + [c.value for c in app.caption]
    )


def test_an_admin_lands_on_the_admin_panel(signed_in):
    """ "At login" is the requirement, so the default page is the assertion - not
    merely that the entry exists somewhere in the sidebar."""
    app = signed_in("ADMIN", "u-admin-default")

    assert "ניהול" in headings(app)
    assert "אזור מנהלי מערכת" in headings(app)


def test_an_admin_does_not_get_the_gardeners_pages(signed_in):
    app = signed_in("ADMIN", "u-admin-pages")

    body = headings(app)
    assert "הטיפול של היום" not in body, "Home rendered for an administrator"
    assert "מה מחכה לך היום" not in body


def nav(app: AppTest) -> set[str]:
    """The entries `st.navigation` actually registered.

    `_registered_pages` is private, and it is still the right thing to assert on:
    the requirement is about the navigation itself, and checking which page
    happened to render would pass just as happily with four extra entries beside
    it. If a Streamlit upgrade moves this, the browser suite covers the same
    ground through the sidebar a user really sees.
    """
    return {page["page_name"] for page in app._registered_pages.values()}


def test_an_admin_gets_exactly_two_entries(signed_in):
    """Not the gardener's application with a tab added. Settings stays because an
    administrator still has a timezone, a display name and notification
    preferences, and those live nowhere else."""
    app = signed_in("ADMIN", "u-admin-nav")

    assert nav(app) == {"ניהול", "הגדרות"}


def test_a_regular_user_gets_the_whole_application(signed_in):
    app = signed_in("USER", "u-plain-nav")

    assert nav(app) == {"בית", "הצמחים שלי", "הוספת צמח", "הצמח שלי", "הגדרות"}
    assert "ניהול" not in nav(app), "the admin entry appeared for a regular user"


def test_a_regular_user_lands_on_home(signed_in):
    app = signed_in("USER", "u-plain")

    body = headings(app)
    assert "הטיפול של היום" in body
    assert "אזור מנהלי מערכת" not in body, "the admin panel rendered for a regular user"
