"""Starting a health check, with photographs taken now (FINAL §16).

Reported from real use: *"when starting a health check it should lead to a new
window and give option to load pic, not just select one"*.

The old form was an inline box offering a multiselect over images already in the
plant's gallery. That is the wrong shape for the thing being asked: a health
check is prompted by something the user has *just noticed*, and the photograph
that shows it does not exist yet. Worse, a plant with an empty gallery reached a
dead end - "you need to upload a photograph first" with nothing there to upload
with.

A dialog rather than a page: the check belongs to the plant the user is looking
at, and its result lands on that same page. Sending them somewhere else and back
would lose the context that makes the answer meaningful.

Uploading is a real HTTP round trip per file, so it happens on submit rather than
on selection - an upload that only matters if the check is actually sent should
not happen while the user is still deciding.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from app.ui.components.image_picker import clear as clear_captures
from app.ui.components.image_picker import image_picker

MAX_IMAGES = 4

STATE_KEY = "pd_health_dialog_open"


def open_dialog() -> None:
    st.session_state[STATE_KEY] = True


def close_dialog() -> None:
    st.session_state.pop(STATE_KEY, None)


def _gallery_choices(gallery: list[dict[str, Any]]) -> dict[str, str]:
    return {
        image["id"]: f"תמונה מ-{str(image.get('created_at', ''))[:10]}"
        for image in gallery
        if image.get("id")
    }


def health_check_dialog(
    gallery: list[dict[str, Any]],
    *,
    on_submit: Callable[[list[Any], list[str], str | None], None],
    key_prefix: str = "pd_health",
) -> None:
    """Render the dialog when it has been opened.

    `on_submit` receives the freshly uploaded files, the ids of gallery images the
    user also ticked, and the note. Uploading is the caller's job because it needs
    the API client and the plant id, and this component is meant to stay ignorant
    of both.
    """
    if not st.session_state.get(STATE_KEY):
        return

    @st.dialog("בדיקת בריאות", width="large")
    def _dialog() -> None:
        st.caption(
            "אפשר לצלם עכשיו, להעלות מהמכשיר, או לבחור תמונות קיימות — "
            "עד ארבע בסך הכול. תמונות חדות באור יום, מקרוב ומרחוק, עוזרות מאוד."
        )

        uploads = image_picker(
            key_prefix=key_prefix,
            max_images=MAX_IMAGES,
            upload_label="תמונות חדשות",
            help_text="אפשר לבחור כמה תמונות יחד.",
        )

        choices = _gallery_choices(gallery)
        chosen: list[str] = []
        if choices:
            chosen = st.multiselect(
                "או מתוך הגלריה",
                options=list(choices),
                format_func=lambda key: choices[key],
                max_selections=MAX_IMAGES,
                key=f"{key_prefix}_images",
            )

        note = st.text_input(
            "מה מטריד אותך? (אופציונלי)",
            key=f"{key_prefix}_note",
            placeholder="למשל: העלים התחתונים מצהיבים כבר שבועיים",
        )

        total = len(uploads or []) + len(chosen)
        if total > MAX_IMAGES:
            # Said here rather than left to the server: the user has already spent
            # the effort of choosing, and a 422 after submit wastes an upload.
            st.warning(
                f"נבחרו {total} תמונות. אפשר עד {MAX_IMAGES} בבדיקה אחת.",
                icon=":material/photo_library:",
            )
        elif total == 0:
            st.info("צריך לפחות תמונה אחת כדי לבדוק.", icon=":material/info:")

        actions = st.container(horizontal=True)
        with actions:
            if st.button(
                "שליחה לבדיקה",
                type="primary",
                disabled=not (1 <= total <= MAX_IMAGES),
                key=f"{key_prefix}_submit",
                icon=":material/send:",
            ):
                on_submit(list(uploads or []), list(chosen), note.strip() or None)
                clear_captures(key_prefix)

            if st.button("ביטול", key=f"{key_prefix}_cancel"):
                close_dialog()
                clear_captures(key_prefix)
                st.rerun()

    _dialog()
