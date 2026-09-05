"""Add plant: photographs, identification, confirmation (FINAL §8).

Three steps, matching the wireframes in UI_DESIGN_TOKENS. Step state lives in
`st.session_state` so a rerun does not lose a half-finished flow — a user who has
just uploaded four photographs should not have to do it again because a widget
changed.
"""

from __future__ import annotations

import time
from typing import Literal

import streamlit as st

from app.common.enums import ConfidenceLevel
from app.ui.components.layout import page_header, show_error
from app.ui.state.api_client import ApiError, get, post

MAX_IMAGES = 4
POLL_INTERVAL_SECONDS = 1.5
POLL_TIMEOUT_SECONDS = 180

STAGES: list[tuple[str, str]] = [
    ("IMAGES_RECEIVED", "התמונות התקבלו"),
    ("CONTEXT_LOADED", "ההקשר נטען"),
    ("ANALYZING", "מנתחים את התמונות"),
    ("PREPARING_RESULT", "מכינים את התוצאה"),
]

# The colour is a Streamlit semantic name; the hex comes from config.toml, so
# these render in the approved palette without any per-call styling.
CONFIDENCE_LABELS: dict[ConfidenceLevel, tuple[str, Literal["green", "orange", "red"]]] = {
    ConfidenceLevel.HIGH: ("גבוהה", "green"),
    ConfidenceLevel.MEDIUM: ("בינונית", "orange"),
    ConfidenceLevel.LOW: ("נמוכה", "red"),
}

STEP = "add_plant_step"
PLANT = "add_plant_plant_id"
REQUEST = "add_plant_request_id"
IDENT = "add_plant_identification_id"


def reset() -> None:
    for key in (STEP, PLANT, REQUEST, IDENT):
        st.session_state.pop(key, None)


step = st.session_state.get(STEP, "upload")


# --- step 1: photographs ------------------------------------------------------

if step == "upload":
    page_header("הוספת צמח", "שלב 1 מתוך 3")

    st.write("צלמו או העלו עד 4 תמונות ברורות של הצמח.")
    with st.expander("איך לצלם תמונה טובה?", icon=":material/lightbulb:"):
        st.markdown(
            """
            - צלמו לאור יום, בלי פלאש
            - כמה עלים שלמים במסגרת
            - תמונה אחת מקרוב על עלה בודד עוזרת מאוד
            - אם יש פרחים או פירות, שווה לצלם גם אותם
            """
        )

    uploads = st.file_uploader(
        "תמונות הצמח",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="add_plant_images",
        help="עד 4 תמונות, כל אחת עד 10MB.",
    )

    if uploads and len(uploads) > MAX_IMAGES:
        st.warning(f"אפשר להעלות עד {MAX_IMAGES} תמונות. ייבחרו הראשונות.", icon=":material/info:")
        uploads = uploads[:MAX_IMAGES]

    if uploads:
        for column, upload in zip(st.columns(len(uploads)), uploads, strict=False):
            with column:
                st.image(upload, width="stretch")

    note = st.text_area(
        "תיאור קצר (אופציונלי)",
        key="add_plant_note",
        placeholder="למשל: קיבלתי אותו במתנה, העלים החדשים בהירים יותר",
        help="אם יש לכם ניחוש מה הצמח, אפשר לכתוב כאן. זה מידע עוזר, לא קביעה.",
    )

    if st.button("המשך לזיהוי", type="primary", disabled=not uploads, icon=":material/arrow_back:"):
        try:
            with st.spinner("שומרים את התמונות…"):
                # The plant is created before it is named: FINAL §3 puts naming
                # after confirmation, so there is nothing to ask for yet.
                plant = post("/v1/plants", json={"notes": note.strip() or None})
                image_ids = [
                    post(
                        f"/v1/plants/{plant['id']}/images",
                        files={
                            "file": (upload.name, upload.getvalue(), upload.type),
                            "context_type": (None, "identification"),
                        },
                    )["id"]
                    for upload in uploads
                ]

                run = post(
                    f"/v1/plants/{plant['id']}/identification-runs",
                    json={"image_ids": image_ids, "user_description": note.strip() or None},
                )

            st.session_state[PLANT] = plant["id"]
            st.session_state[REQUEST] = run["agent_request_id"]
            st.session_state[STEP] = "identifying"
            st.rerun()
        except ApiError as exc:
            show_error(exc)


# --- step 2: identification in progress ---------------------------------------

elif step == "identifying":
    page_header("הוספת צמח", "שלב 2 מתוך 3")
    st.write("מזהים את הצמח שלך…")

    placeholder = st.empty()
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    final: dict | None = None

    while time.monotonic() < deadline:
        try:
            state = get(f"/v1/agent-requests/{st.session_state[REQUEST]}")
        except ApiError as exc:
            show_error(exc)
            break

        current = state.get("stage")
        reached = [s for s, _ in STAGES].index(current) if current in [s for s, _ in STAGES] else -1

        with placeholder.container():
            for index, (_, label) in enumerate(STAGES):
                if state["status"] in ("SUCCEEDED", "FAILED") or index < reached:
                    st.markdown(f":green[✓] {label}")
                elif index == reached:
                    st.markdown(f"**● {label}**")
                else:
                    st.markdown(f":gray[○ {label}]")

        if state["status"] in ("SUCCEEDED", "FAILED"):
            final = state
            break

        time.sleep(POLL_INTERVAL_SECONDS)

    if final is None:
        st.warning("הזיהוי נמשך זמן רב מהצפוי.", icon=":material/hourglass_top:")
        if st.button("בדיקה שוב"):
            st.rerun()
    elif final["status"] == "FAILED":
        # FINAL §25: the failure is visible and nothing authoritative was written.
        st.error("הזיהוי לא הושלם. אפשר לנסות שוב עם תמונות אחרות.", icon=":material/error:")
        if st.button("התחלה מחדש", type="primary"):
            reset()
            st.rerun()
    else:
        st.session_state[IDENT] = final.get("output_summary", {}).get("identification_id")
        st.session_state[STEP] = "confirm"
        st.rerun()


