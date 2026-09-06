"""Taking a photograph rather than finding one (PR 33).

`st.file_uploader` was the only way in. On a phone that is already adequate - the
OS picker offers "Take Photo" - but on a desktop it means hunting for a file, and
on either it means leaving the app to get a picture of the thing you are looking
at right now. A health check in particular is *always* about something just
noticed.

Two behaviours worth defending, and both are here: a capture joins the batch only
when the user says so, and the uploader never goes away - the camera needs a
secure context and is simply absent when the browser refuses it, so it can never
be the only route in.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV


def render(kept):
    # No annotations and imports inside: `AppTest.from_function` execs the source
    # in a bare module, so any name from this file would be undefined.
    import streamlit as st

    from app.ui.components.image_picker import image_picker

    st.session_state.setdefault("pick_captured", list(kept))
    picked = image_picker(key_prefix="pick", max_images=4)
    st.session_state["picked_count"] = len(picked)


def fake_photo():
    """Stands in for the `UploadedFile` both widgets return.

    A real (tiny) PNG rather than a stub object, because the picker previews each
    kept capture with `st.image` and Streamlit decodes what it is given.
    """
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (4, 4), (60, 120, 60)).save(buffer, format="PNG")
    buffer.seek(0)
    buffer.name = "capture.png"
    return buffer


@pytest.fixture
def picker(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(kept: list | None = None) -> AppTest:
        app = AppTest.from_function(render, kwargs={"kept": kept or []}, default_timeout=30)
        app.run()
        assert not app.exception, [str(e) for e in app.exception]
        return app

    return _build


def test_both_ways_in_are_offered(picker):
    app = picker()

    labels = [t.label for t in app.tabs] if hasattr(app, "tabs") else []
    assert "pick_uploads" in [w.key for w in app.get("file_uploader")]
    assert any("צילום" in label for label in labels) or app.get("camera_input")


def test_the_uploader_is_always_there(picker):
    """The camera needs a secure context - `getUserMedia` is refused over plain
    http, which is a phone pointed at a development server on the LAN. If the
    camera were the only route, that user would have none."""
    app = picker()

    assert [w.key for w in app.get("file_uploader")] == ["pick_uploads"]


def test_a_kept_capture_is_counted(picker):
    app = picker(kept=[fake_photo()])

    assert app.session_state["picked_count"] == 1


def test_a_capture_can_be_removed(picker):
    """A mistimed shot has to be undoable, or the only way out of a bad batch is
    to abandon the whole screen."""
    app = picker(kept=[fake_photo(), fake_photo()])
    assert app.session_state["picked_count"] == 2

    next(b for b in app.button if b.key == "pick_drop_0").click().run()

    assert app.session_state["picked_count"] == 1


def test_the_camera_closes_once_the_batch_is_full(picker):
    """Four is the cap the API enforces. Letting a fifth be taken and refused on
    submit wastes the upload and the user's time."""
    app = picker(kept=[fake_photo() for _ in range(4)])

    assert app.session_state["picked_count"] == 4
    assert not app.get("camera_input"), "the camera is still offered past the cap"
