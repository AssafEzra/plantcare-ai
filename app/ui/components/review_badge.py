"""Has a human read the professional information behind this? (PR 33, FINAL §10)

A plant no longer waits for admin review before it gets knowledge and a care
plan — finished research is enough. That is a better first run, and it is only
honest if the screens say what the plan rests on.

Three states, and the badge exists to keep them apart:

* **reviewed** — a published version. Nothing is drawn; this is the ordinary case
  and a badge on every plan would train people to stop reading badges.
* **pending** — finished research nobody has approved yet.
* **rejected** — an administrator judged that research wrong. The plan keeps
  running, because leaving the plant with no schedule at all is worse, and a
  corrected version is already being prepared.
"""

from __future__ import annotations

from typing import Literal

import streamlit as st

BadgeColour = Literal["red", "orange"]

LABELS: dict[str, tuple[str, BadgeColour]] = {
    "pending": ("ממתין לאישור מומחה", "orange"),
    "rejected": ("המידע המקצועי לא אושר", "red"),
}


def review_badge(review: str | None) -> None:
    found = LABELS.get(review or "reviewed")
    if not found:
        return
    label, colour = found
    st.badge(label, color=colour, icon=":material/verified_user:")
