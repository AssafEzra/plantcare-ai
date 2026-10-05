"""Registering, pausing and removing push devices; the preference fields."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from tests.unit.fake_db import FakeDB

OWNER = "00000000-0000-0000-0000-0000000000aa"
STRANGER = "00000000-0000-0000-0000-0000000000bb"


class _User:
    def __init__(self, client: FakeDB, user_id: str = OWNER):
        self.client = client
        self.id = user_id


class _Request:
    class state:  # noqa: N801 - mimics starlette's request.state
        request_id = "req"


class Recorder:
    name = "recorder"
    suppresses = False

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def send(self, target, payload):
        from app.infrastructure.push.provider import PushResult

        self.sent.append((target.endpoint, payload))
        return PushResult.OK


@pytest.fixture
def push(env, monkeypatch):
    from app.api.routers import push

    recorder = Recorder()
    released: list[str] = []
    monkeypatch.setattr(push, "build_push_provider", lambda: recorder)
    monkeypatch.setattr(push, "_release_endpoint", released.append)
    push.recorder = recorder  # type: ignore[attr-defined]
    push.released = released  # type: ignore[attr-defined]
    return push


def body(endpoint: str = "https://fcm.googleapis.com/fcm/send/abc", **extra: Any):
    from app.api.routers.push import SubscribeRequest

    return SubscribeRequest.model_validate(
        {
            "endpoint": endpoint,
            "keys": {"p256dh": "key", "auth": "secret"},
            "expirationTime": None,
            "device_label": "Android · Chrome",
            "platform": "android",
            **extra,
        }
    )


def db_with_timestamps() -> FakeDB:
    db = FakeDB({"push_subscriptions": []})
    original = db.table

    def table(name: str):
        query = original(name)
        insert = query.insert

        def insert_with_defaults(values):
            return insert({"created_at": "2026-10-06T07:00:00+00:00", **values})

        query.insert = insert_with_defaults  # type: ignore[method-assign]
        return query

    db.table = table  # type: ignore[method-assign]
    return db


async def test_registering_stores_the_device_and_sends_one_confirmation(push):
    db = db_with_timestamps()

    response = await push.subscribe(_Request(), body(), _User(db))

    assert len(db.store["push_subscriptions"]) == 1
    assert response.data.platform == "android" and response.data.enabled
    assert len(push.recorder.sent) == 1
    assert push.recorder.sent[0][1]["title"].startswith("🌱")


async def test_registering_again_updates_rather_than_duplicates(push):
    """The app re-sends its subscription on every open, so a renewed key reaches
    the server. That must not create a second row or a second confirmation."""
    db = db_with_timestamps()
    await push.subscribe(_Request(), body(), _User(db))

    from app.api.routers.push import SubscribeRequest

    renewed = SubscribeRequest.model_validate(
        {"endpoint": body().endpoint, "keys": {"p256dh": "new-key", "auth": "new"}}
    )
    await push.subscribe(_Request(), renewed, _User(db))

    assert len(db.store["push_subscriptions"]) == 1
    assert db.store["push_subscriptions"][0]["p256dh"] == "new-key"
    assert len(push.recorder.sent) == 1


async def test_a_paused_device_can_be_resumed_from_anywhere(push):
    db = db_with_timestamps()
    created = await push.subscribe(_Request(), body(), _User(db))
    device_id = created.data.id

    from app.api.routers.push import ToggleRequest

    paused = await push.toggle(_Request(), device_id, ToggleRequest(enabled=False), _User(db))
    resumed = await push.toggle(_Request(), device_id, ToggleRequest(enabled=True), _User(db))

    assert paused.data.enabled is False and resumed.data.enabled is True


async def test_nobody_can_touch_another_users_device(push):
    from app.api.routers.push import ToggleRequest
    from app.common.errors import NotFoundError

    db = db_with_timestamps()
    created = await push.subscribe(_Request(), body(), _User(db))

    with pytest.raises(NotFoundError):
        await push.toggle(
            _Request(), created.data.id, ToggleRequest(enabled=False), _User(db, STRANGER)
        )
    with pytest.raises(NotFoundError):
        await push.remove(created.data.id, _User(db, STRANGER))
    assert len(db.store["push_subscriptions"]) == 1


async def test_signing_out_removes_this_device_by_its_endpoint(push):
    from app.api.routers.push import UnsubscribeRequest

    db = db_with_timestamps()
    await push.subscribe(_Request(), body("https://push.example/phone"), _User(db))
    await push.subscribe(_Request(), body("https://push.example/tablet"), _User(db))

    await push.unsubscribe(UnsubscribeRequest(endpoint="https://push.example/phone"), _User(db))

    assert [d["endpoint"] for d in db.store["push_subscriptions"]] == [
        "https://push.example/tablet"
    ]


async def test_the_device_list_never_returns_the_encryption_keys(push):
    db = db_with_timestamps()
    await push.subscribe(_Request(), body(), _User(db))

    listed = await push.list_devices(_Request(), _User(db))

    dumped = listed.data[0].model_dump()
    assert "p256dh" not in dumped and "auth" not in dumped
    assert listed.data[0].endpoint == body().endpoint


async def test_reopening_the_app_does_not_unpause_a_device_paused_elsewhere(push):
    """The app re-sends its subscription on open with resume=false. Pausing the
    phone from the laptop must survive the phone being opened."""
    from app.api.routers.push import ToggleRequest

    db = db_with_timestamps()
    created = await push.subscribe(_Request(), body(), _User(db))
    await push.toggle(_Request(), created.data.id, ToggleRequest(enabled=False), _User(db))

    resynced = await push.subscribe(_Request(), body(resume=False), _User(db))

    assert resynced.data.enabled is False
    assert len(push.recorder.sent) == 1  # only the first registration's confirmation


async def test_turning_a_paused_device_back_on_from_the_phone_confirms_it(push):
    from app.api.routers.push import ToggleRequest

    db = db_with_timestamps()
    created = await push.subscribe(_Request(), body(), _User(db))
    await push.toggle(_Request(), created.data.id, ToggleRequest(enabled=False), _User(db))

    resumed = await push.subscribe(_Request(), body(), _User(db))

    assert resumed.data.enabled is True
    assert len(push.recorder.sent) == 2


async def test_a_new_owner_of_a_phone_takes_over_its_address(push):
    """A previous user's row can survive a sign-out that failed offline; the new
    owner's registration frees that endpoint first instead of hitting the index."""
    db = db_with_timestamps()

    await push.subscribe(_Request(), body("https://push.example/shared"), _User(db, STRANGER))

    assert push.released == ["https://push.example/shared"]


def test_an_endpoint_must_be_https(push):
    with pytest.raises(ValidationError):
        body("http://insecure.example/x")


# --- preferences ----------------------------------------------------------------


def test_due_days_are_limited_to_zero_through_three(env):
    from app.api.routers.notifications import PreferencesRequest

    assert PreferencesRequest(due_reminder_days=0).due_reminder_days == 0
    assert PreferencesRequest(due_reminder_days=3).due_reminder_days == 3
    with pytest.raises(ValidationError):
        PreferencesRequest(due_reminder_days=4)


def test_the_hidden_settings_are_refused_rather_than_ignored(env):
    """The time is fixed for now and per-task email is gone. A client still sending
    either gets told so, instead of a 200 that changed nothing."""
    from app.api.routers.notifications import PreferencesRequest

    for retired in ({"preferred_time_local": "09:00"}, {"daily_digest": False}):
        with pytest.raises(ValidationError):
            PreferencesRequest.model_validate(retired)
