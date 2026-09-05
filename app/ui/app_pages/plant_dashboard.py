"""Plant dashboard — the per-plant hub (FINAL §17).

The care plan half lands here in PR 16. The gallery, timeline and health sections
arrive with PR 20; this page shows the plan, any open proposal, and the one
operational change a user is allowed to make.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.components.care_plan import active_plan_card, proposal_card
from app.ui.components.layout import empty_state, guarded, page_header, show_error
from app.ui.state.api_client import ApiError, get, post

SELECTED = "pc_selected_plant"
FLASH = "plant_flash"


def flash(message: str, *, kind: str = "success", icon: str = ":material/check_circle:") -> None:
    """Park a message across the rerun that follows an action.

    The same lesson as the admin panel: `st.rerun()` discards anything written
    before it, so a confirmation shown and immediately rerun away is one nobody
    sees.
    """
    st.session_state[FLASH] = (kind, message, icon)


def show_flash() -> None:
    parked = st.session_state.pop(FLASH, None)
    if not parked:
        return
    kind, message, icon = parked
    {"success": st.success, "info": st.info, "warning": st.warning}[kind](message, icon=icon)


plant_id = st.session_state.get(SELECTED)

if not plant_id:
    page_header("הצמח שלי")
    if empty_state(
        "לא נבחר צמח",
        "אפשר לבחור צמח מתוך רשימת הצמחים שלך.",
        icon=":material/spa:",
        action_label="לרשימת הצמחים",
        action_key="pd_to_list",
    ):
        st.switch_page("app_pages/my_plants.py")
    st.stop()


plant = guarded(lambda: get(f"/v1/plants/{plant_id}"))
if plant is None:
    st.stop()

page_header(plant.get("name") or "הצמח שלי")
show_flash()


def approve(version_id: str) -> None:
    try:
        with st.spinner("מפעילים את התוכנית…"):
            result = post(f"/v1/care-plan-proposals/{version_id}/approve")
        flash(f"התוכנית אושרה והיא פעילה כעת (גרסה {result['version_number']}).")
        st.rerun()
    except ApiError as exc:
        show_error(exc)


def reject(version_id: str) -> None:
    try:
        post(f"/v1/care-plan-proposals/{version_id}/reject", json={})
        # Rejecting is not a failure: the plan they already have keeps running,
        # and saying so stops the empty proposal list reading as a loss.
        flash("ההצעה נדחתה. התוכנית הקיימת ממשיכה כרגיל.", kind="info", icon=":material/info:")
        st.rerun()
    except ApiError as exc:
        show_error(exc)


def adjust(version_id: str, overrides: dict[str, Any], summary: str) -> None:
    try:
        post(
            f"/v1/care-plan-versions/{version_id}/operational-adjustment",
            json={"operational_preferences": overrides, "change_summary": summary},
        )
        flash(
            "השינוי נשמר כהצעה חדשה. אפשר לאשר אותה למטה.",
            kind="info",
            icon=":material/pending_actions:",
        )
        st.rerun()
    except ApiError as exc:
        show_error(exc)


# --- open proposals -----------------------------------------------------------

proposals = guarded(lambda: get(f"/v1/plants/{plant_id}/care-plan/proposals")) or []

if proposals:
    st.subheader("ממתין לאישור שלך", anchor=False)
    for proposal in proposals:
        proposal_card(proposal, on_approve=approve, on_reject=reject)


# --- the active plan ----------------------------------------------------------

try:
    plan = get(f"/v1/plants/{plant_id}/care-plan")
except ApiError as exc:
    # A plant with no plan yet is an ordinary state, not an error - it is what
    # every plant looks like between confirmation and the first approval.
    plan = None
    if exc.status != 404:
        show_error(exc)

if plan:
    active_plan_card(plan, on_adjust=adjust)
elif not proposals and empty_state(
    "אין עדיין תוכנית טיפול",
    "נכין הצעה לתוכנית המבוססת על המידע המקצועי של המין ועל התנאים בבית שלך.",
    icon=":material/calendar_month:",
    action_label="הכנת תוכנית",
    action_key="pd_request_plan",
):
    try:
        with st.spinner("מכינים הצעה…"):
            post(f"/v1/plants/{plant_id}/care-plan/proposals", json={"reason": "INITIAL_PLAN"})
        flash(
            "ההצעה בהכנה. היא תופיע כאן בעוד רגע.",
            kind="info",
            icon=":material/hourglass_top:",
        )
        st.rerun()
    except ApiError as exc:
        show_error(exc)
