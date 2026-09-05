"""Admin panel (FINAL §29).

Reaching this page at all requires an ADMIN role, but that is a courtesy: the
navigation entry is hidden for other users while every admin route and every
admin table is independently gated server-side. Hiding UI is never the control.

Three tabs are live here — drafts, published knowledge and approved sources. The
review screen is the one that matters: FINAL §11 says the Knowledge Agent never
publishes, and this is the human step that sentence is describing. It is built to
make the *weak* parts of a draft findable, because a reviewer with limited time
who reads top to bottom will approve the fourteenth section least carefully.
"""

from __future__ import annotations

from typing import Any, Literal

import streamlit as st

from app.ui.components.layout import empty_state, guarded, page_header, show_error
from app.ui.state.api_client import ApiError, get, patch, post

SECTION_LABELS: dict[str, str] = {
    "identification": "זיהוי",
    "description": "תיאור",
    "light": "אור",
    "watering": "השקיה",
    "soil": "מצע",
    "temperature": "טמפרטורה",
    "humidity": "לחות",
    "fertilization": "דישון",
    "repotting": "החלפת עציץ",
    "pruning": "גיזום",
    "propagation": "ריבוי",
    "common_problems": "בעיות נפוצות",
    "toxicity_safety": "רעילות ובטיחות",
}

# The colour is a Streamlit semantic name; the hex comes from config.toml, so
# these render in the approved palette without any per-call styling.
BadgeColour = Literal["red", "orange", "green", "blue", "gray"]

DRAFT_STATUS_LABELS: dict[str, tuple[str, BadgeColour]] = {
    "DRAFT": ("טיוטה", "gray"),
    "RESEARCHING": ("במחקר", "blue"),
    "READY_FOR_REVIEW": ("ממתין לבדיקה", "orange"),
    "APPROVED": ("אושר", "green"),
    "REJECTED": ("נדחה", "red"),
    "FAILED": ("נכשל", "red"),
}

SOURCE_CLASS_LABELS: dict[str, tuple[str, BadgeColour]] = {
    "APPROVED": ("מקור מאושר", "green"),
    "EXTERNAL_UNAPPROVED": ("מקור חיצוני לא מאושר", "orange"),
    "AI_GENERATED_REQUIRES_VERIFICATION": ("נוצר ב-AI — דורש אימות", "red"),
}

# Below this, a section is surfaced to the reviewer rather than left to be found.
WEAK_SECTION = 0.5

page_header("ניהול", "אזור מנהלי מערכת")

drafts_tab, published_tab, sources_tab, reports_tab, monitoring_tab = st.tabs(
    ["טיוטות ידע", "ידע מפורסם", "מקורות מאושרים", "דיווחי משתמשים", "ניטור סוכנים"]
)


def status_badge(status: str) -> None:
    label, colour = DRAFT_STATUS_LABELS.get(status, (status, "gray"))
    st.badge(label, color=colour)


def render_sources(sources: list[dict[str, Any]]) -> None:
    """Provenance, with the unverified claims impossible to miss.

    Ordered worst-first rather than as the model listed them. A reviewer needs to
    see what is *not* backed by a fetched page before deciding whether the text
    resting on it can be published.
    """
    if not sources:
        st.caption("לא צורפו מקורות.")
        return

    order = {"AI_GENERATED_REQUIRES_VERIFICATION": 0, "EXTERNAL_UNAPPROVED": 1, "APPROVED": 2}
    for source in sorted(sources, key=lambda s: order.get(s.get("source_class", ""), 9)):
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


def render_sections(sections: dict[str, Any]) -> None:
    weak = [
        name
        for name, section in sections.items()
        if isinstance(section, dict) and section.get("confidence", 1.0) < WEAK_SECTION
    ]
    if weak:
        st.warning(
            "סעיפים בביטחון נמוך: " + ", ".join(SECTION_LABELS.get(n, n) for n in weak),
            icon=":material/priority_high:",
        )

    for name, label in SECTION_LABELS.items():
        section = sections.get(name)
        if not isinstance(section, dict):
            continue
        confidence = section.get("confidence", 0.0)
        with st.expander(f"{label} · ביטחון {confidence:.2f}", expanded=confidence < WEAK_SECTION):
            st.write(section.get("text", ""))


