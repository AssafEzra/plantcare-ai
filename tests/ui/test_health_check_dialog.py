"""Starting a health check with a photograph taken now (PR 32).

Reported from real use: *"when starting a health check it should lead to a new
window and give option to load pic, not just select one"*.

The old form offered a multiselect over the plant's existing gallery and nothing
else. A health check is prompted by something just noticed, so the photograph
that shows it does not exist yet — and a plant whose gallery was empty reached a
dead end: "you need to upload a photograph first", with nothing there to upload
with.

`AppTest.from_function` renders the component on its own. The dialog body runs
inside `st.dialog`, which `AppTest` executes like any other callback, so the
widgets inside it are reachable by key.
"""

from __future__ import annotations

from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

GALLERY = [
    {"id": "img-1", "created_at": "2026-09-01T10:00:00Z"},
    {"id": "img-2", "created_at": "2026-09-04T10:00:00Z"},
]


def render(gallery, submitted):
    # No annotations: `AppTest.from_function` execs the source in a bare module,
    # so any name from this file's imports would be undefined at run time.
    import streamlit as st

    from app.ui.components.health_check_dialog import health_check_dialog, open_dialog

    open_dialog()
    st.session_state.setdefault("_seen", True)
    health_check_dialog(
        gallery,
        on_submit=lambda uploads, ids, note: submitted.append((uploads, ids, note)),
    )


@pytest.fixture
def dialog(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(gallery: list[dict[str, Any]] | None = None) -> AppTest:
        submitted: list[tuple] = []
        app = AppTest.from_function(
            render,
            kwargs={"gallery": gallery if gallery is not None else GALLERY, "submitted": submitted},
            default_timeout=30,
        )
        app.submitted = submitted  # type: ignore[attr-defined]
        return app

    return _build


def test_a_photograph_can_be_uploaded(dialog):
    """The whole point of the report. The old form had no uploader at all."""
    app = dialog()
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    keys = [w.key for w in app.get("file_uploader")]
    assert "pd_health_uploads" in keys, "there is no way to add a new photograph"


def test_an_empty_gallery_is_no_longer_a_dead_end(dialog):
    """A plant with no images could not be health-checked at all: the form said
    "upload a photograph first" and offered nothing to do it with."""
    app = dialog(gallery=[])
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    assert [w.key for w in app.get("file_uploader")] == ["pd_health_uploads"]
    assert not app.multiselect, "an empty gallery should not render a chooser"


def test_existing_images_can_still_be_chosen(dialog):
    """Both routes, not one replacing the other: a user comparing this week to
    last needs the older photograph in the same assessment."""
    app = dialog()
    app.run()

    assert app.multiselect(key="pd_health_images") is not None


def test_submitting_nothing_is_refused(dialog):
    app = dialog()
    app.run()

    submit = next(b for b in app.button if b.key == "pd_health_submit")
    assert submit.disabled, "a check with no images must not be sendable"


def test_choosing_a_gallery_image_enables_submission(dialog):
    app = dialog()
    app.run()
    app.multiselect(key="pd_health_images").select("img-1").run()

    submit = next(b for b in app.button if b.key == "pd_health_submit")
    assert not submit.disabled

    submit.click().run()
    assert app.submitted, "submitting did not reach the caller"  # type: ignore[attr-defined]
    uploads, ids, _note = app.submitted[0]  # type: ignore[attr-defined]
    assert uploads == []
    assert ids == ["img-1"]
