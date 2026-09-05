"""The admin review screen, via AppTest — headless, no browser, no API.

The page is the human step in "the Knowledge Agent never publishes" (FINAL §11),
so what is worth testing is not that it renders but that it renders the things a
reviewer needs in order to say no: the weak sections and the unverified sources.
A review screen that shows a polished draft and hides its shaky provenance would
make approval the path of least resistance, which is the opposite of the point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import REQUIRED_ENV

PAGE = str(Path(__file__).resolve().parents[2] / "app" / "ui" / "app_pages" / "admin.py")


def section(text: str = "טקסט מקצועי על הצמח הזה ועל הטיפול בו.", confidence: float = 0.9):
    return {"text": text, "confidence": confidence}


DRAFT: dict[str, Any] = {
    "id": "11111111-1111-1111-1111-111111111111",
    "species_id": "22222222-2222-2222-2222-222222222222",
    "language": "he",
    "status": "READY_FOR_REVIEW",
    "updated_at": "2026-09-05T08:00:00Z",
    "created_at": "2026-09-05T07:00:00Z",
    "research_notes": "המידע על הריבוי מבוסס על מקור אחד בלבד.",
    "content": {
        "sections": {
            "identification": section(),
            "description": section(),
            "light": section(),
            # The one a reviewer must not miss.
            "watering": section("ההמלצה כאן אינה מבוססת היטב.", 0.2),
            "soil": section(),
            "temperature": section(),
            "humidity": section(),
            "fertilization": section(),
            "repotting": section(),
            "pruning": section(),
            "propagation": section(),
            "common_problems": section(),
            "toxicity_safety": section(),
        },
        "sources": [
            {
                "source_class": "APPROVED",
                "url": "https://www.rhs.org.uk/plants/monstera",
                "title": "RHS",
                "publisher": "RHS",
            },
            {
                "source_class": "AI_GENERATED_REQUIRES_VERIFICATION",
                "url": None,
                "title": None,
                "publisher": None,
                "notes": "הדף אינו עוסק במין הזה.",
            },
        ],
    },
}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch):
    """The page with the API stubbed out.

    `app/ui` may not reach the database or an agent — the architecture test
    enforces that — so stubbing the one HTTP seam is enough to drive the whole
    screen.
    """
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    settings_module.get_settings.cache_clear()

    def _build(
        drafts: list[dict[str, Any]], sources: list[dict[str, Any]] | None = None
    ) -> AppTest:
        from app.ui.state import api_client

        def fake_get(path: str, **kwargs: Any) -> Any:
            if "knowledge-drafts" in path:
                return drafts
            if "approved-sources" in path:
                return sources or []
            return []

        monkeypatch.setattr(api_client, "get", fake_get)
        return AppTest.from_file(PAGE, default_timeout=30)

    return _build


def texts(app: AppTest) -> str:
    """Everything the page rendered, flattened, for substring assertions."""
    parts: list[str] = []
    for collection in (
        app.markdown,
        app.warning,
        app.caption,
        app.header,
        app.subheader,
        app.info,
    ):
        parts.extend(str(element.value) for element in collection)
    parts.extend(element.label for element in app.expander)
    parts.extend(element.label for element in app.button)
    return " ".join(parts)


def test_the_page_renders_without_errors(page):
    app = page([DRAFT])
    app.run()
    assert not app.exception, [str(e) for e in app.exception]


def test_a_low_confidence_section_is_named_up_front(page):
    """Not just marked somewhere in a list of fourteen expanders.

    A reviewer reading top to bottom gets to the fourteenth section least
    carefully, so the weak one is surfaced before any of them.
    """
    app = page([DRAFT])
    app.run()

    warnings = " ".join(str(w.value) for w in app.warning)
    assert "השקיה" in warnings
    assert "אור" not in warnings


def test_every_section_carries_its_confidence_in_the_heading(page):
    """The score is on the collapsed heading, not inside the section.

    A reviewer scanning the list can see which sections are weak without opening
    thirteen expanders. (`AppTest` does not expose whether a block is open, so the
    auto-expansion of weak sections is verified in the browser rather than here.)
    """
    app = page([DRAFT])
    app.run()

    labels = [e.label for e in app.expander]
    assert any("השקיה" in label and "0.20" in label for label in labels)
    assert any("אור" in label and "0.90" in label for label in labels)


def test_an_unverified_source_is_shown_and_labelled(page):
    """FINAL §10 requires unsupported claims to be marked. A review screen that
    quietly omitted them would let a draft look better sourced than it is."""
    app = page([DRAFT])
    app.run()

    rendered = texts(app)
    assert "דורש אימות" in rendered


def test_a_draft_still_researching_cannot_be_approved(page):
    """FINAL §11: only a draft a person has read may be published. The server
    refuses it too; this stops the button inviting the attempt."""
    researching = {**DRAFT, "status": "RESEARCHING", "content": None}
    app = page([researching])
    app.run()

    approve = [b for b in app.button if "אישור" in b.label]
    assert approve and approve[0].disabled


def test_rejection_is_blocked_until_a_reason_is_given(page):
    """A rejection with no reason leaves the retry nothing to address (A17)."""
    app = page([DRAFT])
    app.run()

    reject = [b for b in app.button if b.label == "דחייה"]
    assert reject and reject[0].disabled


def test_an_empty_queue_explains_where_drafts_come_from(page):
    app = page([])
    app.run()

    assert "טיוטה נפתחת אוטומטית" in texts(app)


def test_the_weak_sections_are_listed_worst_first(page):
    """The warning is a reading order, not a set.

    Listing them in section order puts the shakiest claim wherever it happens to
    fall among the fourteen, which defeats the point of naming them at all.
    """
    draft = {
        **DRAFT,
        "content": {
            **DRAFT["content"],
            "sections": {
                **DRAFT["content"]["sections"],
                "humidity": section("לחות", 0.45),
                "propagation": section("ריבוי", 0.20),
            },
        },
    }
    app = page([draft])
    app.run()

    warning = " ".join(str(w.value) for w in app.warning)
    assert warning.index("ריבוי") < warning.index("לחות")


def test_the_publish_confirmation_survives_the_rerun(page):
    """Found in the browser, not here — originally.

    Every action ends in `st.rerun()`, which discards anything written before it,
    so `st.success()` followed by `st.rerun()` shows the administrator nothing at
    all. The publish result carries the fan-out count, which is the part they most
    need confirmed. Parking it in session state and rendering it on the next run
    is what makes it visible.
    """
    from app.ui.app_pages import admin as admin_page  # noqa: F401

    app = page([DRAFT])
    app.session_state["admin_flash"] = (
        "success",
        "פורסמה גרסה 1. 3 צמחים של המין הזה פעילים כעת.",
        ":material/check_circle:",
    )
    app.run()

    shown = " ".join(str(s.value) for s in app.success)
    assert "פורסמה גרסה 1" in shown
    assert "3 צמחים" in shown
    # And it is consumed, so it does not follow the administrator around.
    assert "admin_flash" not in app.session_state
