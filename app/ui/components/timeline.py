"""Plant history rendering (FINAL §19, UI_DESIGN_TOKENS "Plant Dashboard").

The timeline merges five sources, so the one thing it must not do is look like
five lists stacked together. Every entry gets the same shape — icon, summary,
when — and the icon is what says where it came from.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import streamlit as st

# Icon per kind. Care and health entries are the ones a user scans for, so they
# get distinct glyphs rather than sharing a generic "event" marker.
_ICONS: dict[str, str] = {
    "PLANT_CREATED": ":material/eco:",
    "PLANT_ARCHIVED": ":material/inventory_2:",
    "PLANT_RESTORED": ":material/unarchive:",
    "PLANT_RENAMED": ":material/edit:",
    "ENVIRONMENT_CHANGED": ":material/thermostat:",
    "MAIN_IMAGE_CHANGED": ":material/image:",
    "REPOTTED": ":material/potted_plant:",
    "MOVED": ":material/move_down:",
    "PRUNED": ":material/content_cut:",
    "CUSTOM_NOTE": ":material/sticky_note_2:",
    "CARE_DONE": ":material/check_circle:",
    "CARE_SKIPPED": ":material/skip_next:",
    "CARE_MISSED": ":material/schedule:",
    "CARE_CORRECTED": ":material/history:",
    "HEALTH_ASSESSMENT": ":material/health_and_safety:",
    "IDENTIFICATION": ":material/search:",
    "CARE_PLAN_VERSION": ":material/calendar_month:",
}

_FALLBACK_ICON = ":material/circle:"


def _when(value: str) -> str:
    """A date a person reads, with relative wording for the recent past.

    "Today" and "yesterday" carry more than a date does when scanning a list, and
    beyond that the date is what actually helps.
    """
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()
    except ValueError:  # pragma: no cover - the API returns ISO-8601
        return ""

    today = datetime.now().astimezone().date()
    days = (today - moment.date()).days

    if days == 0:
        return f"היום {moment:%H:%M}"
    if days == 1:
        return f"אתמול {moment:%H:%M}"
    if days < 7:
        return f"לפני {days} ימים"
    return f"{moment:%d/%m/%Y}"


def render_timeline(entries: list[dict[str, Any]]) -> None:
    if not entries:
        st.caption("עדיין אין היסטוריה לצמח הזה.")
        return

    for entry in entries:
        icon = _ICONS.get(entry.get("kind", ""), _FALLBACK_ICON)
        detail = entry.get("detail") or {}

        with st.container(border=True):
            st.markdown(f"{icon} {entry.get('summary', '')}")
            st.caption(_when(entry.get("occurred_at", "")))

            # A note the user wrote, or a plan's change summary: the entry says
            # what happened, and this says what the person said about it.
            note = detail.get("note") or detail.get("change_summary")
            if note and note != entry.get("summary"):
                st.caption(f"„{note}”")


def timeline_kinds(entries: list[dict[str, Any]]) -> list[str]:
    """The distinct kinds present, for a filter control."""
    return sorted({str(entry.get("kind", "")) for entry in entries if entry.get("kind")})


def utc_now_iso() -> str:  # pragma: no cover - a seam for the "load more" cursor
    return datetime.now(UTC).isoformat()
