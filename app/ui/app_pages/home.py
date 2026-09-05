"""Home dashboard.

The full twelve-item dashboard (FINAL §5) is built once the scheduler and task
endpoints exist. This is the shell: real greeting, real counts where the API
already provides them, and honest empty states everywhere else.
"""

from __future__ import annotations

import streamlit as st

from app.ui.components.layout import empty_state, page_header
from app.ui.state import session
from app.ui.state.api_client import ApiError, get

current = session.current()

try:
    profile = get("/v1/me") or {}
except ApiError:
    profile = {}

name = profile.get("display_name") or ""
page_header(f"שלום {name}".strip() + " 👋", "היום בגינה שלך")

left, right = st.columns(2)

with left, st.container(border=True):
    st.subheader("הטיפול של היום", anchor=False)
    st.caption("המשימות יופיעו כאן ברגע שתהיה לך תוכנית טיפול פעילה.")

with right, st.container(border=True):
    st.subheader("דורש תשומת לב", anchor=False)
    st.caption("כאן יופיעו צמחים שכדאי לבדוק.")

st.divider()

st.subheader("הצמחים שלי", anchor=False)
if empty_state(
    "עדיין אין לך צמחים",
    "אפשר להוסיף צמח ראשון ולתת ל-PlantCare לזהות אותו עבורך.",
    action_label="הוספת צמח",
    action_key="home_add_plant",
):
    st.switch_page("app_pages/add_plant.py")
