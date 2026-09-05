"""My plants — the plant grid (FINAL §6)."""

from __future__ import annotations

import streamlit as st

from app.ui.components.layout import empty_state, guarded, page_header
from app.ui.state.api_client import get

page_header("הצמחים שלי")

controls = st.container(horizontal=True)
with controls:
    st.text_input(
        "חיפוש צמח",
        key="plants_search",
        label_visibility="collapsed",
        placeholder="חיפוש צמח…",
    )

plants = guarded(lambda: get("/v1/plants"), spinner="טוען את הצמחים שלך…")

if plants is None:
    st.stop()

if not plants and empty_state(
    "עדיין אין לך צמחים",
    "כשמוסיפים צמח, PlantCare מזהה אותו ובונה עבורו תוכנית טיפול אישית.",
    action_label="הוספת צמח",
    action_key="plants_add",
):
    st.switch_page("app_pages/add_plant.py")
