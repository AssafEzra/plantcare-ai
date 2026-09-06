"""A browser refresh must not sign the user out (PR 32).

Reported from real use: *"every time i hit refresh to the browser window it
logges me out and require a new sign in"*.

`st.session_state` lives for one Streamlit session and a reload starts a new one,
so the auth session — held there and nowhere else — vanished on F5. On a page
that polls a four-minute research run, that is not a small annoyance.

The fix keeps the *refresh* token in a cookie - written by a small Custom
Component v2, because Streamlit can read cookies but not write them - and rebuilds
the session from it before routing. A cookie rather than `localStorage` because it
is readable on the **first** run of a new session, so there is no intermediate
state in which the sign-in form could flash at somebody who is signed in.

These tests stand in for the browser: `read`, `write` and `clear` are what the
cookie would have held.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.conftest import REQUIRED_ENV


def supabase_session(user_id: str = "user-1", token: str = "refresh-2"):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, email="dana@example.com"),
        access_token="access-2",
        refresh_token=token,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).timestamp(),
    )


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    import streamlit as st

    from app.ui.components import session_store
    from app.ui.state import session as session_module

    # A plain dict stands in for `st.session_state`, which needs a script run.
    state: dict = {}
    monkeypatch.setattr(st, "session_state", state, raising=False)
    monkeypatch.setattr(session_module.st, "session_state", state, raising=False)

    calls: list[dict] = []
    cookie: dict[str, str | None] = {"value": None}

    def fake_read() -> str | None:
        calls.append({"op": "read"})
        return cookie["value"]

    def fake_write(token: str) -> None:
        calls.append({"op": "save", "token": token})
        cookie["value"] = token

    def fake_clear() -> None:
        calls.append({"op": "clear"})
        cookie["value"] = None

    for module in (session_store, session_module.store):
        monkeypatch.setattr(module, "read", fake_read)
        monkeypatch.setattr(module, "write", fake_write)
        monkeypatch.setattr(module, "clear", fake_clear)

    return SimpleNamespace(
        module=session_module, state=state, calls=calls, cookie=cookie, monkeypatch=monkeypatch
    )


def test_no_cookie_means_no_session(session):
    """And it is decided on the first run, with no intermediate state: the cookie
    arrives in the connection headers, so there is never a moment where the app
    does not yet know."""
    assert session.module.restore() is None
    assert not session.module.is_signed_in()


def test_a_stored_token_restores_the_session(session):
    from app.ui.state import session as session_module

    session.cookie["value"] = "refresh-1"
    session.monkeypatch.setattr(
        session_module,
        "_client",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                refresh_session=lambda _t: SimpleNamespace(session=supabase_session())
            )
        ),
    )

    restored = session.module.restore()

    assert restored is not None
    assert restored.user_id == "user-1"
    assert session.module.is_signed_in()


def test_a_failed_restore_is_not_retried_every_rerun(session):
    """It is a network call that would fail the same way each time, on a page that
    reruns on every keystroke."""
    session.module.restore()
    session.module.restore()

    assert [c for c in session.calls if c["op"] == "read"] == [{"op": "read"}]


def test_a_rejected_token_is_discarded_rather_than_retried(session):
    """Revoked, expired, or from another deployment. All three mean sign in
    again, and keeping it would retry the same failure on every load."""
    from app.ui.state import session as session_module

    session.cookie["value"] = "stale-token"

    def boom(_t):
        raise RuntimeError("refresh_token_not_found")

    session.monkeypatch.setattr(
        session_module,
        "_client",
        lambda: SimpleNamespace(auth=SimpleNamespace(refresh_session=boom)),
    )

    assert session.module.restore() is None
    assert {"op": "clear"} in session.calls
    assert session.cookie["value"] is None


def test_a_renewed_token_is_written_back(session):
    """Supabase rotates the refresh token on every renewal, so a browser copy
    that is never rewritten would present a retired token on the next load — a
    delayed version of the same logout."""
    session.module._store(supabase_session(token="refresh-99"))

    session.module.restore()

    assert {"op": "save", "token": "refresh-99"} in session.calls


def test_signing_out_clears_the_browser_copy(session):
    from app.ui.state import session as session_module

    session.module._store(supabase_session())
    session.state.pop(session_module._PENDING_WRITE, None)
    session.monkeypatch.setattr(
        session_module,
        "_client",
        lambda: SimpleNamespace(auth=SimpleNamespace(sign_out=lambda: None)),
    )

    session.module.sign_out()

    assert not session.module.is_signed_in()
    assert {"op": "clear"} in session.calls
    assert session.cookie["value"] is None
