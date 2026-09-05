"""Settings — profile and notification preferences (UI_DESIGN_TOKENS "Settings")."""

from __future__ import annotations

from zoneinfo import available_timezones

import streamlit as st

from app.ui.components.layout import guarded, page_header, show_error
from app.ui.state.api_client import ApiError, get, patch

page_header("הגדרות")

profile = guarded(lambda: get("/v1/me"))
if profile is None:
    st.stop()

# A sorted list of every IANA zone, with the user's current one preselected.
# Common Israeli usage sits at the top so the usual choice is one click away.
_PREFERRED = ["Asia/Jerusalem", "Europe/Berlin", "Europe/London", "America/New_York", "UTC"]
_ALL = sorted(available_timezones())
_OPTIONS = _PREFERRED + [tz for tz in _ALL if tz not in _PREFERRED]

current_tz = profile.get("timezone") or "Asia/Jerusalem"
if current_tz not in _OPTIONS:
    _OPTIONS.insert(0, current_tz)

with st.form("profile_settings"):
    st.subheader("פרופיל", anchor=False)

    display_name = st.text_input("שם", value=profile.get("display_name") or "")
    timezone = st.selectbox(
        "אזור זמן",
        options=_OPTIONS,
        index=_OPTIONS.index(current_tz),
        help="התזכורות והמשימות מחושבות לפי אזור הזמן הזה.",
    )
    st.caption(f"אימייל: {profile.get('email') or '—'}")

    saved = st.form_submit_button("שמירה", type="primary")

if saved:
    changes: dict[str, str] = {}
    if (display_name or "").strip() != (profile.get("display_name") or ""):
        changes["display_name"] = display_name.strip()
    if timezone != current_tz:
        changes["timezone"] = timezone

    if not changes:
        st.info("אין שינויים לשמור.", icon=":material/info:")
    else:
        try:
            patch("/v1/me", json=changes)
            st.success("ההגדרות נשמרו.", icon=":material/check_circle:")
            st.rerun()
        except ApiError as exc:
            show_error(exc)

st.divider()

# Notification preferences are read and written through the API, which does not
# expose them yet. Shown disabled rather than hidden so the Settings screen
# matches the approved wireframe and the gap is visible rather than silent.
st.subheader("תזכורות", anchor=False)
st.toggle("תזכורות במייל", value=True, disabled=True)
st.time_input("שעה מועדפת", value=None, disabled=True)
st.toggle("סיכום יומי", value=True, disabled=True)
st.caption("הגדרות התזכורות ייפתחו יחד עם מנגנון התזכורות.")
