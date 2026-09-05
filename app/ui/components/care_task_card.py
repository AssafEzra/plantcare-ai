"""Today's care: one task, and the two things a user can do about it.

UI_DESIGN_TOKENS "Home Dashboard". FINAL §5 asks for a dashboard where "the user
should understand in seconds what needs attention today", which is a constraint
on how much this card is allowed to say. It says the plant, the action, and
whether it is late — and then gets out of the way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import streamlit as st

from app.ui.components.care_plan import ACTION_LABELS


def _due_local(task: dict[str, Any]) -> datetime | None:
    raw = task.get("due_at_utc")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:  # pragma: no cover - the API returns ISO-8601
        return None
    return parsed.astimezone() if parsed.tzinfo else parsed.replace(tzinfo=UTC).astimezone()


def due_text(task: dict[str, Any]) -> str:
    """When, in words a person uses.

    An overdue task says how late it is rather than the date it was due: "3 days
    late" is actionable, "due on the 2nd" makes the reader do the arithmetic.
    """
    due = _due_local(task)
    if due is None:
        return ""

    if task.get("status") == "OVERDUE":
        days = max(0, (datetime.now(UTC) - due.astimezone(UTC)).days)
        if days == 0:
            return "באיחור"
        if days == 1:
            return "באיחור של יום"
        return f"באיחור של {days} ימים"

    today = datetime.now().astimezone().date()
    if due.date() == today:
        return f"היום בשעה {due:%H:%M}"
    if (due.date() - today).days == 1:
        return f"מחר בשעה {due:%H:%M}"
    return f"{due:%d/%m} בשעה {due:%H:%M}"


def care_task_card(
    task: dict[str, Any],
    *,
    on_done=None,
    on_skip=None,
    key_prefix: str = "task",
) -> None:
    """One task with Done and Skip (FINAL §5).

    Both actions are offered, always. Skip is not a lesser option to be hidden:
    a user who did not water today should be able to say so, and the schedule
    treats a skip differently from silence — silence becomes an overdue task and
    eventually a missed one, while a skip is a decision the plan can act on.
    """
    task_id = task["id"]
    action = task.get("action_type") or ""
    label, icon = ACTION_LABELS.get(action, (action, ":material/task_alt:"))
    overdue = task.get("status") == "OVERDUE"

    with st.container(border=True):
        # Icon and text together — UI_DESIGN_TOKENS is explicit that meaning is
        # never carried by a glyph or a colour alone.
        st.markdown(f"{icon} **{label}** · {task.get('plant_name') or 'הצמח שלי'}")

        if overdue:
            st.badge(due_text(task), icon=":material/schedule:", color="orange")
        else:
            st.caption(due_text(task))

        actions = st.container(horizontal=True)
        with actions:
            if on_done and st.button(
                "בוצע",
                key=f"{key_prefix}_done_{task_id}",
                type="primary",
                icon=":material/check:",
            ):
                on_done(task_id)

            if on_skip and st.button(
                "דילוג",
                key=f"{key_prefix}_skip_{task_id}",
                icon=":material/skip_next:",
            ):
                on_skip(task_id)


def overdue_summary_line(summary: dict[str, Any]) -> str:
    """One plant's outstanding work as a sentence (FINAL §13).

    The summary exists so a user returning from a fortnight away sees one line
    per plant instead of fourteen rows — which is technically complete and reads
    as a punishment.
    """
    actions = [ACTION_LABELS.get(a, (a, ""))[0] for a in summary.get("action_types") or []]
    if len(actions) > 1:
        joined = ", ".join(actions[:-1]) + f" ו{actions[-1]}"
    else:
        joined = actions[0] if actions else "טיפול"

    days = summary.get("days_late", 0)
    when = "מהיום" if days == 0 else ("מאתמול" if days == 1 else f"כבר {days} ימים")
    return f"**{summary.get('plant_name') or 'הצמח שלי'}** — {joined} ממתינים {when}"
