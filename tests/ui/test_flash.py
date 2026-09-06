"""Confirmations that the reader can actually see (PR 33).

Reported from real use: pressing שמירת השינוי appeared to do nothing. It had
worked - the message was written at the top of the page while the user was at the
bottom of it. `show_flash()` is called just under `page_header`, the controls that
park messages sit hundreds of pixels below, and Streamlit keeps the scroll
position across the rerun that renders it. The plant dashboard alone parks 23 of
them, so this was never one screen's problem.

`st.toast` is anchored to the viewport rather than the document, so it shows
wherever the reader is standing. The inline box stays, because a toast dismisses
itself and several of these messages say what has to happen next.

The helper also used to be copied into three pages - three places for one
behaviour to drift. It lives in `layout.py` now, and these tests are about the one
implementation.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV


def render(kind, message, twice):
    import streamlit as st

    from app.ui.components.layout import flash, pending_flash, show_flash

    flash(message, kind=kind, icon=":material/pending_actions:")
    st.session_state["pending_before"] = pending_flash()
    show_flash()
    st.session_state["pending_after"] = pending_flash()
    if twice:
        show_flash()


@pytest.fixture
def flashed(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(kind: str = "info", message: str = "השינוי נשמר כהצעה.", twice: bool = False):
        app = AppTest.from_function(
            render,
            kwargs={"kind": kind, "message": message, "twice": twice},
            default_timeout=30,
        )
        app.run()
        assert not app.exception, [str(e) for e in app.exception]
        return app

    return _build


def test_a_message_is_shown_where_the_reader_is(flashed):
    """The toast is the whole point. Anchored to the viewport, it does not care
    that the action was taken eight hundred pixels below the place the inline box
    renders."""
    app = flashed()

    assert app.toast, "no toast - the message is only visible at the top of the page"
    assert "השינוי נשמר כהצעה." in str(app.toast[0].value)


def test_and_still_where_it_persists(flashed):
    """A toast dismisses itself after a few seconds, and several of these messages
    say what has to happen next. Someone who looked away should still find out."""
    app = flashed()

    assert "השינוי נשמר כהצעה." in " ".join(str(i.value) for i in app.info)


@pytest.mark.parametrize(
    ("kind", "collection"),
    [("success", "success"), ("info", "info"), ("warning", "warning")],
)
def test_each_kind_renders_as_itself(flashed, kind, collection):
    app = flashed(kind=kind)

    assert getattr(app, collection), f"a {kind} flash did not render as one"


def test_it_is_shown_once(flashed):
    """Popped, not read. A message that survived its own rendering would follow
    the user to the next page they opened."""
    app = flashed(twice=True)

    assert len(app.info) == 1
    assert len(app.toast) == 1


def test_pending_flash_reports_the_message_waiting(flashed):
    """What holds the adjustment expander open across the rerun, so the form the
    user just filled in does not vanish along with the confirmation."""
    app = flashed()

    assert app.session_state["pending_before"] is True
    assert app.session_state["pending_after"] is False
