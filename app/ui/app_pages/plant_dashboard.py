"""Plant dashboard — the per-plant hub (FINAL §17)."""

from __future__ import annotations

import streamlit as st

from app.ui.components.layout import empty_state, page_header

page_header("הצמח שלי")

if empty_state(
    "לא נבחר צמח",
    "אפשר לבחור צמח מתוך רשימת הצמחים שלך.",
    icon=":material/spa:",
    action_label="לרשימת הצמחים",
    action_key="pd_to_list",
):
    st.switch_page("app_pages/my_plants.py")
