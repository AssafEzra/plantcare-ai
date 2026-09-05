"""Add plant — step 1 of the identification flow (FINAL §8)."""

from __future__ import annotations

import streamlit as st

from app.ui.components.layout import page_header

page_header("הוספת צמח", "שלב 1 מתוך 3")

st.write("צלמו או העלו עד 4 תמונות של הצמח.")
st.file_uploader(
    "תמונות הצמח",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
    key="add_plant_images",
    help="עד 4 תמונות, כל אחת עד 10MB.",
)
st.text_area("תיאור קצר (אופציונלי)", key="add_plant_note", placeholder="למשל: קיבלתי אותו במתנה")
st.button("המשך לזיהוי", type="primary", disabled=True, help="הזיהוי ייפתח בשלב הבא של הפיתוח.")
