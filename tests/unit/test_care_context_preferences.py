"""The Care Agent sees the plant owner's preferences, and nobody else's.

`_preferences` read `notification_preferences` with `limit(1)` and no owner filter.
Under a user's own client RLS hid the problem. Under the service client - plans
queued by a knowledge publication, `execute_proposal_as_service` - it returned
whichever row came first, so one user's settings reached another user's plan.
"""

from __future__ import annotations

from tests.unit.fake_db import FakeDB


def test_only_the_owners_row_is_read(env):
    from app.orchestration.services.care_context import _preferences

    db = FakeDB(
        {
            "notification_preferences": [
                {"user_id": "someone-else", "preferred_time_local": "06:00", "daily_digest": False},
                {"user_id": "owner", "preferred_time_local": "19:30", "daily_digest": True},
            ]
        }
    )

    prefs = _preferences(db, "owner")

    assert prefs["preferred_time_local"] == "19:30"
    assert prefs["daily_digest"] is True


def test_an_owner_with_no_row_gets_nothing_rather_than_a_stranger(env):
    from app.orchestration.services.care_context import _preferences

    db = FakeDB({"notification_preferences": [{"user_id": "someone-else", "daily_digest": False}]})

    assert _preferences(db, "owner") == {}
