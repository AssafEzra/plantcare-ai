"""Approving a care plan, in a window, with what actually changes (FINAL §12).

The proposal used to render inline on the plant page: the agent's one-sentence
summary, the full recommendations, the full new schedule, and two buttons. Every
part true, and it still left the user to read two schedules side by side and work
out for themselves that watering had moved from seven days to five.

Two changes here. It opens as a dialog, so the decision has the screen to itself
rather than competing with the health card and the timeline. And above the plan it
shows the difference — the agent's sentence first, because that is the *why*, then
the computed diff, which is the *what*.

The diff is `domain/services/care_plan_diff.py`: pure, deterministic, tested
without a screen. A comparison a user leans on to make a decision must not be
something a model rephrases differently each run.

A first plan has nothing to diff against, and says so by simply showing the plan.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from app.domain.services.care_plan_diff import RuleChange, diff_rules, has_changes
from app.ui.components.care_plan import (
    ACTION_LABELS,
    SOURCE_LABELS,
    WEEKDAY_LABELS,
    render_recommendations,
    render_rules,
)

STATE_KEY = "pd_proposal_open"

FIELD_LABELS: dict[str, str] = {
    "interval_days": "תדירות",
    "preferred_time_local": "שעה",
    "preferred_weekday": "יום בשבוע",
}

REVIEW_NOTICES: dict[str, tuple[str, str, str]] = {
    "pending": (
        "warning",
        "המידע המקצועי שעליו מבוססת התוכנית ממתין לאישור מומחה.",
        ":material/hourglass_top:",
    ),
    "rejected": (
        "error",
        "המידע המקצועי שעליו מבוססת התוכנית לא אושר. אנחנו מכינים גרסה מתוקנת.",
        ":material/report:",
    ),
}


def open_dialog(version_id: str) -> None:
    st.session_state[STATE_KEY] = version_id


def close_dialog() -> None:
    st.session_state.pop(STATE_KEY, None)


def _value_text(field: str, value: Any) -> str:
    if value is None:
        return "—"
    if field == "interval_days":
        days = int(value)
        return "כל יום" if days == 1 else f"כל {days} ימים"
    if field == "preferred_weekday":
        return WEEKDAY_LABELS.get(str(value), str(value))
    return str(value)[:5]


def change_line(change: RuleChange) -> str:
    """One rule's difference, as a sentence.

    Written to be read left to right in one pass: what it is, then what happened,
    then the numbers. Anything that needs the reader to hold two lists in their
    head is the problem this is solving.
    """
    label, _icon = ACTION_LABELS.get(change.action_type, (change.action_type, ""))

    if change.kind == "added":
        after = change.after or {}
        return f"**{label}** · נוסף, {_value_text('interval_days', after.get('interval_days'))}"
    if change.kind == "removed":
        return f"**{label}** · הוסר"
    if change.kind == "changed":
        before, after = change.before or {}, change.after or {}
        parts = [
            f"{FIELD_LABELS.get(field, field)}: "
            f"{_value_text(field, before.get(field))} ← {_value_text(field, after.get(field))}"
            for field in change.fields
        ]
        return f"**{label}** · " + " · ".join(parts)
    return f"**{label}** · ללא שינוי"


def render_changes(current: list[dict[str, Any]], proposed: list[dict[str, Any]]) -> None:
    """The diff, or nothing at all when there is no previous plan."""
    if not current:
        return

    changes = diff_rules(current, proposed)
    if not has_changes(changes):
        # Worth saying out loud. A proposal that changes no rule is a
        # recommendation change only, and a user who approves expecting a new
        # schedule should not have to discover that by watching for one.
        st.info("לוח הזמנים נשאר כפי שהוא. ההמלצות המקצועיות עודכנו.", icon=":material/info:")
        return

    st.markdown("**מה משתנה**")
    for change in changes:
        if change.kind == "unchanged":
            continue
        st.markdown(f"- {change_line(change)}")

    unchanged = [c for c in changes if c.kind == "unchanged"]
    if unchanged:
        st.caption(
            "ללא שינוי: "
            + " · ".join(
                ACTION_LABELS.get(c.action_type, (c.action_type, ""))[0] for c in unchanged
            )
        )


def proposal_dialog(
    proposals: list[dict[str, Any]],
    *,
    on_approve: Callable[[str], None],
    on_reject: Callable[[str], None],
) -> None:
    """Render the open proposal as a dialog, when one has been opened."""
    version_id = st.session_state.get(STATE_KEY)
    if not version_id:
        return

    proposal = next((p for p in proposals if str(p.get("id")) == str(version_id)), None)
    if proposal is None:
        # Approved or rejected in another tab, or the page reloaded. Closing is
        # the honest response; the alternative is a dialog about a decision that
        # has already been taken.
        close_dialog()
        return

    @st.dialog("הצעת עדכון לתוכנית טיפול", width="large")
    def _dialog() -> None:
        st.subheader(
            SOURCE_LABELS.get(proposal["source_type"], proposal["source_type"]), anchor=False
        )
        st.caption(f"גרסה {proposal['version_number']}")

        notice = REVIEW_NOTICES.get(proposal.get("knowledge_review", "reviewed"))
        if notice:
            kind, message, icon = notice
            {"warning": st.warning, "error": st.error}[kind](message, icon=icon)

        # The agent's own sentence first: it is the reason, and the diff below is
        # the consequence. Reversed, the numbers arrive with nothing to explain
        # them.
        if proposal.get("change_summary"):
            st.info(proposal["change_summary"], icon=":material/edit_note:")

        render_changes(proposal.get("current_rules") or [], proposal.get("rules") or [])

        st.divider()
        st.markdown("**ההמלצות המקצועיות**")
        render_recommendations(proposal.get("professional_recommendations") or {})

        st.markdown("**מה נתזמן עבורך**")
        render_rules(proposal.get("rules") or [])

        missing = (proposal.get("operational_preferences") or {}).get("missing_context") or []
        if missing:
            # Not a question. Nothing here waits on an answer (A20).
            st.caption("מידע שהיה עוזר לדייק את התוכנית: " + " · ".join(missing))

        actions = st.container(horizontal=True)
        with actions:
            if st.button(
                "אישור התוכנית",
                key=f"pdlg_approve_{version_id}",
                type="primary",
                icon=":material/check:",
            ):
                close_dialog()
                on_approve(str(version_id))

            if st.button("דחייה", key=f"pdlg_reject_{version_id}", icon=":material/block:"):
                close_dialog()
                on_reject(str(version_id))

            if st.button("סגירה", key=f"pdlg_close_{version_id}"):
                close_dialog()
                st.rerun()

    _dialog()
