"""The client half of "view as user".

The API refuses writes and confines reads; those are tested elsewhere. What can only
break here is the part an administrator actually experiences:

* the header goes out on **every** request, because it is added at one chokepoint;
* cached reads are keyed on the viewed user, or the admin is served their own plants
  while believing they are looking at somebody else's - the same defect as leaking
  between accounts, and harder to notice because both answers look plausible;
* the banner is on screen the whole time, and leaving actually leaves.

The nav switch itself is a property of `/v1/me` returning the viewed profile, which
the integration suite asserts.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ui.state import view_as
from app.ui.state.api_client import ACT_AS_KEY

TARGET = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch):
    """A stand-in for `st.session_state` that behaves like a dict.

    `view_as` and `api_client` both reach for the real one, which needs a script run
    context these tests do not have.
    """
    store: dict[str, Any] = {}

    from app.ui.state import api_client

    monkeypatch.setattr(api_client.st, "session_state", store, raising=False)
    monkeypatch.setattr(view_as.st, "session_state", store, raising=False)
    return store


# --- the header ------------------------------------------------------------------


def test_no_header_when_the_mode_is_off(state, monkeypatch):
    from app.ui.state import api_client

    monkeypatch.setattr(api_client.session, "access_token", lambda: "tok")

    assert "X-Act-As-User" not in api_client._headers()


def test_the_header_goes_out_on_every_request_when_the_mode_is_on(state, monkeypatch):
    """One chokepoint, so no page can forget it. A screen that dropped the header
    would show the admin their own account inside somebody else's session."""
    from app.ui.state import api_client

    monkeypatch.setattr(api_client.session, "access_token", lambda: "tok")
    state[ACT_AS_KEY] = TARGET

    headers = api_client._headers()

    assert headers["X-Act-As-User"] == TARGET
    # The credential is still the administrator's - that is what puts the admin RLS
    # policies in force for the reads.
    assert headers["Authorization"] == "Bearer tok"


# --- the cache -------------------------------------------------------------------


def test_cached_reads_are_keyed_on_the_viewed_user(state, monkeypatch):
    """The bug this design produces if missed: the signed-in admin does not change
    when the mode is entered, so a key of `user_key()` alone would serve them their
    own cached plants."""
    from app.ui.state import api_client

    keys: list[str] = []

    monkeypatch.setattr(api_client.session, "user_key", lambda: "admin-key")
    monkeypatch.setattr(api_client, "_cached", lambda identity, path, params: keys.append(identity))

    api_client.cached_get("/v1/plants")
    state[ACT_AS_KEY] = TARGET
    api_client.cached_get("/v1/plants")

    assert keys[0] != keys[1], "the same cache entry served two different accounts"
    assert TARGET in keys[1]


def test_two_different_viewed_users_do_not_share_a_cache_entry(state, monkeypatch):
    from app.ui.state import api_client

    keys: list[str] = []
    monkeypatch.setattr(api_client.session, "user_key", lambda: "admin-key")
    monkeypatch.setattr(api_client, "_cached", lambda identity, path, params: keys.append(identity))

    state[ACT_AS_KEY] = TARGET
    api_client.cached_get("/v1/plants")
    state[ACT_AS_KEY] = "99999999-2222-3333-4444-555555555555"
    api_client.cached_get("/v1/plants")

    assert keys[0] != keys[1]


# --- entering and leaving ---------------------------------------------------------


def test_entering_records_the_target_and_refreshes(state, monkeypatch):
    cleared: list[bool] = []
    monkeypatch.setattr(view_as, "clear_cache", lambda: cleared.append(True))
    monkeypatch.setattr(view_as.st, "rerun", lambda: None)

    view_as.enter(TARGET, "owner@example.com")

    assert state[ACT_AS_KEY] == TARGET
    assert view_as.active()
    assert view_as.target_email() == "owner@example.com"
    assert cleared, "the first screen would otherwise be up to five minutes stale"


def test_leaving_clears_the_mode(state, monkeypatch):
    monkeypatch.setattr(view_as, "clear_cache", lambda: None)
    monkeypatch.setattr(view_as.st, "rerun", lambda: None)
    state.update({ACT_AS_KEY: TARGET, view_as.EMAIL_KEY: "owner@example.com"})

    view_as.leave()

    assert not view_as.active()
    assert view_as.active_target() is None


def test_leaving_forgets_the_users_selected_plant(state, monkeypatch):
    """Otherwise the admin's own plant page opens on a plant belonging to somebody
    else, which they cannot read - a 404 with no explanation."""
    monkeypatch.setattr(view_as, "clear_cache", lambda: None)
    monkeypatch.setattr(view_as.st, "rerun", lambda: None)
    state.update({ACT_AS_KEY: TARGET, "pc_selected_plant": "someone-elses-plant"})

    view_as.leave()

    assert "pc_selected_plant" not in state
