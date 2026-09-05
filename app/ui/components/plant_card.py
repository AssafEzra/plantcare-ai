"""Plant card for the grid (FINAL §6, UI_DESIGN_TOKENS "My Plants")."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from app.ui.components.status import status_badge


def plant_card(plant: dict, *, on_open: Callable[[str], None] | None = None) -> None:
    """One plant, as a bordered card.

    Shows image, personal name, health and an attention indicator. Species and
    the nearest task join it once identification and scheduling exist; the card
    is deliberately honest about what it does not know yet rather than showing
    placeholder text that looks like data.
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
        status_badge(plant.get("current_health_status", "UNKNOWN"))

        if plant.get("status") == "PENDING_IDENTIFICATION":
            st.caption(":material/pending: ממתין לזיהוי")
        elif plant.get("status") == "KNOWLEDGE_PENDING":
            st.caption(":material/hourglass_top: מכינים מידע מקצועי")

        if on_open and st.button(
            "פתיחה", key=f"open_{plant['id']}", width="stretch", icon=":material/arrow_back:"
        ):
            on_open(plant["id"])
