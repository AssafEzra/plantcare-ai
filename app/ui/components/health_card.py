"""Health assessment rendering (FINAL §16, UI_DESIGN_TOKENS).

    "The Agent must not present definitive diagnosis."

The interface carries as much of that as the schema does. Observations and
possible issues are rendered in visibly different registers — one is what was
seen, the other what it might mean — and an issue always shows the evidence it
rests on, so a user can disagree with the reasoning rather than only the verdict.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.components.status import status_badge, trend_badge

SEVERITY_LABELS: dict[int, str] = {
    1: "קלה",
    2: "קלה-בינונית",
    3: "בינונית",
    4: "משמעותית",
    5: "חמורה",
}


def render_assessment(assessment: dict[str, Any], *, on_adjust_plan=None) -> None:
    """One assessment in full."""
    status = assessment.get("overall_status", "UNKNOWN")
    observations = assessment.get("observations") or []
    issues = assessment.get("possible_issues") or []
    recommendations = assessment.get("recommendations") or []

    with st.container(border=True):
        header, badges = st.columns([2, 1])
        with header:
            st.subheader("תוצאות הבדיקה", anchor=False)
        with badges:
            status_badge(status)
            if assessment.get("trend"):
                trend_badge(assessment["trend"])

        if status == "UNKNOWN":
            # FINAL §16: an insufficient check is saved with its reason. Presented
            # as an outcome rather than an error, because it is one - and the
            # reason says what would actually help.
            st.info(
                assessment.get("insufficient_information_reason")
                or "לא הצלחנו לקבוע את מצב הצמח מהתמונות האלה.",
                icon=":material/help:",
            )

        if observations:
            st.markdown("**מה נראה בתמונות**")
            for observation in observations:
                st.markdown(f"- {observation.get('observation_text', '')}")

        if issues:
            # Deliberately framed as possibilities, and each one shows what it
            # rests on. A finding a user cannot check is a finding they can only
            # believe or ignore.
            st.markdown("**ממצאים אפשריים**")
            st.caption("אלה אפשרויות, לא אבחנה. כדאי לבדוק אותן מול הצמח עצמו.")
            for issue in issues:
                with st.container(border=True):
                    severity = issue.get("severity")
                    line = f"**{issue.get('issue_name', '')}**"
                    if severity in SEVERITY_LABELS:
                        line += f" · חומרה {SEVERITY_LABELS[severity]}"
                    st.markdown(line)
                    if issue.get("evidence"):
                        st.caption(f"על סמך: {issue['evidence']}")

        if recommendations:
            st.markdown("**מה כדאי לעשות**")
            wants_plan_change = False
            for recommendation in recommendations:
                st.markdown(f"- {recommendation.get('recommendation_text', '')}")
                wants_plan_change = wants_plan_change or recommendation.get(
                    "requires_care_plan_adjustment", False
                )

            if wants_plan_change and on_adjust_plan:
                # §16: the Health Agent cannot change the plan. This raises a
                # proposal the user approves, which is the only route there is.
                st.caption("חלק מההמלצות נוגעות לתדירות הטיפול עצמה.")
                if st.button(
                    "הצעת עדכון לתוכנית הטיפול",
                    type="primary",
                    icon=":material/edit_calendar:",
                    key=f"adjust_{assessment.get('id')}",
                ):
                    on_adjust_plan(assessment.get("id"))

        if assessment.get("sources"):
            with st.expander("מקורות", icon=":material/link:"):
                for source in assessment["sources"]:
                    if source.get("url"):
                        st.markdown(f"- [{source.get('title') or source['url']}]({source['url']})")
                    elif source.get("title"):
                        st.markdown(f"- {source['title']}")


def render_history(entries: list[dict[str, Any]]) -> None:
    """Past assessments, newest first.

    Kept deliberately terse: the detail lives on each assessment, and a history
    that repeated every finding would bury the one thing history is for, which is
    seeing the direction of travel.
    """
    if not entries:
        st.caption("עדיין לא בוצעו בדיקות בריאות לצמח הזה.")
        return

    for entry in entries:
        with st.container(border=True):
            status_badge(entry.get("overall_status", "UNKNOWN"))
            if entry.get("trend"):
                trend_badge(entry["trend"])
            st.caption(str(entry.get("created_at", ""))[:16].replace("T", " "))
