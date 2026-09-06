"""Where a piece of knowledge came from (FINAL §10, PR 14's verification).

Lived inside `admin.py` until PR 31, which meant only an administrator could ever
see it. `GET /v1/species/{id}/knowledge` returns `sources` for every user and its
own docstring says "what a user sees: the current version *and where it came
from*" — the second half of that sentence reached nobody.

That matters more here than in the admin panel. The whole point of PR 14's
deterministic verification is that a reader can tell a fetched, approved page from
something the model asserted; hiding the distinction leaves them trusting all of
it equally, which is the opposite of what the machinery was built for.
"""

from __future__ import annotations

from typing import Any, Literal

import streamlit as st

BadgeColour = Literal["green", "orange", "red", "gray"]

SOURCE_CLASS_LABELS: dict[str, tuple[str, BadgeColour]] = {
    "APPROVED": ("מקור מאושר", "green"),
    "EXTERNAL_UNAPPROVED": ("מקור חיצוני לא מאושר", "orange"),
    "AI_GENERATED_REQUIRES_VERIFICATION": ("נוצר ב-AI — דורש אימות", "red"),
}

# Worst first, deliberately. A reader needs to see what is *not* backed by a
# fetched page before the text resting on it.
ORDER = {"AI_GENERATED_REQUIRES_VERIFICATION": 0, "EXTERNAL_UNAPPROVED": 1, "APPROVED": 2}


def render_sources(sources: list[dict[str, Any]]) -> None:
    if not sources:
        st.caption("לא צורפו מקורות.")
        return

    for source in sorted(sources, key=lambda s: ORDER.get(s.get("source_class", ""), 9)):
        label, colour = SOURCE_CLASS_LABELS.get(
            source.get("source_class", ""), (source.get("source_class", ""), "gray")
        )
        with st.container(border=True):
            st.badge(label, color=colour)
            if source.get("title"):
                st.write(f"**{source['title']}**")
            if source.get("publisher"):
                st.caption(source["publisher"])
            if source.get("url"):
                st.link_button("פתיחת המקור", source["url"], icon=":material/open_in_new:")
            if source.get("notes"):
                st.caption(source["notes"])
