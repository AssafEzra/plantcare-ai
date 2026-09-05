"""Settings — profile and notification preferences (UI_DESIGN_TOKENS "Settings")."""

from __future__ import annotations

from datetime import time, timedelta
from zoneinfo import available_timezones

import streamlit as st

from app.ui.components.layout import guarded, page_header, show_error
from app.ui.state.api_client import ApiError, get, patch, put

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

# --- notification preferences (FINAL §14) --------------------------------------

st.subheader("תזכורות", anchor=False)

preferences = guarded(lambda: get("/v1/notification-preferences"))
if preferences is None:
    st.stop()


def _preferred_time() -> time:
    raw = str(preferences.get("preferred_time_local") or "08:00")
    try:
        return time.fromisoformat(raw if len(raw) > 5 else f"{raw}:00")
    except ValueError:
        return time(8, 0)


with st.form("notification_settings"):
    email_enabled = st.toggle(
        "תזכורות במייל",
        value=bool(preferences.get("email_enabled", True)),
    )
    preferred = st.time_input(
        "שעה מועדפת",
        value=_preferred_time(),
        step=timedelta(minutes=30),
        # A10 made visible. The rule says when a task is due; this says when we
        # are allowed to write. A user who waters in the evening still wants to
        # be told in the morning, and the two settings being confusable is
        # exactly the ambiguity the spec left open.
        help="השעה שבה נשלח לך את התזכורת. זמני הטיפול עצמם נקבעים בתוכנית הטיפול.",
    )
    daily_digest = st.toggle(
        "סיכום יומי",
        value=bool(preferences.get("daily_digest", True)),
        help="הודעה אחת עם כל משימות היום, במקום הודעה נפרדת לכל משימה.",
    )

    saved_prefs = st.form_submit_button("שמירת התזכורות", type="primary")

if saved_prefs:
    reminder_changes: dict[str, object] = {}
    if email_enabled != bool(preferences.get("email_enabled", True)):
        reminder_changes["email_enabled"] = email_enabled
    if daily_digest != bool(preferences.get("daily_digest", True)):
        reminder_changes["daily_digest"] = daily_digest
    if preferred and preferred != _preferred_time():
        reminder_changes["preferred_time_local"] = preferred.isoformat()

    if not reminder_changes:
        st.info("אין שינויים לשמור.", icon=":material/info:")
    else:
        try:
            put("/v1/notification-preferences", json=reminder_changes)
            st.success("הגדרות התזכורות נשמרו.", icon=":material/check_circle:")
            st.rerun()
        except ApiError as exc:
            show_error(exc)

if not preferences.get("email_enabled", True):
    # Said plainly rather than left to be inferred from a toggle: a user who
    # turned reminders off should know the work is still tracked in the app.
    st.caption("התזכורות במייל כבויות. המשימות עדיין מופיעות במסך הבית.")
