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

from app.ui.components.agent_progress import await_request
from app.ui.components.care_plan import active_plan_card, proposal_card
from app.ui.components.care_task_card import care_task_card, due_text, is_due
from app.ui.components.environment_form import FIELD_LABELS, describe, environment_form
from app.ui.components.health_card import render_assessment, render_history
from app.ui.components.health_check_dialog import close_dialog as close_health_dialog
from app.ui.components.health_check_dialog import health_check_dialog
from app.ui.components.health_check_dialog import open_dialog as open_health_dialog
from app.ui.components.identification_card import identification_card
from app.ui.components.layout import empty_state, guarded, page_header, show_error
from app.ui.components.sources import render_sources
from app.ui.components.status import status_badge, trend_badge
from app.ui.components.timeline import render_timeline
from app.ui.state.api_client import ApiError, delete, get, patch, post, put

SELECTED = "pc_selected_plant"
FLASH = "plant_flash"
HISTORY_SHOWN = "plant_history_shown"

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
pending_identification: dict[str, Any] | None = data.get("pending_identification")
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
    elif pending_identification:
        st.caption("הזיהוי הושלם וממתין לאישור שלך.")
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
            open_health_dialog()
            st.rerun()

        if data.get("status") == "ARCHIVED":
            if st.button("שחזור", type="primary", icon=":material/unarchive:", key="pd_restore"):
                act(f"/v1/plants/{plant_id}/restore", "הצמח שוחזר.")
        elif st.button("העברה לארכיון", icon=":material/inventory_2:", key="pd_archive"):
            act(
                f"/v1/plants/{plant_id}/archive",
                "הצמח הועבר לארכיון. ההיסטוריה נשמרת.",
                kind="info",
            )


def rename_plant(name: str, notes: str) -> None:
    """PATCH /v1/plants/{id}. Shipped in PR 11 and reachable from nowhere until
    PR 31, so a plant kept whatever name confirmation gave it forever."""
    try:
        patch(
            f"/v1/plants/{plant_id}",
            json={"name": name.strip() or None, "notes": notes.strip() or None},
        )
        flash("הפרטים נשמרו.")
        st.rerun()
    except ApiError as exc:
        show_error(exc)


def remove_image(image_id: str) -> None:
    """DELETE /v1/plants/{id}/images/{id}, also unreachable until PR 31.

    FINAL §20 decides what "delete" means and the endpoint implements it: an image
    the AI has used is hidden rather than destroyed, because an assessment that
    cited it must stay legible. The user is told which of the two happened.
    """
    try:
        result = delete(f"/v1/plants/{plant_id}/images/{image_id}")
    except ApiError as exc:
        show_error(exc)
        return

    if result.get("outcome") == "hidden":
        flash(
            "התמונה הוסרה מהגלריה. היא נשמרת כראיה לניתוח שהתבסס עליה.",
            kind="info",
            icon=":material/visibility_off:",
        )
    else:
        flash("התמונה נמחקה.")
    st.rerun()


with st.expander("עריכת פרטי הצמח", icon=":material/edit:"), st.form("pd_rename", border=False):
    new_name = st.text_input(
        "שם הצמח", value=data.get("name") or "", max_chars=120, key="pd_rename_name"
    )
    new_notes = st.text_area(
        "הערות", value=data.get("notes") or "", max_chars=2000, key="pd_rename_notes"
    )
    if st.form_submit_button("שמירה", type="primary", icon=":material/save:"):
        rename_plant(new_name, new_notes)

if gallery:
    with st.expander(f"גלריה ({len(gallery)})", icon=":material/photo_library:"):
        for row_start in range(0, len(gallery), 3):
            for column, image in zip(
                st.columns(3), gallery[row_start : row_start + 3], strict=False
            ):
                with column:
                    if image.get("thumbnail_url"):
                        st.image(image["thumbnail_url"], width="stretch")
                    if image.get("is_main"):
                        st.caption(":material/star: תמונה ראשית")
                    if st.button(
                        "מחיקה", key=f"pd_img_del_{image['id']}", icon=":material/delete:"
                    ):
                        remove_image(image["id"])

st.divider()


# --- an identification waiting for an answer -----------------------------------

if pending_identification:
    pending_id = pending_identification["id"]

    def confirm_identification(candidate_id: str, name: str | None) -> None:
        try:
            with st.spinner("מאשרים…"):
                post(
                    f"/v1/identifications/{pending_id}/confirm",
                    json={"candidate_id": candidate_id, "name": name},
                )
            flash("הזיהוי אושר.")
            st.rerun()
        except ApiError as exc:
            show_error(exc)

    def report_wrong_identification(scientific_name: str | None, note: str) -> None:
        try:
            post(
                f"/v1/identifications/{pending_id}/correct",
                json={"scientific_name": scientific_name, "note": note or None},
            )
        except ApiError as exc:
            show_error(exc)
            return
        flash(
            "הדיווח נשמר. אפשר לנסות שוב עם תמונות אחרות.",
            kind="info",
            icon=":material/flag:",
        )
        st.rerun()

    st.subheader("זיהינו את הצמח — האם זה נכון?", anchor=False)
    identification_card(
        pending_identification,
        on_confirm=confirm_identification,
        on_correct=report_wrong_identification,
        key_prefix="pd_ident",
    )
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


