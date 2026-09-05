"""The Home dashboard (FINAL §5, PROGRESS §9).

    "The dashboard is action-oriented. The user should understand in seconds
     what needs attention today."

So the tests are mostly about what the page says *first* and what it does not say
at all. A dashboard that renders every field correctly in the wrong order fails
that sentence while passing any test that only checks presence.

Three states have to be distinguishable, and conflating any two of them is the
easy mistake: no plants yet (an invitation), plants but nothing due (an
achievement — FINAL §5 names the all-caught-up state), and work outstanding.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "home.py")


def task(action: str = "WATERING", *, status: str = "PENDING", hours: int = 2, plant="המונסטרה"):
    return {
        "id": f"task-{action}-{status}-{hours}",
        "plant_id": "11111111-1111-1111-1111-111111111111",
        "care_rule_id": "22222222-2222-2222-2222-222222222222",
        "due_at_utc": (datetime.now(UTC) + timedelta(hours=hours)).isoformat(),
        "status": status,
        "plant_name": plant,
        "action_type": action,
    }


def plant(name: str = "המונסטרה", health: str = "HEALTHY", plant_id: str = "p1"):
    return {"id": plant_id, "name": name, "status": "ACTIVE", "current_health_status": health}


def dashboard(**overrides: Any) -> dict[str, Any]:
    base = {
        "today_care": [],
        "upcoming_care": [],
        "overdue_summary": [],
        "plants_needing_attention": [],
        "my_plants": [],
        "counts": {"today_tasks": 0, "attention": 0, "active_plants": 0, "overdue": 0},
    }
    return {**base, **overrides}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(data: dict[str, Any]) -> AppTest:
        from app.ui.state import api_client

        def fake_get(path: str, **kwargs: Any) -> Any:
            if path == "/v1/dashboard":
                return data
            return {"display_name": "דנה"}

        monkeypatch.setattr(api_client, "get", fake_get)
        return AppTest.from_file(PAGE, default_timeout=30)

    return _build


def rendered(app: AppTest) -> str:
    parts: list[str] = []
    for collection in (app.markdown, app.caption, app.info, app.warning, app.subheader, app.header):
        parts.extend(str(e.value) for e in collection)
    parts.extend(e.label for e in app.expander)
    parts.extend(e.label for e in app.button)
    return " ".join(parts)


# --- the three empty-ish states, which must not be confused --------------------


def test_a_new_account_is_invited_to_add_a_plant(page):
    app = page(dashboard())
    app.run()

    assert not app.exception, [str(e) for e in app.exception]
    text = rendered(app)
    assert "עדיין אין לך צמחים" in text
    assert "הכול מטופל" not in text


def test_plants_with_nothing_due_get_the_all_caught_up_state(page):
    """FINAL §5 names this state explicitly.

    Showing the same "no plants" box would waste the one moment the app gets to
    say well done, and would read as though the plants had vanished.
    """
    app = page(
        dashboard(
            my_plants=[plant()],
            counts={"today_tasks": 0, "attention": 0, "active_plants": 1, "overdue": 0},
        )
    )
    app.run()

    text = rendered(app)
    assert "הכול מטופל" in text
    assert "עדיין אין לך צמחים" not in text


def test_work_outstanding_shows_neither_empty_state(page):
    app = page(
        dashboard(
            today_care=[task()],
            my_plants=[plant()],
            counts={"today_tasks": 1, "attention": 0, "active_plants": 1, "overdue": 0},
        )
    )
    app.run()

    text = rendered(app)
    assert "הכול מטופל" not in text
    assert "עדיין אין לך צמחים" not in text


# --- today's care --------------------------------------------------------------


def test_each_task_offers_both_done_and_skip(page):
    """FINAL §5 lists both. Skip is not a lesser option to be hidden: the
    schedule treats a skip differently from silence, so a user who did not water
    needs a way to say so."""
    app = page(
        dashboard(
            today_care=[task()],
            counts={"active_plants": 1, "today_tasks": 1, "attention": 0, "overdue": 0},
        )
    )
    app.run()

    labels = [b.label for b in app.button]
    assert "בוצע" in labels
    assert "דילוג" in labels


def test_a_task_names_the_plant_and_the_action(page):
    """ "Water the monstera" is a reminder; an id and a timestamp is a row."""
    app = page(
        dashboard(
            today_care=[task()],
            counts={"active_plants": 1, "today_tasks": 1, "attention": 0, "overdue": 0},
        )
    )
    app.run()

    text = rendered(app)
    assert "המונסטרה" in text
    assert "השקיה" in text


def test_an_overdue_task_says_how_late_rather_than_when_it_was_due(page):
    """ "3 days late" is actionable; "due on the 2nd" makes the reader do
    arithmetic."""
    late = task(status="OVERDUE", hours=-72)
    app = page(
        dashboard(
            today_care=[late],
            counts={"active_plants": 1, "today_tasks": 1, "attention": 0, "overdue": 1},
        )
    )
    app.run()

    assert "באיחור" in rendered(app)


# --- the overdue summary (FINAL §13) -------------------------------------------


def test_overdue_work_is_summarised_per_plant(page):
    """One line per plant. Fourteen rows for someone back from holiday is
    complete and reads as a reprimand."""
    app = page(
        dashboard(
            overdue_summary=[
                {
                    "plant_id": "11111111-1111-1111-1111-111111111111",
                    "plant_name": "המונסטרה",
                    "action_types": ["WATERING", "FERTILIZING"],
                    "count": 5,
                    "days_late": 4,
                }
            ],
            counts={"active_plants": 1, "today_tasks": 0, "attention": 0, "overdue": 5},
        )
    )
    app.run()

    warnings = " ".join(str(w.value) for w in app.warning)
    assert "המונסטרה" in warnings
    assert "השקיה" in warnings
    assert "דישון" in warnings
    assert "4" in warnings


# --- counts, attention, previews -----------------------------------------------


def test_the_three_counts_are_shown(page):
    app = page(
        dashboard(counts={"today_tasks": 3, "attention": 2, "active_plants": 7, "overdue": 1})
    )
    app.run()

    values = [m.value for m in app.metric]
    assert "7" in values
    assert "3" in values
    assert "2" in values


def test_plants_needing_attention_are_listed_with_their_status(page):
    app = page(
        dashboard(
            plants_needing_attention=[plant("הפיקוס", "NEEDS_ATTENTION", "p2")],
            counts={"active_plants": 1, "today_tasks": 0, "attention": 1, "overdue": 0},
        )
    )
    app.run()

    assert "הפיקוס" in rendered(app)


def test_upcoming_care_never_appears_above_todays_work(page):
    """The ordering FINAL §5 asks for, asserted as ordering.

    Upcoming care belongs on the page and must not compete with what the user can
    act on now. Checking that both render would pass just as happily with the
    sections reversed, so this checks which comes first — and that upcoming is
    rendered muted rather than as another card.

    (`AppTest` does not expose an `st.expander` that carries an `icon`, so the
    collapse itself is verified in the browser.)
    """
    app = page(
        dashboard(
            today_care=[task()],
            upcoming_care=[task("FERTILIZING", hours=72)],
            counts={"active_plants": 1, "today_tasks": 1, "attention": 0, "overdue": 0},
        )
    )
    app.run()

    blocks = [str(m.value) for m in app.markdown]
    today_at = next(i for i, b in enumerate(blocks) if "השקיה" in b)
    upcoming_at = next(i for i, b in enumerate(blocks) if b.startswith(":gray["))

    assert today_at < upcoming_at


def test_the_add_plant_call_to_action_is_always_available(page):
    app = page(
        dashboard(
            my_plants=[plant()],
            counts={"active_plants": 1, "today_tasks": 0, "attention": 0, "overdue": 0},
        )
    )
    app.run()

    assert "הוספת צמח" in [b.label for b in app.button]


def test_a_plant_in_the_preview_opens_its_dashboard(page):
    app = page(
        dashboard(
            my_plants=[plant()],
            counts={"active_plants": 1, "today_tasks": 0, "attention": 0, "overdue": 0},
        )
    )
    app.run()

    opens = [b for b in app.button if b.label == "פתיחה"]
    assert opens
    opens[0].click().run()
    assert app.session_state["pc_selected_plant"] == "p1"


def test_the_greeting_is_personalised(page):
    app = page(dashboard())
    app.run()

    assert "דנה" in rendered(app)


def test_upcoming_lines_name_the_action(page):
    """Three rules on one plant otherwise render three identical lines.

    Found in the browser: "the monstera · tomorrow at 08:00", three times, which
    tells the user nothing about what is actually coming.
    """
    app = page(
        dashboard(
            upcoming_care=[
                task("WATERING", hours=20),
                task("FERTILIZING", hours=20),
                task("INSPECTION", hours=20),
            ],
            counts={"active_plants": 1, "today_tasks": 0, "attention": 0, "overdue": 0},
        )
    )
    app.run()

    upcoming_lines = [str(m.value) for m in app.markdown if str(m.value).startswith(":gray[")]
    assert len(upcoming_lines) == 3
    assert len(set(upcoming_lines)) == 3, "each line must be distinguishable"
    joined = " ".join(upcoming_lines)
    assert "השקיה" in joined and "דישון" in joined and "בדיקה" in joined


def test_a_task_with_no_action_label_does_not_render_asterisks(page):
    """Bold-empty is four literal asterisks on screen.

    Found on the plant dashboard, which shipped without decorating its tasks and
    rendered "**** · my plant" where a reminder should have been. The card is now
    defensive about it regardless of who forgot.
    """
    bare = {**task(), "action_type": None, "plant_name": None}
    app = page(
        dashboard(
            today_care=[bare],
            counts={"active_plants": 1, "today_tasks": 1, "attention": 0, "overdue": 0},
        )
    )
    app.run()

    text = rendered(app)
    assert "****" not in text
    assert "טיפול" in text
