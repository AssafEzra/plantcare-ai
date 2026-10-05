"""Care intensity at the API edge: what the screens send and what they are shown."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from tests.unit.fake_db import FakeDB

# --- PATCH /v1/me -------------------------------------------------------------------


def test_medium_takes_exactly_two_different_days(env):
    from app.api.schemas.profile import ProfileUpdateRequest

    assert ProfileUpdateRequest(care_days_medium=["TUESDAY", "FRIDAY"]).care_days_medium

    for bad in (["FRIDAY"], ["FRIDAY", "FRIDAY"], ["MONDAY", "TUESDAY", "FRIDAY"]):
        with pytest.raises(ValidationError):
            ProfileUpdateRequest(care_days_medium=bad)


def test_an_unknown_level_is_refused(env):
    from app.api.schemas.profile import ProfileUpdateRequest

    with pytest.raises(ValidationError):
        ProfileUpdateRequest(care_intensity="EXTREME")


# --- PATCH /v1/plants/{id} ----------------------------------------------------------


def test_null_follows_settings_and_is_not_the_same_as_leaving_it_out(env):
    """The route dumps with exclude_unset: an explicit null must reach the database
    (clear the override), while an absent field must not touch it."""
    from app.api.schemas.plants import PlantUpdateRequest

    cleared = PlantUpdateRequest.model_validate({"care_intensity": None})
    untouched = PlantUpdateRequest.model_validate({"name": "Monstera"})

    assert cleared.model_dump(mode="json", exclude_unset=True) == {"care_intensity": None}
    assert "care_intensity" not in untouched.model_dump(mode="json", exclude_unset=True)


# --- what the plant card is shown ---------------------------------------------------


def owner(intensity: str = "LOW"):
    from app.orchestration.services.scheduler import OwnerCareSettings

    return OwnerCareSettings(
        timezone="Asia/Jerusalem",
        intensity=intensity,
        care_day_low="FRIDAY",
        care_days_medium=["TUESDAY", "FRIDAY"],
    )


RULES = [
    {"action_type": "WATERING", "interval_days": 3, "is_active": True},
    {"action_type": "FERTILIZING", "interval_days": 30, "is_active": True},
]


def test_a_plant_following_low_is_warned_about_its_three_day_watering(env):
    from app.orchestration.services.care_intensity import plant_summary

    summary = plant_summary(owner(), plant_override=None, rules=RULES)

    assert summary["effective"] == "LOW"
    assert summary["care_days"] == ["FRIDAY"]
    assert [w["action_type"] for w in summary["warnings"]] == ["WATERING"]


def test_the_same_plant_pinned_to_high_has_no_line_and_no_warning(env):
    from app.orchestration.services.care_intensity import plant_summary

    summary = plant_summary(owner(), plant_override="HIGH", rules=RULES)

    assert summary["effective"] == "HIGH"
    assert summary["care_days"] == []
    assert summary["warnings"] == []
    assert summary["owner_intensity"] == "LOW"


# --- GET /v1/care-intensity/impact --------------------------------------------------


def test_impact_lists_affected_plants_and_skips_pinned_ones(env, monkeypatch):
    from app.common.enums import CareIntensity, Weekday
    from app.orchestration.services import care_intensity

    db = FakeDB(
        {
            "plants": [
                {
                    "id": "p1",
                    "user_id": "u",
                    "name": "Fern",
                    "status": "ACTIVE",
                    "care_intensity": None,
                },
                {
                    "id": "p2",
                    "user_id": "u",
                    "name": "Cactus",
                    "status": "ACTIVE",
                    "care_intensity": None,
                },
                {
                    "id": "p3",
                    "user_id": "u",
                    "name": "Pinned",
                    "status": "ACTIVE",
                    "care_intensity": "HIGH",
                },
            ]
        }
    )
    plans: dict[str, Any] = {
        "p1": {"rules": [{"action_type": "WATERING", "interval_days": 2, "is_active": True}]},
        "p2": {"rules": [{"action_type": "WATERING", "interval_days": 14, "is_active": True}]},
        "p3": {"rules": [{"action_type": "WATERING", "interval_days": 1, "is_active": True}]},
    }
    monkeypatch.setattr(
        care_intensity.care_workflow, "plan_for_plant", lambda _c, *, plant_id: plans[plant_id]
    )

    affected = care_intensity.impact(
        db,
        user_id="u",
        intensity=CareIntensity.MEDIUM,
        care_day_low=Weekday.FRIDAY,
        care_days_medium=[Weekday.TUESDAY, Weekday.FRIDAY],
    )

    assert [a["plant_name"] for a in affected] == ["Fern"]
    assert affected[0]["tasks"][0]["max_gap_days"] == 4


def test_impact_of_high_is_nothing(env):
    from app.common.enums import CareIntensity, Weekday
    from app.orchestration.services import care_intensity

    assert (
        care_intensity.impact(
            FakeDB(),
            user_id="u",
            intensity=CareIntensity.HIGH,
            care_day_low=Weekday.FRIDAY,
            care_days_medium=[Weekday.TUESDAY, Weekday.FRIDAY],
        )
        == []
    )


# --- saving re-dates pending tasks ----------------------------------------------------


OWNER = "00000000-0000-0000-0000-0000000000aa"


class _User:
    def __init__(self, client: FakeDB):
        self.client = client
        self.id = OWNER


class _Request:
    class state:  # noqa: N801 - mimics starlette's request.state
        request_id = "req"


async def test_saving_the_setting_reschedules_and_unrelated_edits_do_not(env, monkeypatch):
    from app.api.routers import profile
    from app.api.schemas.profile import ProfileUpdateRequest

    db = FakeDB(
        {
            "profiles": [
                {
                    "id": OWNER,
                    "role": "USER",
                    "timezone": "Asia/Jerusalem",
                    "locale": "he",
                    "is_active": True,
                    "created_at": "2026-10-01T00:00:00+00:00",
                    "care_intensity": "HIGH",
                }
            ]
        }
    )
    calls: list[str] = []
    monkeypatch.setattr(
        profile.scheduler,
        "reschedule_pending",
        lambda _c, *, user_id, now_utc: calls.append(user_id),
    )

    await profile.update_me(_Request(), ProfileUpdateRequest(display_name="Dana"), _User(db))
    assert calls == []

    response = await profile.update_me(
        _Request(), ProfileUpdateRequest(care_intensity="LOW"), _User(db)
    )
    assert calls == [OWNER]
    assert response.data.care_intensity == "LOW"


async def test_changing_a_plants_override_reschedules_that_plant(env, monkeypatch):
    from app.api.routers import plants
    from app.api.schemas.plants import PlantUpdateRequest

    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "user_id": OWNER,
        "status": "ACTIVE",
        "current_health_status": "UNKNOWN",
        "created_at": "2026-10-01T00:00:00+00:00",
        "updated_at": "2026-10-01T00:00:00+00:00",
        "care_intensity": None,
    }
    db = FakeDB({"plants": [row]})
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        plants.scheduler,
        "reschedule_pending",
        lambda _c, *, user_id, plant_id, now_utc: calls.append((user_id, plant_id)),
    )

    from uuid import UUID

    await plants.update_plant(
        _Request(),
        UUID(row["id"]),
        PlantUpdateRequest.model_validate({"care_intensity": "HIGH"}),
        _User(db),
    )

    assert calls == [(OWNER, row["id"])]
    assert db.store["plants"][0]["care_intensity"] == "HIGH"
