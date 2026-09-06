"""The "is this your plant?" card (FINAL §8, UI_DESIGN_TOKENS "Identification Result").

Shared by the Add Plant wizard and the plant dashboard, because the same question
can be reached two ways. The wizard asks it immediately after the analysis; the
dashboard asks it whenever a plant is still waiting for an answer.

That second route is the reason this file exists. The card used to live inside
`add_plant.py`, reachable only through `st.session_state`. A refresh, a closed
tab, or a walk away between "analysing" and the result left the identification
finished in the database and unanswerable in the interface - the plant's own page
said "הצמח עדיין לא זוהה" and offered nothing to press. The confirmation is a
property of the plant, not of a wizard step, so it renders wherever the plant is.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import streamlit as st

from app.common.enums import ConfidenceLevel

# The colour is a Streamlit semantic name; the hex comes from config.toml, so
# these render in the approved palette without any per-call styling.
CONFIDENCE_LABELS: dict[ConfidenceLevel, tuple[str, Literal["green", "orange", "red"]]] = {
    ConfidenceLevel.HIGH: ("גבוהה", "green"),
    ConfidenceLevel.MEDIUM: ("בינונית", "orange"),
    ConfidenceLevel.LOW: ("נמוכה", "red"),
}


def candidate_label(candidate: dict) -> str:
    common = candidate.get("common_name")
    return f"{common} ({candidate['scientific_name']})" if common else candidate["scientific_name"]


def identification_card(
    identification: dict,
    *,
    on_confirm: Callable[[str, str | None], None],
    on_restart: Callable[[], None] | None = None,
    on_correct: Callable[[str | None, str], None] | None = None,
    restart_label: str = "נסה שוב",
    key_prefix: str = "ident",
    wikipedia_url: str | None = None,
) -> None:
    """Render the result and collect the user's answer.

    `on_confirm` receives the chosen candidate id and the name the user typed
    (or `None`). Naming is optional and the API fills it from the candidate's
    common name when it is left empty (A2) - so the field is an invitation, not
    a gate in front of a plant the user has already waited for.
    """
    candidates = identification.get("candidates") or []
    if not candidates:
        return

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
        if wikipedia_url:
            st.link_button("מידע נוסף בוויקיפדיה", wikipedia_url, icon=":material/open_in_new:")

    chosen = primary["id"]
    if len(candidates) > 1:
        st.write("אפשרויות נוספות:")
        options = {candidate["id"]: candidate_label(candidate) for candidate in candidates}
        chosen = st.radio(
            "בחירת הצמח",
            options=list(options),
            format_func=lambda key: options[key],
            label_visibility="collapsed",
            key=f"{key_prefix}_choice",
        )

    name = st.text_input(
        "איך לקרוא לצמח?",
        key=f"{key_prefix}_name",
        placeholder=primary.get("common_name") or primary["scientific_name"],
        help="אפשר להשאיר ריק - נשתמש בשם הצמח.",
        max_chars=120,
    )

    actions = st.container(horizontal=True)
    with actions:
        if st.button(
            "זה הצמח שלי",
            type="primary",
            icon=":material/check:",
            key=f"{key_prefix}_confirm",
        ):
            on_confirm(chosen, name.strip() or None)

        if on_restart and st.button(
            restart_label, icon=":material/refresh:", key=f"{key_prefix}_restart"
        ):
            on_restart()

    # A13, and the endpoint that had no caller until PR 31: the user can say the
    # model is wrong. It records history and changes nothing - FINAL §8 keeps
    # confirmation as the only thing that moves a plant - so the copy has to be
    # honest that this is a report rather than a correction that takes effect.
    if on_correct:
        with st.expander("אף אחת מהאפשרויות אינה נכונה", icon=":material/flag:"):
            st.caption(
                "הדיווח נשמר בהיסטוריה של הצמח ומסייע לנו להשתפר. "
                "הוא אינו קובע את המין - לשם כך צריך לאשר אפשרות או לנסות תמונות אחרות."
            )
            with st.form(f"{key_prefix}_correct", border=False):
                guess = st.text_input(
                    "אם ידוע לך, מה המין?",
                    placeholder="למשל: Monstera deliciosa",
                    max_chars=200,
                    key=f"{key_prefix}_correct_name",
                )
                note = st.text_area(
                    "מה לא מתאים?", max_chars=1000, key=f"{key_prefix}_correct_note"
                )
                if st.form_submit_button("שליחת דיווח", icon=":material/send:"):
                    if not guess.strip() and not note.strip():
                        st.warning("יש למלא שם מין או הערה.", icon=":material/info:")
                    else:
                        on_correct(guess.strip() or None, note.strip())
