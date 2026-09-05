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

# Every action below ends in st.rerun(), which discards anything written before
# it. A message shown and then immediately rerun away is a message nobody sees —
# and the publish result carries the fan-out count, which is the part an
# administrator most wants confirmed. So the outcome is parked here and rendered
# on the next run instead.
FLASH = "admin_flash"


def flash(message: str, *, kind: str = "success", icon: str = ":material/check_circle:") -> None:
    st.session_state[FLASH] = (kind, message, icon)


def show_flash() -> None:
    parked = st.session_state.pop(FLASH, None)
    if not parked:
        return
    kind, message, icon = parked
    {"success": st.success, "info": st.info, "warning": st.warning}[kind](message, icon=icon)


overview_tab, drafts_tab, published_tab, sources_tab, reports_tab, monitoring_tab, accounts_tab = (
    st.tabs(
        [
            "סקירה",
            "טיוטות ידע",
            "ידע מפורסם",
            "מקורות מאושרים",
            "דיווחי משתמשים",
            "ניטור סוכנים",
            "חשבונות",
        ]
    )
)


# --- overview -------------------------------------------------------------------

with overview_tab:
    show_flash()
    overview = guarded(lambda: get("/v1/admin/overview"))

    if overview is not None:
        # Ordered by what would make someone act: failures first, then things
        # waiting on a person, then volume.
        a, b, c, d = st.columns(4)
        a.metric("בקשות AI שנכשלו", overview.get("failed_agent_requests", 0))
        b.metric("תזכורות שנכשלו", overview.get("failed_notifications", 0))
        c.metric("טיוטות לבדיקה", overview.get("drafts_awaiting_review", 0))
        d.metric("דיווחים פתוחים", overview.get("open_knowledge_reports", 0))

        st.caption(f"נתוני {overview.get('window_days', 7)} הימים האחרונים")

        stats = overview.get("agent_stats") or []
        if stats:
            st.markdown("**שימוש בסוכנים**")
            for stat in stats:
                with st.container(border=True):
                    failed = stat.get("failed", 0)
                    line = f"**{stat['agent_type']}** · {stat['total']} הרצות"
                    if failed:
                        line += f" · {failed} נכשלו"
                    st.markdown(line)
                    st.caption(
                        f"עלות מוערכת ${stat['estimated_cost']:.4f} · "
                        f"משך ממוצע {stat['average_latency_ms']}ms"
                    )
            st.caption(f'סה"כ עלות מוערכת: ${overview.get("total_estimated_cost", 0):.4f}')
        else:
            st.caption("לא נרשמו הרצות בחלון הזמן הזה.")


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
    # Worst first, matching `KnowledgeContent.weakest_sections`. Section order
    # would put the shakiest claim wherever it happens to fall in the fourteen,
    # and this line exists to tell a reviewer where to start.
    weak = [
        name
        for name, _ in sorted(
            (
                (name, section.get("confidence", 1.0))
                for name, section in sections.items()
                if isinstance(section, dict)
            ),
            key=lambda pair: pair[1],
        )
        if sections[name].get("confidence", 1.0) < WEAK_SECTION
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
    show_flash()
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
                            flash(
                                f"פורסמה גרסה {result['version_number']}. "
                                f"{result['active_plants']} צמחים של המין הזה פעילים כעת."
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
                            flash(
                                "המחקר יצא לדרך. הטיוטה תחזור לכאן כשיסתיים.",
                                kind="info",
                                icon=":material/hourglass_top:",
                            )
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
                        flash(
                            "הטיוטה נדחתה. הצמחים ממשיכים להמתין וניתן לחקור מחדש.",
                            kind="info",
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
    show_flash()
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
                flash("המקור נוסף.")
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
                            flash(
                                "המקור הושבת. גרסאות שכבר פורסמו אינן משתנות.",
                                kind="info",
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


# --- user reports ----------------------------------------------------------------

with reports_tab:
    show_flash()
    st.caption(
        "דיווחי משתמשים על שגיאות במידע. אישור דיווח אינו מפעיל מחקר — לשם כך יש לחקור מחדש בלשונית הטיוטות."
    )

    reports = guarded(lambda: get("/v1/admin/knowledge-reports", params={"status": "OPEN"}))
    if reports is not None:
        if not reports:
            st.caption("אין דיווחים פתוחים.")
        for report in reports:
            with st.container(border=True):
                st.write(report["report_text"])
                st.caption(
                    f"מין: {(report.get('species_id') or '—')[:8]} · {report['created_at'][:16]}"
                )

                decision = st.container(horizontal=True)
                with decision:
                    for status, label in (
                        ("ACTIONED", "טופל"),
                        ("REVIEWING", "בבדיקה"),
                        ("DISMISSED", "נדחה"),
                    ):
                        if st.button(label, key=f"report_{status}_{report['id']}"):
                            try:
                                post(
                                    f"/v1/admin/knowledge-reports/{report['id']}/review",
                                    json={"status": status},
                                )
                                flash("הדיווח עודכן.")
                                st.rerun()
                            except ApiError as exc:
                                show_error(exc)


# --- agent monitoring -------------------------------------------------------------

with monitoring_tab:
    st.caption(
        "הרצות של סוכני ה-AI: מודל, גרסת פרומפט, משך ועלות. "
        "תוכן הפרומפטים והתשובות אינו נשמר ואינו ניתן לצפייה."
    )

    only_failures = st.toggle("רק כשלים", key="admin_only_failures")
    execution_params: dict[str, Any] = {"limit": 50}
    if only_failures:
        execution_params["status"] = "FAILED"

    executions = guarded(lambda: get("/v1/admin/agent-executions", params=execution_params))
    if executions is not None:
        if not executions:
            st.caption("אין הרצות להצגה.")
        for execution in executions:
            with st.container(border=True):
                if execution["status"] == "FAILED":
                    st.badge("נכשל", color="red")
                st.markdown(f"**{execution['agent_type']}** · {execution['model']}")
                st.caption(
                    f"פרומפט {execution['prompt_version']} · ניסיון {execution['attempt']} · "
                    f"{execution['latency_ms']}ms · "
                    f"{execution['input_tokens']}+{execution['output_tokens']} טוקנים · "
                    f"${execution['estimated_cost']:.4f}"
                )
                if execution.get("error_code"):
                    st.caption(f"שגיאה: {execution['error_code']}")


# --- accounts ---------------------------------------------------------------------

with accounts_tab:
    show_flash()
    st.caption(
        "חשבונות אינם נמחקים פיזית. אנונימיזציה מוחקת פרטים מזהים, חוסמת גישה "
        "ומשמרת את ההיסטוריה (FINAL §21)."
    )

    search = st.text_input("חיפוש לפי אימייל", key="admin_account_search")
    accounts = guarded(
        lambda: get("/v1/admin/accounts", params={"q": search.strip()} if search.strip() else {})
    )

    if accounts is not None:
        if not accounts:
            st.caption("לא נמצאו חשבונות.")
        for profile in accounts[:25]:
            with st.container(border=True):
                st.markdown(f"**{profile.get('email') or '(אנונימי)'}**")
                st.caption(f"{profile['role']} · נוצר {profile['created_at'][:10]}")

                if profile.get("anonymized_at"):
                    st.badge("אנונימי", color="gray")
                    continue
                if not profile.get("is_active"):
                    st.badge("מושבת", color="gray")

                reason = st.text_input(
                    "סיבה",
                    key=f"anon_reason_{profile['id']}",
                    placeholder="למשל: בקשת מחיקה מהמשתמש",
                )
                if st.button(
                    "אנונימיזציה",
                    key=f"anon_{profile['id']}",
                    # A26: the reason is the only record of why an account was
                    # closed, so the action is unavailable without one.
                    disabled=not reason.strip(),
                ):
                    try:
                        post(
                            f"/v1/admin/accounts/{profile['id']}/anonymize",
                            json={"reason": reason.strip()},
                        )
                        flash(
                            "החשבון עבר אנונימיזציה. ההיסטוריה נשמרה.",
                            kind="info",
                            icon=":material/info:",
                        )
                        st.rerun()
                    except ApiError as exc:
                        show_error(exc)
