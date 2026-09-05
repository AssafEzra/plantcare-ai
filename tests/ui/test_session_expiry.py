"""An expired session must return the user to sign-in, not strand them.

Found in the browser after a tab had been open for a couple of hours: the page
still showed the signed-in navigation, a red "session expired" banner, and no way
forward except guessing to reload. `ApiError.is_auth_error` had existed since
PR 9 and nothing acted on it.

The sequencing is the whole bug. `session.access_token()` clears the stored
session when a refresh fails, but the shell decided the routing at the top of the
run and is already rendering the signed-in layout — so clearing state is not
enough on its own. Only a rerun makes the next pass route to sign-in.
"""

from __future__ import annotations

import pytest
import streamlit as st

from app.ui.state.api_client import ApiError


@pytest.fixture(autouse=True)
def _clean_session(monkeypatch: pytest.MonkeyPatch):
    from app.ui.state import session as session_module

    store: dict = {}
    monkeypatch.setattr(st, "session_state", store, raising=False)
    monkeypatch.setattr(session_module.st, "session_state", store, raising=False)
    return store


def test_an_auth_error_signs_out_and_reruns(monkeypatch: pytest.MonkeyPatch):
    from app.ui.components import layout

    signed_out: list[bool] = []
    reran: list[bool] = []

    monkeypatch.setattr(layout.session, "sign_out", lambda: signed_out.append(True))
    monkeypatch.setattr(layout.st, "rerun", lambda: reran.append(True))
    monkeypatch.setattr(layout.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(layout.st, "error", lambda *a, **k: None)

    layout.show_error(ApiError("UNAUTHENTICATED", "פג תוקף החיבור.", status=401))

    assert signed_out == [True]
    assert reran == [True], "clearing the session is not enough: the shell already routed"


def test_an_ordinary_error_does_not_sign_the_user_out(monkeypatch: pytest.MonkeyPatch):
    """A validation mistake must not end the session.

    Treating every failure as an auth failure would log a user out for typing a
    bad value into a form.
    """
    from app.ui.components import layout

    signed_out: list[bool] = []
    errors: list[str] = []

    monkeypatch.setattr(layout.session, "sign_out", lambda: signed_out.append(True))
    monkeypatch.setattr(layout.st, "rerun", lambda: pytest.fail("must not rerun"))
    monkeypatch.setattr(layout.st, "error", lambda message, **k: errors.append(message))
    monkeypatch.setattr(layout.st, "caption", lambda *a, **k: None)

    layout.show_error(ApiError("VALIDATION_FAILED", "פרטים לא תקינים.", status=422))

    assert signed_out == []
    assert errors == ["פרטים לא תקינים."]


def test_a_401_without_the_code_is_still_an_auth_error():
    """The property keys on either signal, because a proxy or a dependency can
    produce a bare 401 with no envelope of ours behind it."""
    assert ApiError("SOMETHING_ELSE", "x", status=401).is_auth_error
    assert ApiError("UNAUTHENTICATED", "x").is_auth_error
    assert not ApiError("NOT_FOUND", "x", status=404).is_auth_error
