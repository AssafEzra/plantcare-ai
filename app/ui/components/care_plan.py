"""Care plan and proposal rendering (UI_DESIGN_TOKENS "Care Plan", FINAL §12).

The proposal card is where §12's central rule becomes visible: professional
recommendations are shown as text with no edit control anywhere near them, while
frequency and time sit in inputs. A user should be able to tell which half they
own by looking, without reading a note about it.
"""

from __future__ import annotations

from typing import Any, Literal

import streamlit as st

ACTION_LABELS: dict[str, tuple[str, str]] = {
    "WATERING": ("השקיה", ":material/water_drop:"),
    "FERTILIZING": ("דישון", ":material/eco:"),
    "REPOTTING": ("החלפת עציץ", ":material/potted_plant:"),
    "PRUNING": ("גיזום", ":material/content_cut:"),
    "MISTING": ("ריסוס", ":material/mist:"),
    "ROTATING": ("סיבוב", ":material/rotate_right:"),
    "INSPECTION": ("בדיקה", ":material/search:"),
}

SOURCE_LABELS: dict[str, str] = {
    "INITIAL_PLAN": "תוכנית ראשונה",
    "OPERATIONAL_ADJUSTMENT": "שינוי תפעולי",
    "ENVIRONMENT_CHANGE": "שינוי בסביבה",
    "HEALTH_DRIVEN": "בעקבות בדיקת בריאות",
    "RE_IDENTIFICATION": "זיהוי מחדש",
}

BadgeColour = Literal["green", "orange", "blue", "gray"]

STATUS_LABELS: dict[str, tuple[str, BadgeColour]] = {
    "PROPOSED": ("ממתין לאישור", "orange"),
    "ACTIVE": ("פעילה", "green"),
    "SUPERSEDED": ("הוחלפה", "gray"),
    "REJECTED": ("נדחתה", "gray"),
}

WEEKDAY_LABELS: dict[str, str] = {
    "SUNDAY": "ראשון",
    "MONDAY": "שני",
    "TUESDAY": "שלישי",
    "WEDNESDAY": "רביעי",
    "THURSDAY": "חמישי",
    "FRIDAY": "שישי",
    "SATURDAY": "שבת",
}


def _interval_text(days: int) -> str:
    """Say it the way a person would.

    "כל 7 ימים" is correct and reads like a database row; "כל שבוע" is what the
    user actually has to remember.
    """
    if days == 1:
        return "כל יום"
    if days == 7:
        return "כל שבוע"
    if days == 14:
        return "כל שבועיים"
    if days % 7 == 0:
        return f"כל {days // 7} שבועות"
    if days == 30:
        return "כל חודש"
    return f"כל {days} ימים"


def rule_line(rule: dict[str, Any]) -> str:
    label, _ = ACTION_LABELS.get(rule["action_type"], (rule["action_type"], ""))
    time_text = str(rule.get("preferred_time_local", ""))[:5]
    line = f"**{label}** · {_interval_text(rule['interval_days'])} בשעה {time_text}"
    if rule.get("preferred_weekday"):
        line += (
            f" · בימי {WEEKDAY_LABELS.get(rule['preferred_weekday'], rule['preferred_weekday'])}"
        )
    return line


def render_rules(rules: list[dict[str, Any]]) -> None:
    if not rules:
        st.caption("אין כללי טיפול בתוכנית הזו.")
        return

    for rule in rules:
        with st.container(border=True):
            st.markdown(rule_line(rule))
            if rule.get("instructions"):
                st.caption(rule["instructions"])


def render_recommendations(recommendations: dict[str, Any]) -> None:
    """The professional half. Text only — no input anywhere in this function.

    FINAL §12: this content is not directly editable. The clearest way to say so
    is to give it nothing to type into.
    """
    if recommendations.get("summary"):
        st.write(recommendations["summary"])

    for field, label in (
        ("watering", "השקיה"),
        ("light", "אור"),
        ("feeding", "דישון"),
        ("seasonal_notes", "הערות עונתיות"),
    ):
        if recommendations.get(field):
            with st.expander(label):
                st.write(recommendations[field])

    for warning in recommendations.get("warnings") or []:
        st.warning(warning, icon=":material/warning:")


