"""Sign in, register and password reset.

The only screen that talks to Supabase directly rather than through the API:
obtaining a credential is not a business operation (PROJECT_STRUCTURE §7).
"""

from __future__ import annotations

import contextlib

import streamlit as st

from app.ui.components.layout import page_header
from app.ui.state import session

page_header("PlantCare AI", "המנהל האישי לצמחים שלך")

sign_in_tab, register_tab, reset_tab = st.tabs(["כניסה", "הרשמה", "שכחתי סיסמה"])

with sign_in_tab:
    with st.form("sign_in"):
        email = st.text_input("אימייל", key="si_email", autocomplete="email")
        password = st.text_input(
            "סיסמה", type="password", key="si_password", autocomplete="current-password"
        )
        submitted = st.form_submit_button("כניסה", type="primary", width="stretch")

    if submitted:
        if not email or not password:
            st.warning("יש למלא אימייל וסיסמה.", icon=":material/info:")
        else:
            try:
                session.sign_in(email.strip(), password)
                st.rerun()
            except Exception:
                # Deliberately identical for a wrong password and an unknown
                # address: distinguishing them tells an attacker which accounts
                # exist.
                st.error("האימייל או הסיסמה שגויים.", icon=":material/error:")

with register_tab:
    with st.form("register"):
        new_name = st.text_input("שם (אופציונלי)", key="ru_name")
        new_email = st.text_input("אימייל", key="ru_email", autocomplete="email")
        new_password = st.text_input(
            "סיסמה", type="password", key="ru_password", autocomplete="new-password"
        )
        st.caption("לפחות 8 תווים.")
        registering = st.form_submit_button("הרשמה", type="primary", width="stretch")

    if registering:
        if not new_email or not new_password:
            st.warning("יש למלא אימייל וסיסמה.", icon=":material/info:")
        elif len(new_password) < 8:
            st.warning("הסיסמה צריכה להכיל לפחות 8 תווים.", icon=":material/info:")
        else:
            try:
                needs_confirmation = session.sign_up(
                    new_email.strip(), new_password, (new_name or "").strip() or None
                )
                if needs_confirmation:
                    st.success(
                        "שלחנו לך מייל אימות. יש לאשר אותו ואז להתחבר.",
                        icon=":material/mark_email_read:",
                    )
                else:
                    st.rerun()
            except Exception:
                st.error("לא הצלחנו ליצור את החשבון. ייתכן שהוא כבר קיים.", icon=":material/error:")

with reset_tab:
    with st.form("reset"):
        reset_email = st.text_input("אימייל", key="rp_email", autocomplete="email")
        resetting = st.form_submit_button("שליחת קישור לאיפוס", width="stretch")

    if resetting:
        if reset_email:
            # Any failure is swallowed on purpose: surfacing one would reveal
            # whether the address is registered.
            with contextlib.suppress(Exception):
                session.send_password_reset(reset_email.strip())
        # Always the same response, whether or not the address is registered:
        # a different message would confirm which addresses have accounts.
        st.success(
            "אם קיים חשבון עם האימייל הזה, ישלח אליו קישור לאיפוס.",
            icon=":material/mark_email_read:",
        )