def await_proposal(started: dict, *, waiting: str) -> None:
    """Stay with a queued proposal until it exists, then say what happened.

    Care took 105 seconds on its first live run, so "it will appear here in a
    moment" was a promise the page then made no attempt to keep: it never polled,
    and a failed run left the user staring at the same empty state that invited
    them to press the button in the first place.
    """
    st.write(waiting)
    final = await_request(started["agent_request_id"])

    if final is None:
        flash(
            "ההצעה עדיין בהכנה. היא תופיע כאן ברגע שתהיה מוכנה.",
            kind="info",
            icon=":material/hourglass_top:",
        )
    elif final["status"] == "FAILED":
        # FINAL §25: no version, no rules, and the user is told rather than left
        # waiting for something that is not coming.
        flash(
            "לא הצלחנו להכין הצעה כרגע. אפשר לנסות שוב.",
            kind="warning",
            icon=":material/error:",
        )
    else:
        flash("ההצעה מוכנה וממתינה לאישור שלך.", icon=":material/pending_actions:")

    st.rerun()


if data.get("open_proposals"):
    proposals = guarded(lambda: get(f"/v1/plants/{plant_id}/care-plan/proposals")) or []
    if proposals:
        st.subheader("ממתין לאישור שלך", anchor=False)
        for proposal in proposals:
            proposal_card(proposal, on_approve=approve, on_reject=reject)


def complete_task(task_id: str, action: str) -> None:
    """Done and Skip, from the plant's own page.

    `care_task_card` renders those buttons only when it is given the callbacks,
    and this page never gave them - so a task that was due today was read-only
    here and had to be completed from Home. The two are the same action against
    the same endpoint; only one screen offered it.
    """
    try:
        result = post(f"/v1/care-tasks/{task_id}/{action}")
    except ApiError as exc:
        show_error(exc)
        return

    # Say when it comes round again. The scheduler creates the next occurrence
    # immediately, so without this the list simply redraws with a card that looks
    # like the one just completed and the action reads as having done nothing.
    note = "נרשם." if action == "done" else "דילגנו על המשימה."
    if result.get("next_due_at_utc"):
        note += f" הפעם הבאה: {due_text({'due_at_utc': result['next_due_at_utc']})}."
    flash(note)
    st.rerun()


upcoming = data.get("upcoming_tasks") or []
if upcoming:
    st.subheader("הטיפול הקרוב", anchor=False)
    for task in upcoming[:5]:
        # Done and Skip only on what is actually due. A task three days out drawn
        # with the same buttons invites completing it early, which anchors the
        # whole recurrence to today (A8) and quietly shifts the plan.
        actionable = task.get("status") in {"PENDING", "OVERDUE"} and is_due(task)
        care_task_card(
            task,
            key_prefix="pd",
            on_done=(lambda task_id: complete_task(task_id, "done")) if actionable else None,
            on_skip=(lambda task_id: complete_task(task_id, "skip")) if actionable else None,
        )

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
        queued = post(f"/v1/plants/{plant_id}/care-plan/proposals", json={"reason": "INITIAL_PLAN"})
    except ApiError as exc:
        show_error(exc)
        st.stop()

    await_proposal(queued, waiting="מכינים הצעה לתוכנית טיפול…")


# --- health ---------------------------------------------------------------------


def request_care_adjustment(assessment_id: str) -> None:
    """A health finding asks for the plan to be revisited (FINAL §16).

    The Health Agent cannot touch the plan; this raises a HEALTH_DRIVEN proposal
    the user then approves, which is the only route from a finding to a schedule.
    """
    try:
        started = post(
            f"/v1/plants/{plant_id}/care-plan/adjustment-proposals",
            json={
                "health_assessment_id": assessment_id,
                "reason": "ממצאי בדיקת הבריאות מצביעים על צורך בהתאמת התדירות.",
            },
        )
    except ApiError as exc:
        show_error(exc)
        return

    await_proposal(started, waiting="מכינים הצעה לעדכון התוכנית…")


