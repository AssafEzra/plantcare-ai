"""My plants — the plant grid (FINAL §6)."""

from __future__ import annotations

import streamlit as st

from app.common.enums import HealthStatus
from app.ui.components.layout import empty_state, guarded, page_header
from app.ui.components.plant_card import plant_card
from app.ui.components.status import status_style
from app.ui.state.api_client import get

page_header("הצמחים שלי")

_HEALTH_LABELS = {"": "כל הבריאות"} | {
    status.value: status_style(status).label for status in HealthStatus
}

controls = st.container(horizontal=True)
with controls:
    search = st.text_input(
        "חיפוש צמח",
        key="plants_search",
        label_visibility="collapsed",
        placeholder="חיפוש צמח…",
    )
    health = st.selectbox(
        "סינון לפי בריאות",
        options=list(_HEALTH_LABELS),
        format_func=lambda key: _HEALTH_LABELS[key],
        key="plants_health",
        label_visibility="collapsed",
    )

params: dict[str, str] = {}
if search.strip():
    params["q"] = search.strip()
if health:
    params["health_status"] = health

plants = guarded(lambda: get("/v1/plants", params=params), spinner="טוען את הצמחים שלך…")
if plants is None:
    st.stop()

if not plants:
    # A search that found nothing is a different situation from owning no plants,
    # and offering "add your first plant" to someone with twenty is wrong.
    if params:
        st.info("לא נמצאו צמחים שמתאימים לחיפוש.", icon=":material/search_off:")
    elif empty_state(
        "עדיין אין לך צמחים",
        "כשמוסיפים צמח, PlantCare מזהה אותו ובונה עבורו תוכנית טיפול אישית.",
        action_label="הוספת צמח",
        action_key="plants_add",
    ):
        st.switch_page("app_pages/add_plant.py")
    st.stop()

st.caption(f"{len(plants)} צמחים")

# Three per row on a wide screen; Streamlit collapses columns on narrow ones.
for row_start in range(0, len(plants), 3):
    for column, plant in zip(st.columns(3), plants[row_start : row_start + 3], strict=False):
        with column:
            plant_card(plant)
