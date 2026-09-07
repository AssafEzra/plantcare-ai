"""The cookie is read from the browser when it does not arrive with the request.

Regression for the deployed app: on Streamlit Community Cloud a refresh returned
the user to the sign-in form. Diagnosed on 2026-09-07 against the live app — the
browser held a valid `pc_refresh_token`, that exact token was unrevoked in
`auth.refresh_tokens`, and the sign-in form rendered anyway, so `refresh_session`
was never reached and `st.context.cookies` had come back empty.

These tests pin the two halves of the fix: the fallback read, and the fact that a
pending answer is not the same as "signed out".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch):
    import streamlit as st

    from app.ui.components import session_store

    state: dict = {}
    monkeypatch.setattr(st, "session_state", state, raising=False)
    monkeypatch.setattr(session_store.st, "session_state", state, raising=False)

    # `st.context.cookies` empty is exactly the deployed condition.
    monkeypatch.setattr(session_store.st, "context", SimpleNamespace(cookies={}), raising=False)

    reported: dict = {"token": None}
    monkeypatch.setattr(
        session_store,
        "_mount",
        lambda op, token: SimpleNamespace(token=reported["token"]),
    )

    return SimpleNamespace(module=session_store, state=state, reported=reported)


def test_a_silent_component_is_not_yet_an_answer(store):
    """`None` means the browser has not replied, and the caller must wait."""
    assert store.module.read() is None
    assert store.module.awaiting() is True


def test_an_empty_reply_is_an_answer(store):
    """An empty string means "asked, nothing stored" - stop waiting.

    The distinction matters: conflating it with silence would hold every
    signed-out visitor on a spinner instead of showing them the sign-in form.
    """
    store.reported["token"] = ""

    assert store.module.read() is None
    assert store.module.awaiting() is False


def test_the_token_comes_back_from_the_browser(store):
    store.reported["token"] = "kzm4vqjx7abc"

    assert store.module.read() == "kzm4vqjx7abc"
    assert store.module.awaiting() is False


def test_waiting_is_bounded(store):
    """A component that never reports must not hold the page for ever."""
    for _ in range(store.module._MAX_WAITS + 1):
        store.module.read()

    assert store.module.awaiting() is False


def test_the_request_header_still_wins_when_it_has_the_cookie(store, monkeypatch):
    """The fast path is kept: where it works there is no rerun and no waiting."""
    monkeypatch.setattr(
        store.module.st,
        "context",
        SimpleNamespace(cookies={"pc_refresh_token": "abc123"}),
        raising=False,
    )
    store.reported["token"] = "from-the-browser"

    assert store.module.read() == "abc123"
    assert store.module.awaiting() is False
