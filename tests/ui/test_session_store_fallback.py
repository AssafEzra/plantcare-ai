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


def test_the_cookie_lives_twelve_hours_and_the_js_carries_it():
    """The idle window, pinned to the number FINAL 22 states.

    No test can watch twelve hours pass, so this pins the written value against the
    spec sentence and claims nothing more. The second assertion is the one with
    teeth: the constant could be changed while the interpolation into `_JS` broke,
    and `document.cookie` without a `max-age` writes a cookie that dies with the
    browser tab - which presents as the sign-out-on-refresh bug this component was
    built to prevent.
    """
    from app.ui.components import session_store

    assert session_store.MAX_AGE_SECONDS == 60 * 60 * 12
    assert f"max-age={session_store.MAX_AGE_SECONDS}" in session_store._JS


# --- two operations in one script pass -----------------------------------------
#
# Reported from the deployed app: `StreamlitDuplicateElementKey` on every visit
# after it had been idle, clearable only with Rerun, and then back again.
#
# `restore()` reads the stored token and, when the refresh rejects it, clears it -
# both in one script pass. Every operation mounted under one key, so the pair was a
# duplicate element rather than a sign-out. Idle was the trigger because that is
# exactly when a stored token has expired.
#
# The tests above cannot see any of this: they replace `_mount` outright. These
# drive the real one, against a double that emulates the two things Streamlit and
# the browser actually do - refuse a repeated key within a pass, and run the
# component's cookie script.


class DuplicateKeyError(RuntimeError):
    """Stands in for `StreamlitDuplicateElementKey`."""


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch):
    import streamlit as st

    from app.ui.components import session_store

    state: dict = {}
    monkeypatch.setattr(st, "session_state", state, raising=False)
    monkeypatch.setattr(session_store.st, "session_state", state, raising=False)
    monkeypatch.setattr(session_store.st, "context", SimpleNamespace(cookies={}), raising=False)

    jar: dict[str, str | None] = {"cookie": None}
    keys: list[str] = []

    def mount(*, data, key, height, on_token_change):
        if key in keys:
            raise DuplicateKeyError(key)
        keys.append(key)

        # What `_JS` does: act on the operation, then report whatever the browser
        # holds afterwards - including "" for "asked, nothing there".
        op = data["op"]
        if op == "save" and data["token"]:
            jar["cookie"] = data["token"]
        elif op == "clear":
            jar["cookie"] = None
        return SimpleNamespace(token=jar["cookie"] if jar["cookie"] is not None else "")

    monkeypatch.setattr(session_store, "_renderer", lambda: mount)
    return SimpleNamespace(module=session_store, jar=jar, keys=keys, state=state)


def test_each_operation_mounts_a_distinct_element(browser):
    browser.module.write("refresh-1")
    browser.module.read()
    browser.module.clear()

    assert len(set(browser.keys)) == 3, f"operations shared an element: {browser.keys}"


def test_reading_then_clearing_in_one_pass_does_not_collide(browser):
    """The reported crash, at its smallest. A rejected token is read and then
    removed, and both happen before the script ends."""
    browser.jar["cookie"] = "expired-token"

    assert browser.module.read() == "expired-token"
    browser.module.clear()  # raised a duplicate-key error before the fix

    assert browser.jar["cookie"] is None


def test_the_clear_actually_removes_the_token(browser):
    """Why the failure repeated forever rather than once: the exception came before
    the clear's script ran, so the token it was removing survived and the next visit
    did the same thing."""
    browser.jar["cookie"] = "expired-token"

    browser.module.read()
    browser.module.clear()

    assert browser.jar["cookie"] is None, "the token that caused the failure survived it"


def test_a_pending_write_followed_by_a_read_does_not_collide(browser):
    """The same defect on a rarer path - `restore()` flushes a pending write before
    reading. Fixed by the same change, and worth pinning so it is not re-introduced
    by keying on anything narrower than the operation."""
    browser.module.write("refresh-1")

    assert browser.module.read() == "refresh-1"
