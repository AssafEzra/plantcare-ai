"""Plant card for the grid (FINAL §6, UI_DESIGN_TOKENS "My Plants")."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from app.ui.components.care_plan import ACTION_LABELS
from app.ui.components.care_task_card import due_text
from app.ui.components.status import status_badge


def plant_card(plant: dict, *, on_open: Callable[[str], None] | None = None) -> None:
    """One plant, as a bordered card.

    The six things `PROGRESS §10` asks for: image, name, species, health, the
    nearest task, and a way in. Everything below the name is conditional — a
    plant with no photograph, no confirmed species or no schedule yet renders
    without those lines rather than with placeholder text that looks like data.

    The image, species and task all arrive from `GET /v1/plants`, which did not
    supply any of them until PR 25. The card had been reading `thumbnail_url`
    since PR 9 and the key was never set, so every card in the grid showed "no
    image" regardless of how many photographs the plant had.
    """
    with st.container(border=True):
        image_url = plant.get("thumbnail_url")
        if image_url:
            st.image(image_url, width="stretch")
        else:
            # A neutral placeholder keeps the grid aligned; an empty slot makes
            # the row jump around as images load.
            st.container(height=120, border=False)
            st.caption(":material/photo_camera: אין תמונה")

        st.markdown(f"**{plant.get('name') or 'ללא שם'}**")

        # The botanical identity, under the name the user gave it. Absent until
        # an identification is confirmed, which is the only thing that makes a
        # species authoritative.
        if plant.get("species_name"):
            st.caption(f":material/eco: {plant['species_name']}")

        status_badge(plant.get("current_health_status", "UNKNOWN"))

        if plant.get("status") == "PENDING_IDENTIFICATION":
            st.caption(":material/pending: ממתין לזיהוי")
        elif plant.get("status") == "KNOWLEDGE_PENDING":
            st.caption(":material/hourglass_top: מכינים מידע מקצועי")

        task = plant.get("next_task")
        if task:
            action = task.get("action_type") or ""
            label, icon = ACTION_LABELS.get(action, (action or "טיפול", ":material/task_alt:"))
            when = due_text(task)
            # Late work says so, and says it in the same words the task card
            # uses. A grid that showed only the date would make the reader work
            # out whether it had already passed.
            st.caption(f"{icon} {label} · {when}" if when else f"{icon} {label}")

        if on_open and st.button(
            "פתיחה", key=f"open_{plant['id']}", width="stretch", icon=":material/arrow_back:"
        ):
            on_open(plant["id"])
