"""Plant dashboard — the central hub (FINAL §17, UI_DESIGN_TOKENS).

§17 lists thirteen sections. The order here is the wireframe's and it is not
arbitrary: the hero image and status say what this plant *is* and how it is
doing, the actions come next because that is why someone opened the page, and
history goes last because it is for reading rather than acting.

Everything above the timeline comes from one `GET /v1/plants/{id}/dashboard`.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.components.care_plan import active_plan_card, proposal_card
from app.ui.components.care_task_card import care_task_card, due_text
from app.ui.components.layout import empty_state, guarded, page_header, show_error
from app.ui.components.status import status_badge, trend_badge
from app.ui.components.timeline import render_timeline
from app.ui.state.api_client import ApiError, get, post

SELECTED = "pc_selected_plant"
FLASH = "plant_flash"
HISTORY_SHOWN = "plant_history_shown"

ENVIRONMENT_LABELS: dict[str, str] = {
    "location_type": "מיקום",
    "light_level": "עוצמת אור",
    "light_direction": "כיוון החלון",
    "temperature_c": "טמפרטורה",
    "humidity_percent": "לחות",
    "room": "חדר",
    "notes": "הערות",
}

SECTION_LABELS: dict[str, str] = {
    "identification": "זיהוי",
    "description": "תיאור",
    "light": "אור",
    "watering": "השקיה",
    "soil": "מצע",
    "temperature": "טמפרטורה",
    "humidity": "לחות",
    "fertilization": "דישון",
    "repotting": "החלפת עציץ",
    "pruning": "גיזום",
    "propagation": "ריבוי",
    "common_problems": "בעיות נפוצות",
    "toxicity_safety": "רעילות ובטיחות",
}

LOGGABLE: dict[str, str] = {
    "REPOTTED": "החלפתי עציץ",
    "MOVED": "העברתי למקום אחר",
    "PRUNED": "גיזמתי",
    "CUSTOM_NOTE": "הערה חופשית",
}


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


data = guarded(lambda: get(f"/v1/plants/{plant_id}/dashboard"))
if data is None:
    st.stop()

species: dict[str, Any] | None = data.get("species")
health: dict[str, Any] = data.get("health") or {}
gallery: list[dict[str, Any]] = data.get("gallery") or []

page_header(data.get("name") or "הצמח שלי")
show_flash()

if data.get("status") == "ARCHIVED":
    st.info("הצמח נמצא בארכיון. ההיסטוריה נשמרת ואפשר לשחזר אותו.", icon=":material/inventory_2:")


def act(path: str, message: str, *, kind: str = "success") -> None:
    try:
        post(path)
        flash(message, kind=kind)
        st.rerun()
    except ApiError as exc:
        show_error(exc)


def log_event(event_type: str, note: str | None) -> None:
    try:
        post(f"/v1/plants/{plant_id}/history", json={"event_type": event_type, "note": note})
        flash("נרשם בהיסטוריה.")
        st.rerun()
    except ApiError as exc:
        show_error(exc)


# --- hero, species, status -----------------------------------------------------

hero, facts = st.columns([1, 1])

with hero:
    main_image = data.get("main_image")
    if main_image and main_image.get("url"):
        st.image(main_image["url"], width="stretch")
    else:
        st.container(height=180, border=True)
        st.caption(":material/photo_camera: אין עדיין תמונה")

with facts:
    if species:
        st.markdown(f"**{species.get('common_name') or species['scientific_name']}**")
        st.caption(f"*{species['scientific_name']}*")
    else:
        st.caption("הצמח עדיין לא זוהה.")

    status_badge(health.get("current_status", "UNKNOWN"))
    if health.get("trend"):
        trend_badge(health["trend"])
    if health.get("latest_assessed_at"):
        st.caption(f"בדיקה אחרונה: {due_text({'due_at_utc': health['latest_assessed_at']})}")

    actions = st.container(horizontal=True)
    with actions:
        if st.button("בדיקת בריאות", icon=":material/health_and_safety:", key="pd_health"):
            # PR 21 builds the check itself. Saying so beats a button that
            # silently does nothing.
            st.toast("בדיקת הבריאות תיפתח בקרוב.")

        if data.get("status") == "ARCHIVED":
            if st.button("שחזור", type="primary", icon=":material/unarchive:", key="pd_restore"):
                act(f"/v1/plants/{plant_id}/restore", "הצמח שוחזר.")
        elif st.button("העברה לארכיון", icon=":material/inventory_2:", key="pd_archive"):
            act(
                f"/v1/plants/{plant_id}/archive",
                "הצמח הועבר לארכיון. ההיסטוריה נשמרת.",
                kind="info",
            )

if len(gallery) > 1:
    with st.expander(f"גלריה ({len(gallery)})", icon=":material/photo_library:"):
        for row_start in range(0, len(gallery), 3):
            for column, image in zip(
                st.columns(3), gallery[row_start : row_start + 3], strict=False
            ):
                if image.get("thumbnail_url"):
                    column.image(image["thumbnail_url"], width="stretch")

st.divider()


# --- proposals and plan --------------------------------------------------------


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


if data.get("open_proposals"):
    proposals = guarded(lambda: get(f"/v1/plants/{plant_id}/care-plan/proposals")) or []
    if proposals:
        st.subheader("ממתין לאישור שלך", anchor=False)
        for proposal in proposals:
            proposal_card(proposal, on_approve=approve, on_reject=reject)

upcoming = data.get("upcoming_tasks") or []
if upcoming:
    st.subheader("הטיפול הקרוב", anchor=False)
    for task in upcoming[:5]:
        care_task_card(task, key_prefix="pd")

plan = data.get("care_plan")
if plan:
    active_plan_card(plan, on_adjust=adjust)
elif not data.get("open_proposals") and empty_state(
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


# --- environment ---------------------------------------------------------------

environment = data.get("environment")
with st.expander("תנאי הגידול", icon=":material/thermostat:"):
    if environment:
        for key, label in ENVIRONMENT_LABELS.items():
            value = environment.get(key)
            if value not in (None, ""):
                st.markdown(f"**{label}:** {value}")
    else:
        st.caption("עדיין לא הוגדרו תנאי גידול.")
    # FINAL §12: an environment change produces a proposal, never a silent
    # rewrite. Saying so here sets the expectation before the user changes one.
    st.caption("עדכון התנאים מפעיל בדיקה של תוכנית הטיפול, אך לא משנה אותה אוטומטית.")


# --- knowledge ------------------------------------------------------------------

if species:
    with st.expander("מידע מקצועי על המין", icon=":material/menu_book:"):
        knowledge = None
        try:
            knowledge = get(f"/v1/species/{species['id']}/knowledge")
        except ApiError as exc:
            if exc.status == 404:
                st.caption("המידע המקצועי עדיין בהכנה.")
            else:
                show_error(exc)

        if knowledge:
            sections = knowledge.get("content") or {}
            rendered_any = False
            for name, label in SECTION_LABELS.items():
                section = sections.get(name)
                text = section.get("text") if isinstance(section, dict) else section
                if text:
                    rendered_any = True
                    st.markdown(f"**{label}**")
                    st.write(text)

            if not rendered_any:
                # An empty box reads as a broken page. Saying so is worse news and
                # better information.
                st.caption("המידע המקצועי אינו זמין להצגה כרגע.")

            # FINAL §10: users report errors; they never edit.
            with st.form("knowledge_report"):
                report = st.text_area(
                    "דיווח על טעות במידע",
                    placeholder="למשל: ההמלצה על ההשקיה אינה מתאימה למין הזה",
                )
                if st.form_submit_button("שליחת דיווח") and report.strip():
                    try:
                        post(
                            f"/v1/species/{species['id']}/knowledge-reports",
                            json={"plant_id": plant_id, "report_text": report.strip()},
                        )
                        flash("הדיווח נשלח לבדיקה. תודה.", kind="info", icon=":material/info:")
                        st.rerun()
                    except ApiError as exc:
                        show_error(exc)


# --- history --------------------------------------------------------------------

st.divider()
st.subheader("היסטוריה", anchor=False)

with st.expander("רישום פעולה שביצעת", icon=":material/add_notes:"):
    st.caption("דברים שעשית מחוץ לתוכנית — הם עדיין חלק מההיסטוריה של הצמח.")
    event_type = st.selectbox(
        "מה קרה?",
        options=list(LOGGABLE),
        format_func=lambda key: LOGGABLE[key],
        key="pd_event_type",
    )
    note = st.text_input("הערה", key="pd_event_note")
    if st.button(
        "רישום",
        key="pd_log_event",
        # A custom note with nothing in it is an empty timeline row. The server
        # refuses it too; disabling says so before the round trip.
        disabled=event_type == "CUSTOM_NOTE" and not note.strip(),
    ):
        log_event(event_type, note.strip() or None)

shown = st.session_state.get(HISTORY_SHOWN, 20)
history = guarded(lambda: get(f"/v1/plants/{plant_id}/history", params={"limit": shown})) or []
render_timeline(history)

if len(history) >= shown and st.button("טעינת עוד", key="pd_more_history"):
    st.session_state[HISTORY_SHOWN] = shown + 20
    st.rerun()