def proposal_card(
    proposal: dict[str, Any],
    *,
    on_approve,
    on_reject,
    key_prefix: str = "proposal",
) -> None:
    """One open proposal, with the two decisions the user actually has.

    `missing_context` (A20) is rendered as "what would have helped", not as a
    question. The MVP has no status, table or endpoint that could carry an answer
    back, so phrasing it as a question would promise a conversation that cannot
    happen.
    """
    version_id = proposal["id"]
    recommendations = proposal.get("professional_recommendations") or {}
    preferences = proposal.get("operational_preferences") or {}
    missing = preferences.get("missing_context") or []

    with st.container(border=True):
        header, badge = st.columns([3, 1])
        with header:
            st.subheader(
                SOURCE_LABELS.get(proposal["source_type"], proposal["source_type"]), anchor=False
            )
            st.caption(f"גרסה {proposal['version_number']}")
        with badge:
            label, colour = STATUS_LABELS.get(proposal["status"], (proposal["status"], "gray"))
            st.badge(label, color=colour)

        if proposal.get("change_summary"):
            st.info(proposal["change_summary"], icon=":material/edit_note:")

        st.markdown("**ההמלצות המקצועיות**")
        render_recommendations(recommendations)

        st.markdown("**מה נתזמן עבורך**")
        render_rules(proposal.get("rules") or [])

        if missing:
            # Not a question. Nothing here waits on an answer.
            st.caption("מידע שהיה עוזר לדייק את התוכנית: " + " · ".join(missing))

        actions = st.container(horizontal=True)
        with actions:
            if st.button(
                "אישור התוכנית",
                key=f"{key_prefix}_approve_{version_id}",
                type="primary",
                icon=":material/check:",
            ):
                on_approve(version_id)

            if st.button(
                "דחייה",
                key=f"{key_prefix}_reject_{version_id}",
                icon=":material/block:",
            ):
                on_reject(version_id)


def active_plan_card(plan: dict[str, Any], *, on_adjust=None, key_prefix: str = "plan") -> None:
    """The plan in force, and the one thing the user may change about it.

    The adjustment form offers frequency and time and nothing else. That is the
    editable half of §12, and putting it in its own expander keeps it visually
    separate from the advice above it.
    """
    with st.container(border=True):
        st.subheader("תוכנית הטיפול", anchor=False)
        st.caption(
            f"גרסה {plan['version_number']} · "
            f"{SOURCE_LABELS.get(plan['source_type'], plan['source_type'])}"
        )
        st.badge("פעילה", color="green")

        st.markdown("**ההמלצות המקצועיות**")
        render_recommendations(plan.get("professional_recommendations") or {})

        st.markdown("**התזמון שלך**")
        render_rules(plan.get("rules") or [])

        if on_adjust is None:
            return

        with st.expander("שינוי תדירות או שעה", icon=":material/tune:"):
            st.caption(
                "אפשר לשנות מתי מזכירים לך. ההמלצות המקצועיות נשארות כפי שהן "
                "ונשמרות במלואן בגרסה החדשה."
            )
            overrides: dict[str, Any] = {}
            for rule in plan.get("rules") or []:
                label, _ = ACTION_LABELS.get(rule["action_type"], (rule["action_type"], ""))
                days = st.number_input(
                    f"{label} — כל כמה ימים",
                    min_value=1,
                    max_value=365,
                    value=int(rule["interval_days"]),
                    key=f"{key_prefix}_days_{rule['id']}",
                )
                if int(days) != int(rule["interval_days"]):
                    overrides[rule["action_type"]] = {"interval_days": int(days)}

            summary = st.text_input(
                "מה השתנה?",
                key=f"{key_prefix}_summary",
                placeholder="למשל: הדירה חמה יותר בקיץ",
            )
            if st.button(
                "שמירת השינוי",
                key=f"{key_prefix}_adjust",
                type="primary",
                disabled=not overrides or not summary.strip(),
            ):
                on_adjust(plan["id"], overrides, summary.strip())
