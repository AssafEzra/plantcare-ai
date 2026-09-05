"""Admin panel (FINAL §29).

Reaching this page at all requires an ADMIN role, but that is a courtesy: the
navigation entry is hidden for other users while every admin route and every
admin table is independently gated server-side. Hiding UI is never the control.
"""

from __future__ import annotations

import streamlit as st

from app.ui.components.layout import page_header

page_header("ניהול", "אזור מנהלי מערכת")

drafts, published, sources, reports, monitoring = st.tabs(
    ["טיוטות ידע", "ידע מפורסם", "מקורות מאושרים", "דיווחי משתמשים", "ניטור סוכנים"]
)

with drafts:
    st.caption("טיוטות ידע הממתינות לבדיקה יופיעו כאן.")
with published:
    st.caption("גרסאות ידע שפורסמו, כולל היסטוריה ומקורות.")
with sources:
    st.caption("ניהול רשימת הדומיינים המאושרים.")
with reports:
    st.caption("דיווחי משתמשים על שגיאות במידע.")
with monitoring:
    st.caption("הרצות של סוכני ה-AI: מודל, גרסת פרומפט, משך ועלות.")
