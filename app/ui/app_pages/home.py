"""Home dashboard (FINAL §5, UI_DESIGN_TOKENS "Home Dashboard").

    "The dashboard is action-oriented. The user should understand in seconds
     what needs attention today."

That sentence decides the ordering. Today's work comes first, because it is the
only thing on the page the user can act on right now. Plants needing attention
come second, counts third, and the plant grid last — it is pleasant to look at
and it is not a call to action.

Everything renders from a single `GET /v1/dashboard` (API_CONTRACTS §Dashboard),
which exists because this is the page a user opens every day and five sequential
calls would be felt.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from app.ui.components.care_plan import ACTION_LABELS
from app.ui.components.care_task_card import care_task_card, due_text, overdue_summary_line
from app.ui.components.layout import empty_state, guarded, page_header, show_error
from app.ui.components.status import status_badge
from app.ui.state.api_client import ApiError, get, post

FLASH = "home_flash"


def flash(message: str, *, kind: str = "success", icon: str = ":material/check_circle:") -> None:
    """Park a message across the rerun an action triggers.

    `st.rerun()` discards anything written before it, so a confirmation shown and
    immediately rerun away is one nobody sees.
    """
    st.session_state[FLASH] = (kind, message, icon)


def show_flash() -> None:
    parked = st.session_state.pop(FLASH, None)
    if not parked:
        return
    kind, message, icon = parked
    {"success": st.success, "info": st.info, "warning": st.warning}[kind](message, icon=icon)


def greeting() -> str:
    """Personalised, and aware of the time of day.

    A dashboard that says "good morning" at ten at night is a small thing that
    makes the whole page feel unattended.
    """
    hour = datetime.now().astimezone().hour
    if hour < 12:
        return "בוקר טוב"
    if hour < 18:
        return "צהריים טובים"
    return "ערב טוב"


def open_plant(plant_id: str) -> None:
    st.session_state["pc_selected_plant"] = plant_id
    st.switch_page("app_pages/plant_dashboard.py")


# --- load ---------------------------------------------------------------------

try:
    profile = get("/v1/me") or {}
except ApiError:
    profile = {}

name = (profile.get("display_name") or "").strip()
page_header(f"{greeting()} {name}".strip() + " 👋", "מה מחכה לך היום")
show_flash()

dashboard = guarded(lambda: get("/v1/dashboard"))
if dashboard is None:
    st.stop()

counts: dict[str, Any] = dashboard.get("counts") or {}
today_care = dashboard.get("today_care") or []
upcoming = dashboard.get("upcoming_care") or []
overdue = dashboard.get("overdue_summary") or []
attention = dashboard.get("plants_needing_attention") or []
my_plants = dashboard.get("my_plants") or []


def mark(task_id: str, action: str, message: str) -> None:
    try:
        result = post(f"/v1/care-tasks/{task_id}/{action}")
        note = message
        if result.get("next_due_at_utc"):
            note += f" הפעם הבאה: {due_text({'due_at_utc': result['next_due_at_utc']})}."
        flash(note)
        st.rerun()
    except ApiError as exc:
        show_error(exc)


# --- counts -------------------------------------------------------------------

plants_col, today_col, attention_col = st.columns(3)
plants_col.metric("צמחים פעילים", counts.get("active_plants", 0))
today_col.metric("משימות להיום", counts.get("today_tasks", 0))
attention_col.metric("דורשים תשומת לב", counts.get("attention", 0))

st.divider()


# --- today's care -------------------------------------------------------------

st.subheader("הטיפול של היום", anchor=False)

if overdue:
    # FINAL §13: one line per plant. A user back from a fortnight away should not
    # be shown fourteen rows, which is complete and reads as a reprimand.
    for summary in overdue:
        st.warning(overdue_summary_line(summary), icon=":material/schedule:")

if today_care:
    for task in today_care:
        care_task_card(
            task,
            on_done=lambda task_id: mark(task_id, "done", "יופי, נרשם."),
            on_skip=lambda task_id: mark(task_id, "skip", "דילגנו על המשימה."),
        )
elif counts.get("active_plants"):
    # The all-caught-up state FINAL §5 asks for by name. Distinct from "no plants
    # yet": one is an achievement, the other is an invitation, and showing the
    # same empty box for both would waste the only moment the app gets to say
    # well done.
    with st.container(border=True):
        st.markdown("### :material/task_alt: הכול מטופל")
        st.write("אין משימות פתוחות להיום. נעדכן אותך כשיגיע הזמן.")
else:
    if empty_state(
        "עדיין אין לך צמחים",
        "אפשר להוסיף צמח ראשון ולתת ל-PlantCare לזהות אותו עבורך.",
        action_label="הוספת צמח",
        action_key="home_add_plant_empty",
    ):
        st.switch_page("app_pages/add_plant.py")


# --- upcoming -----------------------------------------------------------------

if upcoming:
    with st.expander(f"בקרוב ({len(upcoming)})", icon=":material/upcoming:"):
        for task in upcoming:
            # The action, not just the plant and the time. Three rules on one
            # plant produce three lines that are otherwise word-for-word
            # identical, which tells the user nothing about what is coming.
            action = task.get("action_type") or ""
            label, _ = ACTION_LABELS.get(action, (action, ""))
            plant_name = task.get("plant_name") or "הצמח שלי"
            st.markdown(f":gray[**{label}** · {plant_name} · {due_text(task)}]")


# --- needing attention --------------------------------------------------------

if attention:
    st.subheader("דורשים תשומת לב", anchor=False)
    for plant in attention:
        with st.container(border=True):
            st.markdown(f"**{plant.get('name') or 'ללא שם'}**")
            status_badge(plant.get("current_health_status", "UNKNOWN"))
            if st.button("פתיחה", key=f"attention_{plant['id']}", icon=":material/arrow_back:"):
                open_plant(plant["id"])


# --- quick actions ------------------------------------------------------------

st.divider()

quick = st.container(horizontal=True)
with quick:
    if st.button("הוספת צמח", type="primary", icon=":material/add:", key="home_add_plant"):
        st.switch_page("app_pages/add_plant.py")
    # FINAL §5 asks for a Quick Health Check on Home. The check itself is the
    # Health Agent's, which lands in PR 21; until then this takes the user to the
    # plant they would run it on rather than showing a button that does nothing.
    if st.button("בדיקת בריאות מהירה", icon=":material/health_and_safety:", key="home_health"):
        if len(my_plants) == 1:
            open_plant(my_plants[0]["id"])
        else:
            st.switch_page("app_pages/my_plants.py")


# --- my plants preview --------------------------------------------------------

if my_plants:
    st.subheader("הצמחים שלי", anchor=False)
    for row_start in range(0, len(my_plants), 3):
        for column, plant in zip(st.columns(3), my_plants[row_start : row_start + 3], strict=False):
            with column, st.container(border=True):
                st.markdown(f"**{plant.get('name') or 'ללא שם'}**")
                status_badge(plant.get("current_health_status", "UNKNOWN"))
                if st.button(
                    "פתיחה",
                    key=f"preview_{plant['id']}",
                    width="stretch",
                    icon=":material/arrow_back:",
                ):
                    open_plant(plant["id"])

    if counts.get("active_plants", 0) > len(my_plants) and st.button(
        "לכל הצמחים", key="home_all_plants"
    ):
        st.switch_page("app_pages/my_plants.py")