# --- step 3: confirmation -----------------------------------------------------

elif step == "confirm":
    page_header("הזיהוי הושלם", "שלב 3 מתוך 3")

    identification_id = st.session_state.get(IDENT)
    if not identification_id:
        st.warning("לא נמצאה תוצאת זיהוי.", icon=":material/info:")
        if st.button("התחלה מחדש"):
            reset()
            st.rerun()
        st.stop()

    try:
        identification = get(f"/v1/identifications/{identification_id}")
    except ApiError as exc:
        show_error(exc)
        st.stop()

    candidates = identification.get("candidates") or []

    if identification["status"] != "SUCCESS" or not candidates:
        st.warning(
            "לא הצלחנו לזהות את הצמח מהתמונות האלה. תמונות נוספות או ברורות יותר יעזרו.",
            icon=":material/photo_camera:",
        )
        if st.button("העלאת תמונות אחרות", type="primary"):
            reset()
            st.rerun()
        st.stop()

    primary = candidates[0]
    level = ConfidenceLevel(identification.get("confidence_level") or "LOW")
    label, colour = CONFIDENCE_LABELS[level]

    with st.container(border=True):
        st.subheader(primary.get("common_name") or primary["scientific_name"], anchor=False)
        st.caption(f"*{primary['scientific_name']}*")
        st.badge(f"רמת ביטחון: {label}", color=colour)

        if level is ConfidenceLevel.LOW:
            # FINAL §8 asks for a low-confidence warning. The user still decides -
            # hiding a weak result would leave them with nothing to act on - but
            # they should know what they are agreeing to.
            st.warning(
                "הזיהוי אינו ודאי. כדאי לבדוק את האפשרויות הנוספות לפני שמאשרים.",
                icon=":material/help:",
            )

        if identification.get("image_quality"):
            st.caption(identification["image_quality"])

        # Shown only when the deterministic check found a real matching page
        # (FINAL §8: the URL must never be invented).
        if identification.get("wikipedia_url"):
            st.link_button(
                "מידע נוסף בוויקיפדיה",
                identification["wikipedia_url"],
                icon=":material/open_in_new:",
            )

    chosen = primary["id"]
    if len(candidates) > 1:
        st.write("אפשרויות נוספות:")
        options = {
            candidate["id"]: (
                f"{candidate.get('common_name') or candidate['scientific_name']} "
                f"({candidate['scientific_name']})"
            )
            for candidate in candidates
        }
        chosen = st.radio(
            "בחירת הצמח",
            options=list(options),
            format_func=lambda key: options[key],
            label_visibility="collapsed",
        )

    actions = st.container(horizontal=True)
    with actions:
        if st.button("זה הצמח שלי", type="primary", icon=":material/check:"):
            try:
                with st.spinner("מאשרים…"):
                    result = post(
                        f"/v1/identifications/{identification_id}/confirm",
                        json={"candidate_id": chosen},
                    )
                st.session_state["pc_confirmed"] = result
                st.session_state[STEP] = "done"
                st.rerun()
            except ApiError as exc:
                show_error(exc)

        if st.button("נסה שוב", icon=":material/refresh:"):
            reset()
            st.rerun()


# --- done ---------------------------------------------------------------------

elif step == "done":
    result = st.session_state.get("pc_confirmed", {})

    if result.get("knowledge_pending"):
        # The "Knowledge Pending" screen from UI_DESIGN_TOKENS: the plant is added
        # and usable, while its professional information is researched.
        page_header("כמעט סיימנו")
        st.write("זיהינו את הצמח שלך ומכינים עבורו מידע מקצועי.")
        st.markdown(":green[✓] הזיהוי אושר")
        st.markdown(":green[✓] הצמח נוסף")
        st.markdown("**● הכנת מידע מקצועי**")
        st.markdown(":gray[○ אישור מידע]")
        st.info("אפשר להמשיך להשתמש באפליקציה. נעדכן כשהמידע יהיה מוכן.", icon=":material/info:")
    else:
        page_header("הצמח נוסף")
        st.success("הזיהוי אושר והצמח מוכן.", icon=":material/check_circle:")

    if st.button("לרשימת הצמחים", type="primary", icon=":material/arrow_back:"):
        plant_id = st.session_state.get(PLANT)
        reset()
        st.session_state.pop("pc_confirmed", None)
        st.session_state["pc_selected_plant"] = plant_id
        st.switch_page("app_pages/my_plants.py")
