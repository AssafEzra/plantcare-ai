"""Add plant — step 1: photographs (FINAL §8, UI_DESIGN_TOKENS "Add Plant")."""

from __future__ import annotations

import streamlit as st

from app.ui.components.layout import page_header, show_error
from app.ui.state.api_client import ApiError, post

MAX_IMAGES = 4

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

if st.button(
    "המשך לזיהוי",
    type="primary",
    disabled=not uploads,
    icon=":material/arrow_back:",
):
    try:
        with st.spinner("שומרים את התמונות…"):
            # The plant is created before it is named: FINAL §3 puts naming after
            # confirmation, so there is nothing to ask for yet.
            plant = post("/v1/plants", json={"notes": note.strip() or None})

            for upload in uploads:
                post(
                    f"/v1/plants/{plant['id']}/images",
                    files={
                        "file": (upload.name, upload.getvalue(), upload.type),
                        "context_type": (None, "identification"),
                    },
                )

        st.session_state["pc_pending_plant_id"] = plant["id"]
        st.success(
            "התמונות נשמרו. הזיהוי ייפתח בשלב הבא של הפיתוח.",
            icon=":material/check_circle:",
        )
    except ApiError as exc:
        show_error(exc)