# --- drafts -------------------------------------------------------------------

with drafts_tab:
    status_filter = st.selectbox(
        "סינון לפי סטטוס",
        options=["READY_FOR_REVIEW", "RESEARCHING", "REJECTED", "FAILED", "APPROVED", "הכול"],
        format_func=lambda value: (
            "הכול" if value == "הכול" else DRAFT_STATUS_LABELS.get(value, (value, ""))[0]
        ),
        key="admin_draft_status",
    )

    params = {} if status_filter == "הכול" else {"status": status_filter}
    drafts = guarded(lambda: get("/v1/admin/knowledge-drafts", params=params))

    if drafts is None:
        pass
    elif not drafts:
        empty_state(
            "אין טיוטות בסטטוס הזה",
            "טיוטה נפתחת אוטומטית כשמשתמש מאשר זיהוי של מין שאין לו עדיין ידע מפורסם.",
            icon=":material/menu_book:",
        )
    else:
        for draft in drafts:
            content = draft.get("content") or {}
            sections = content.get("sections") or {}
            with st.container(border=True):
                header, badge = st.columns([4, 1])
                with header:
                    st.subheader(draft["species_id"][:8], anchor=False)
                    st.caption(f"שפה: {draft['language']} · עודכן: {draft['updated_at'][:16]}")
                with badge:
                    status_badge(draft["status"])

                if draft.get("admin_note"):
                    st.info(draft["admin_note"], icon=":material/comment:")

                if not sections:
                    st.caption("אין עדיין תוכן לבדיקה.")
                else:
                    if draft.get("research_notes"):
                        st.caption(f"הערות מחקר: {draft['research_notes']}")
                    render_sections(sections)
                    st.markdown("**מקורות**")
                    render_sources(content.get("sources") or [])

                actions = st.container(horizontal=True)
                reviewable = draft["status"] == "READY_FOR_REVIEW"

                with actions:
                    if st.button(
                        "אישור ופרסום",
                        key=f"approve_{draft['id']}",
                        type="primary",
                        disabled=not reviewable,
                        icon=":material/publish:",
                    ):
                        try:
                            result = post(
                                f"/v1/admin/knowledge-drafts/{draft['id']}/approve", json={}
                            )
                            st.success(
                                f"פורסמה גרסה {result['version_number']}. "
                                f"{result['active_plants']} צמחים פעילים במין הזה.",
                                icon=":material/check_circle:",
                            )
                            st.rerun()
                        except ApiError as exc:
                            show_error(exc)

                    if st.button(
                        "מחקר מחדש",
                        key=f"retry_{draft['id']}",
                        icon=":material/refresh:",
                        # A17: the path out of a rejected or failed draft, and so
                        # the path out of KNOWLEDGE_PENDING for the plants waiting.
                        disabled=draft["status"] in {"RESEARCHING", "APPROVED"},
                    ):
                        try:
                            post(
                                f"/v1/admin/knowledge-drafts/{draft['id']}/retry",
                                json={
                                    "reason": st.session_state.get(f"note_{draft['id']}") or None
                                },
                            )
                            st.success("המחקר יצא לדרך.", icon=":material/hourglass_top:")
                            st.rerun()
                        except ApiError as exc:
                            show_error(exc)

                note = st.text_input(
                    "סיבת דחייה (חובה לדחייה, ומועברת לסוכן במחקר חוזר)",
                    key=f"note_{draft['id']}",
                    placeholder="למשל: ההמלצה על ההשקיה אינה מתאימה לאקלים מקומי",
                )
                if st.button(
                    "דחייה",
                    key=f"reject_{draft['id']}",
                    disabled=not reviewable or not note.strip(),
                    icon=":material/block:",
                ):
                    try:
                        post(
                            f"/v1/admin/knowledge-drafts/{draft['id']}/reject",
                            json={"admin_note": note.strip()},
                        )
                        # A17 made visible: rejection is not the end of the road,
                        # and the plants waiting on this species are still waiting.
                        st.info(
                            "הטיוטה נדחתה. הצמחים ממשיכים להמתין וניתן לחקור מחדש.",
                            icon=":material/info:",
                        )
                        st.rerun()
                    except ApiError as exc:
                        show_error(exc)


