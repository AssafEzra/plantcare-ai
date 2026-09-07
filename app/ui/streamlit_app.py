"""PlantCare AI — Streamlit entry point.

Navigation is built with `st.navigation`/`st.Page`. The page modules live in
`app/ui/app_pages/`, **not** `pages/`: a `pages/` directory beside the entry
script triggers Streamlit's legacy auto-discovery, which would fight the explicit
navigation defined here. PROJECT_STRUCTURE §2 names `pages/`; the deviation and
its reason are recorded there.
"""

from __future__ import annotations

import streamlit as st

from app.common.enums import UserRole
from app.ui import embedded_api
from app.ui.state import session
from app.ui.state.api_client import ApiError, get
from app.ui.styles.rtl import apply_rtl

st.set_page_config(
    page_title="PlantCare AI",
    page_icon=":material/potted_plant:",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_rtl()

# Before anything calls the API. On a single-process host this starts it; on every
# other deployment - including local development, where the API is a separate
# `uvicorn` - it does nothing at all.
embedded_api.start_if_configured()


@st.cache_data(ttl=60, show_spinner=False)
def _profile(user_id: str, token_fingerprint: str) -> dict | None:
    """The signed-in user's profile.

    Cached briefly because it is read on every rerun to decide whether the admin
    section belongs in the navigation. Keyed on the user id so one account can
    never see another's cached profile, and on a token fingerprint so a
    re-authentication refreshes it.
    """
    try:
        return get("/v1/me")
    except ApiError:
        return None


def _sync_timezone(profile: dict) -> None:
    """Adopt the browser's timezone the first time we see it.

    FINAL §15 asks for automatic detection with a manual override. `st.context`
    exposes the browser's IANA zone, so detection needs no custom component. The
    stored value is only ever replaced while it is still the default - once a
    user has chosen a zone in Settings, their choice stands.
    """
    if st.session_state.get("pc_tz_checked"):
        return
    st.session_state["pc_tz_checked"] = True

    detected = getattr(st.context, "timezone", None)
    if not detected or profile.get("timezone") != "Asia/Jerusalem":
        return
    if detected == "Asia/Jerusalem":
        return

    try:
        from app.ui.state.api_client import patch

        patch("/v1/me", json={"timezone": detected})
        _profile.clear()
    except ApiError:
        # A rejected zone is not worth interrupting sign-in over; Settings still
        # offers the manual override.
        pass


# --- routing ------------------------------------------------------------------

# Before anything decides what to draw: a browser refresh starts a new Streamlit
# session, so the auth state has to be rebuilt from the browser first. Without
# this, F5 was indistinguishable from signing out.
session.restore()

# The cookie does not always arrive with the connection - on Streamlit Community
# Cloud it never does - so the answer can be one rerun away. Draw nothing that
# would be wrong if the user turns out to be signed in.
if session.restoring():
    st.caption("רק רגע…")
    st.stop()

if not session.is_signed_in():
    pages = [st.Page("app_pages/auth.py", title="כניסה", icon=":material/login:")]
else:
    current = session.current()
    profile = _profile(current.user_id, current.access_token[-16:]) or {} if current else {}
    if profile:
        _sync_timezone(profile)

    # An administrator gets the operator's application, not the gardener's with an
    # extra tab. The admin account exists to review knowledge drafts, watch agent
    # runs and read the audit log; Home, My Plants and Add Plant are somebody
    # else's product, and carrying them made the panel look like a sixth tab of a
    # plant-care app rather than the thing an operator opens.
    #
    # Settings stays: an administrator still has a timezone, a display name and
    # notification preferences, and those live nowhere else.
    #
    # This is presentation only. Every plant route is still the caller's own by
    # RLS and every admin route is still gated server-side (FINAL §22, §26) - an
    # administrator who typed a plant URL would see their own plants, exactly as
    # before. Hiding navigation has never been the control here.
    if profile.get("role") == UserRole.ADMIN:
        pages = [
            st.Page(
                "app_pages/admin.py",
                title="ניהול",
                icon=":material/admin_panel_settings:",
                default=True,
            ),
            st.Page("app_pages/settings.py", title="הגדרות", icon=":material/settings:"),
        ]
    else:
        pages = [
            st.Page("app_pages/home.py", title="בית", icon=":material/home:", default=True),
            st.Page("app_pages/my_plants.py", title="הצמחים שלי", icon=":material/potted_plant:"),
            st.Page("app_pages/add_plant.py", title="הוספת צמח", icon=":material/add_circle:"),
            st.Page("app_pages/plant_dashboard.py", title="הצמח שלי", icon=":material/spa:"),
            st.Page("app_pages/settings.py", title="הגדרות", icon=":material/settings:"),
        ]

    with st.sidebar:
        st.markdown("### PlantCare AI")
        st.caption(profile.get("display_name") or profile.get("email") or "")
        st.divider()

page = st.navigation(pages)

if session.is_signed_in():
    with st.sidebar:
        if st.button("יציאה", icon=":material/logout:", width="stretch"):
            session.sign_out()
            _profile.clear()
            st.rerun()

page.run()