def run_health_check(uploads: list[Any], gallery_ids: list[str], note: str | None) -> None:
    """Upload whatever is new, then start the check and stay with it.

    It used to fire the 202, promise that "the results will appear here in a
    moment", and never look again — so a failed run said nothing at all and a
    successful one appeared only if the user happened to reload. Reported as
    "did a health check and nothing happened".

    The photographs are uploaded here rather than in the dialog because a health
    check is prompted by something just noticed, and the picture of it does not
    exist until now. They go in under `context_type=health`, which keeps them out
    of the plant's gallery: evidence for one assessment is not a portrait.
    """
    image_ids = list(gallery_ids)
    try:
        for upload in uploads:
            created = post(
                f"/v1/plants/{plant_id}/images",
                files={
                    "file": (upload.name, upload.getvalue(), upload.type),
                    "context_type": (None, "health"),
                },
            )
            image_ids.append(created["id"])
    except ApiError as exc:
        show_error(exc)
        return

    try:
        started = post(
            f"/v1/plants/{plant_id}/health-checks",
            json={"image_ids": image_ids, "user_note": note},
        )
    except ApiError as exc:
        show_error(exc)
        return

    st.write("בודקים את הצמח…")
    final = await_request(started["agent_request_id"])

    if final is None:
        # Still running. Not a failure, and saying so would be a lie about a run
        # that is very likely about to succeed.
        close_health_dialog()
        flash(
            "הבדיקה נמשכת. התוצאה תופיע כאן ברגע שתהיה מוכנה.",
            kind="info",
            icon=":material/hourglass_top:",
        )
    elif final["status"] == "FAILED":
        # FINAL §25: the failure is visible, and nothing authoritative was written.
        flash(
            "הבדיקה לא הושלמה. אפשר לנסות שוב, ותמונות חדות יותר עוזרות.",
            kind="warning",
            icon=":material/error:",
        )
    else:
        close_health_dialog()
        flash("הבדיקה הושלמה.")

    st.rerun()


st.subheader("בריאות הצמח", anchor=False)

health_check_dialog(gallery, on_submit=run_health_check)

latest_id = health.get("latest_assessment_id")
if latest_id:
    latest = guarded(lambda: get(f"/v1/health-assessments/{latest_id}"))
    if latest:
        render_assessment(latest, on_adjust_plan=request_care_adjustment)

    with st.expander("בדיקות קודמות", icon=":material/history:"):
        render_history(guarded(lambda: get(f"/v1/plants/{plant_id}/health-history")) or [])
else:
    st.caption("עדיין לא בוצעה בדיקת בריאות לצמח הזה.")

st.divider()


# --- environment ---------------------------------------------------------------


def save_environment(values: dict[str, Any]) -> None:
    """Store the conditions, then ask for the plan to be looked at again.

    FINAL §12: an environment change produces a *proposal*, never a silent
    rewrite — the caption below has promised that since PR 20 while nothing
    could change the conditions and nothing reviewed the plan when they did.

    The review is only requested when there is a plan to review. Queueing a
    proposal for a plant that has no care plan yet would put a second, competing
    INITIAL_PLAN in front of the user.
    """
    try:
        put(f"/v1/plants/{plant_id}/environment", json=values)
    except ApiError as exc:
        show_error(exc)
        return

    if not data.get("care_plan"):
        flash("תנאי הגידול נשמרו.")
        st.rerun()

    try:
        queued = post(
            f"/v1/plants/{plant_id}/care-plan/proposals",
            json={"reason": "ENVIRONMENT_CHANGE"},
        )
    except ApiError:
        # The conditions are saved either way, and saying otherwise would send
        # the user back to re-enter something that is already stored.
        flash(
            "תנאי הגידול נשמרו. לא הצלחנו להתחיל בדיקה של תוכנית הטיפול כרגע.",
            kind="warning",
            icon=":material/warning:",
        )
        st.rerun()

    st.write("תנאי הגידול נשמרו. בודקים אם צריך לעדכן את תוכנית הטיפול…")
    await_proposal(queued, waiting="בודקים את תוכנית הטיפול…")


environment = data.get("environment")
with st.expander("תנאי הגידול", icon=":material/thermostat:"):
    if environment and any(environment.get(key) not in (None, "") for key in FIELD_LABELS):
        for key, label in FIELD_LABELS.items():
            value = environment.get(key)
            if value not in (None, ""):
                st.markdown(f"**{label}:** {describe(key, value)}")
        st.divider()
    else:
        st.caption("עדיין לא הוגדרו תנאי גידול. אפשר למלא כאן — כל שדה הוא רשות.")

    # FINAL §12: an environment change produces a proposal, never a silent
    # rewrite. Saying so here sets the expectation before the user changes one.
    st.caption("עדכון התנאים מפעיל בדיקה של תוכנית הטיפול, אך לא משנה אותה אוטומטית.")
    environment_form(environment, on_save=save_environment, key_prefix="pd_env")


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

            # Where it came from, which is the half of `KnowledgeResponse` that
            # reached nobody until PR 31. The endpoint has always returned
            # `sources`, and the whole point of PR 14's deterministic verification
            # is that a reader can tell a fetched, approved page from something
            # the model asserted. Rendering only the prose left them trusting all
            # of it equally.
            st.divider()
            st.caption(
                f"גרסה {knowledge.get('version_number')} · "
                f"פורסם {str(knowledge.get('published_at') or '')[:10]}"
            )
            with st.expander(f"מקורות ({len(knowledge.get('sources') or [])})"):
                render_sources(knowledge.get("sources") or [])

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