# --- published knowledge ------------------------------------------------------

with published_tab:
    st.caption("היסטוריית הגרסאות של מין. גרסאות שפורסמו אינן ניתנות לעריכה או למחיקה.")
    species_id = st.text_input("מזהה מין", key="admin_species_id", placeholder="UUID של המין")

    if species_id.strip():
        versions = guarded(lambda: get(f"/v1/admin/knowledge-versions/{species_id.strip()}"))
        if versions is not None:
            if not versions:
                st.caption("אין עדיין גרסאות מפורסמות למין הזה.")
            for version in versions:
                with st.container(border=True):
                    st.write(f"**גרסה {version['version_number']}** · {version['language']}")
                    st.caption(f"פורסם: {version['published_at'][:16]}")
                    if version["is_current"]:
                        st.badge("הגרסה הנוכחית", color="green")


# --- approved sources ---------------------------------------------------------

with sources_tab:
    sources = guarded(lambda: get("/v1/admin/approved-sources"))

    with st.expander("הוספת מקור מאושר", icon=":material/add:"):
        name = st.text_input("שם", key="src_name")
        domain = st.text_input(
            "דומיין",
            key="src_domain",
            placeholder="rhs.org.uk",
            help="אפשר להדביק כתובת מלאה; נשמר רק הדומיין.",
        )
        reliability = st.slider("רמת אמינות", 1, 5, 3, key="src_reliability")
        if st.button("הוספה", type="primary", disabled=not (name.strip() and domain.strip())):
            try:
                post(
                    "/v1/admin/approved-sources",
                    json={
                        "name": name.strip(),
                        "domain": domain.strip(),
                        "reliability_level": reliability,
                    },
                )
                st.success("המקור נוסף.", icon=":material/check_circle:")
                st.rerun()
            except ApiError as exc:
                show_error(exc)

    if sources is not None:
        if not sources:
            st.caption("אין עדיין מקורות מאושרים.")
        for source in sources:
            with st.container(border=True):
                st.write(f"**{source['name']}** · `{source['domain']}`")
                if source["is_enabled"]:
                    st.badge("פעיל", color="green")
                else:
                    st.badge("מושבת", color="gray")
                if source.get("reliability_level"):
                    st.caption(f"אמינות: {source['reliability_level']}/5")

                if source["is_enabled"]:
                    if st.button("השבתה", key=f"disable_{source['id']}", icon=":material/block:"):
                        try:
                            post(f"/v1/admin/approved-sources/{source['id']}/disable")
                            # Deliberately does not touch existing provenance rows:
                            # they record what was true when a version published.
                            st.info(
                                "המקור הושבת. גרסאות שכבר פורסמו אינן משתנות.",
                                icon=":material/history:",
                            )
                            st.rerun()
                        except ApiError as exc:
                            show_error(exc)
                elif st.button("הפעלה מחדש", key=f"enable_{source['id']}"):
                    try:
                        patch(
                            f"/v1/admin/approved-sources/{source['id']}",
                            json={"is_enabled": True},
                        )
                        st.rerun()
                    except ApiError as exc:
                        show_error(exc)


with reports_tab:
    st.caption("דיווחי משתמשים על שגיאות במידע.")
with monitoring_tab:
    st.caption("הרצות של סוכני ה-AI: מודל, גרסת פרומפט, משך ועלות.")
