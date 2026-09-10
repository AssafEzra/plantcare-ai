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


# --- a stored token the refresh rejects ----------------------------------------
#
# Reported from the deployed app: returning to it after it had been idle raised
# `StreamlitDuplicateElementKey` instead of showing the sign-in form, and Rerun was
# the only way past - after which the next visit did it again.
#
# `restore()` reads the token and then clears it in the same script pass, and every
# operation mounted under one element key. Idle was the trigger because that is
# exactly when a stored token has expired. The fixture above cannot reach it: it
# replaces `read`/`write`/`clear`, so nothing ever mounts.
#
# This drives the real store against a double for the browser, which is the only
# arrangement in which the crash can happen at all.


@pytest.fixture
def real_store(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    import streamlit as st

    from app.ui.components import session_store
    from app.ui.state import session as session_module

    state: dict = {}
    for module in (st, session_module.st, session_store.st):
        monkeypatch.setattr(module, "session_state", state, raising=False)
    # Empty, as on Community Cloud - which is what sends `read()` to the component.
    monkeypatch.setattr(session_store.st, "context", SimpleNamespace(cookies={}), raising=False)

    jar: dict[str, str | None] = {"cookie": None}
    keys: list[str] = []

    def mount(*, data, key, height, on_token_change):
        if key in keys:
            raise RuntimeError(f"StreamlitDuplicateElementKey: {key}")
        keys.append(key)
        op = data["op"]
        if op == "save" and data["token"]:
            jar["cookie"] = data["token"]
        elif op == "clear":
            jar["cookie"] = None
        return SimpleNamespace(token=jar["cookie"] if jar["cookie"] is not None else "")

    monkeypatch.setattr(session_store, "_renderer", lambda: mount)
    return SimpleNamespace(
        module=session_module, jar=jar, keys=keys, state=state, monkeypatch=monkeypatch
    )


def test_an_expired_token_signs_the_user_out_instead_of_crashing(real_store):
    """The whole reported bug, at the level the user met it."""
    from app.ui.state import session as session_module

    real_store.jar["cookie"] = "expired-refresh-token"
    real_store.monkeypatch.setattr(
        session_module,
        "_client",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                refresh_session=lambda _t: (_ for _ in ()).throw(RuntimeError("token expired"))
            )
        ),
    )

    assert real_store.module.restore() is None
    assert not real_store.module.is_signed_in()


def test_and_the_rejected_token_is_gone_afterwards(real_store):
    """Why it recurred rather than happening once: the crash came before the clear
    ran, so the token survived and every later visit repeated it."""
    from app.ui.state import session as session_module

    real_store.jar["cookie"] = "expired-refresh-token"
    real_store.monkeypatch.setattr(
        session_module,
        "_client",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                refresh_session=lambda _t: (_ for _ in ()).throw(RuntimeError("token expired"))
            )
        ),
    )

    real_store.module.restore()

    assert real_store.jar["cookie"] is None


def test_a_refresh_that_returns_nothing_is_handled_the_same_way(real_store):
    """The other rejection branch, which had the identical collision."""
    from app.ui.state import session as session_module

    real_store.jar["cookie"] = "stale-refresh-token"
    real_store.monkeypatch.setattr(
        session_module,
        "_client",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(refresh_session=lambda _t: SimpleNamespace(session=None))
        ),
    )

    assert real_store.module.restore() is None
    assert real_store.jar["cookie"] is None


def test_a_valid_stored_token_still_restores(real_store):
    """The fix must not cost the component the thing it exists for."""
    from app.ui.state import session as session_module

    real_store.jar["cookie"] = "good-refresh-token"
    real_store.monkeypatch.setattr(
        session_module,
        "_client",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                refresh_session=lambda _t: SimpleNamespace(session=supabase_session())
            )
        ),
    )

    restored = real_store.module.restore()

    assert restored is not None
    assert restored.user_id == "user-1"
