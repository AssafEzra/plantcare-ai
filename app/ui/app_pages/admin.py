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

from datetime import datetime
from typing import Any, Literal

import streamlit as st

from app.ui.components.layout import (
    empty_state,
    flash,
    guarded,
    page_header,
    show_error,
    show_flash,
)
from app.ui.components.sources import render_sources
from app.ui.state.api_client import ApiError, cached_get, get, patch, post

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

# Below this, a section is surfaced to the reviewer rather than left to be found.
WEAK_SECTION = 0.5

page_header("ניהול", "אזור מנהלי מערכת")

# Every action below ends in st.rerun(), which discards anything written before
# it. A message shown and then immediately rerun away is a message nobody sees —
# and the publish result carries the fan-out count, which is the part an
# administrator most wants confirmed. So the outcome is parked here and rendered
# on the next run instead.


(
    overview_tab,
    drafts_tab,
    published_tab,
    sources_tab,
    reports_tab,
    monitoring_tab,
    deliveries_tab,
    audit_tab,
    accounts_tab,
) = st.tabs(
    [
        "סקירה",
        "טיוטות ידע",
        "ידע מפורסם",
        "מקורות מאושרים",
        "דיווחי משתמשים",
        "ניטור סוכנים",
        "התראות שנשלחו",
        "יומן פעולות",
        "חשבונות",
    ]
)


# --- overview -------------------------------------------------------------------

with overview_tab:
    show_flash()
    overview = guarded(lambda: cached_get("/v1/admin/overview"))

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
            total = f'סה"כ עלות מוערכת: ${overview.get("total_estimated_cost", 0):.4f}'
            # An execution with no cost is not a free execution. Saying so keeps
            # the total honest as a floor: an unpriced model and a call that failed
            # after the model had generated both land here, and both were reported
            # as $0.00 until PR AI_provider - which is why this figure disagreed
            # with the Anthropic invoice.
            missing = int(overview.get("executions_missing_cost", 0) or 0)
            if missing:
                total += f" · {missing} הרצות ללא עלות מתועדת"
            st.caption(total)
        else:
            st.caption("לא נרשמו הרצות בחלון הזמן הזה.")


def status_badge(status: str) -> None:
    label, colour = DRAFT_STATUS_LABELS.get(status, (status, "gray"))
    st.badge(label, color=colour)


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
    drafts = guarded(lambda: cached_get("/v1/admin/knowledge-drafts", params=params))

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

OPEN_VERSION = "admin_open_version"


def open_version(version_id: str) -> None:
    st.session_state[OPEN_VERSION] = version_id


def render_version(version_id: str) -> None:
    """The article itself, with everything an administrator reviews it for.

    The tab used to show a version number, a date and a badge — never the text.
    Its own endpoint has always returned the content and the sources; the screen
    read neither, so "published knowledge" could be confirmed to exist and never
    read.
    """
    detail = guarded(lambda: cached_get(f"/v1/admin/knowledge-versions/detail/{version_id}"))
    if not detail:
        return

    header = st.container(horizontal=True)
    with header:
        st.markdown(f"### גרסה {detail['version_number']} · {detail['language']}")
        if st.button("סגירה", key="admin_close_version", icon=":material/close:"):
            st.session_state.pop(OPEN_VERSION, None)
            st.rerun()

    st.caption(f"פורסם: {str(detail.get('published_at') or '')[:16]}")
    if detail.get("is_current"):
        st.badge("הגרסה הנוכחית", color="green")

    content = detail.get("content") or {}
    if not content:
        st.info("לגרסה הזו אין תוכן.", icon=":material/info:")
    for key, label in SECTION_LABELS.items():
        section = content.get(key)
        if not section:
            continue
        text = section.get("text") if isinstance(section, dict) else str(section)
        if not text:
            continue
        with st.expander(label, icon=":material/article:"):
            st.write(text)
            # Confidence is per section and is the reason a reviewer looks at one
            # section rather than another.
            if isinstance(section, dict) and section.get("confidence") is not None:
                st.caption(f"רמת ביטחון: {section['confidence']}")

    render_sources(detail.get("sources") or [])


def render_research_control(entry: dict[str, Any]) -> None:
    """Start a fresh research run for a species whose article is already published.

    Published knowledge had no route back into research: the retry control lives
    on a draft, and an approved species has no open draft to press it on. This is
    the screen where that judgement is formed - it shows the text, the version and
    how many plants are reading it - so it is where the control belongs.

    Folded into an expander rather than sitting beside "פתיחת הידע" because this
    is a browsing screen where every article listed is working. Opening the
    expander is the first half of the confirmation and typing a reason is the
    second, which is the shape the rejection control already uses. The reason is
    not a formality either: it reaches the agent, so a second attempt can address
    the objection instead of reproducing the article that prompted it.
    """
    open_status = entry.get("open_draft_status")

    with st.expander("מחקר חדש", icon=":material/refresh:"):
        if open_status:
            # The route refuses this with a 409. Saying so here means the
            # administrator does not have to meet it, and names where the draft is.
            label, _ = DRAFT_STATUS_LABELS.get(open_status, (open_status, "gray"))
            st.info(
                f"כבר קיימת טיוטה פתוחה למין הזה ({label}). אפשר לטפל בה בלשונית טיוטות ידע.",
                icon=":material/hourglass_top:",
            )
            return

        st.caption(
            "מחקר חדש פותח טיוטה לבדיקה. הידע המפורסם נשאר פעיל עד שהטיוטה תאושר, "
            "ואם היא תידחה לא ישתנה דבר. הרצה אחת אורכת כחמש דקות והיא היקרה ביותר "
            "במערכת (כ־0.3$ על Opus)."
        )
        reason = st.text_input(
            "סיבת המחקר (מועברת לסוכן)",
            key=f"admin_research_reason_{entry['id']}",
            placeholder="למשל: הפרק על השקיה שגוי",
        )
        if st.button(
            "התחלת מחקר",
            key=f"admin_research_{entry['id']}",
            icon=":material/science:",
            disabled=not reason.strip(),
        ):
            try:
                post(
                    f"/v1/admin/species/{entry['species_id']}/knowledge/research",
                    json={"reason": reason.strip(), "language": entry["language"]},
                )
                flash(
                    "המחקר יצא לדרך. הטיוטה תופיע בלשונית טיוטות ידע כשיסתיים.",
                    kind="info",
                    icon=":material/hourglass_top:",
                )
                st.rerun()
            except ApiError as exc:
                show_error(exc)


with published_tab:
    if st.session_state.get(OPEN_VERSION):
        render_version(st.session_state[OPEN_VERSION])
    else:
        st.caption("כל המינים שיש להם ידע מפורסם. גרסאות שפורסמו אינן ניתנות לעריכה או למחיקה.")
        search = st.text_input(
            "חיפוש מין",
            key="admin_knowledge_search",
            placeholder="שם מדעי או שם עברי",
        )

        catalogue = guarded(
            lambda: get(
                "/v1/admin/knowledge-versions",
                params={"q": search.strip()} if search.strip() else None,
            )
        )
        if catalogue is not None:
            if not catalogue:
                st.caption("לא נמצאו מינים עם ידע מפורסם.")
            for entry in catalogue:
                with st.container(border=True):
                    title = st.container(horizontal=True)
                    with title:
                        st.markdown(
                            f"**{entry.get('common_name') or entry['scientific_name']}**"
                            f" · :gray[_{entry['scientific_name']}_]"
                        )
                        if st.button(
                            "פתיחת הידע",
                            key=f"admin_open_{entry['id']}",
                            icon=":material/menu_book:",
                        ):
                            open_version(entry["id"])
                            st.rerun()
                    st.caption(
                        f"גרסה {entry['version_number']} · {entry['language']} · "
                        f"פורסם {str(entry.get('published_at') or '')[:10]} · "
                        f"{entry.get('plant_count', 0)} צמחים"
                    )
                    render_research_control(entry)

            with st.expander("היסטוריית גרסאות לפי מזהה מין", icon=":material/history:"):
                species_id = st.text_input(
                    "מזהה מין", key="admin_species_id", placeholder="UUID של המין"
                )
                if species_id.strip():
                    versions = guarded(
                        lambda: cached_get(f"/v1/admin/knowledge-versions/{species_id.strip()}")
                    )
                    for version in versions or []:
                        row = st.container(horizontal=True)
                        with row:
                            st.write(
                                f"**גרסה {version['version_number']}** · "
                                f"{str(version.get('published_at') or '')[:10]}"
                                + (" · נוכחית" if version["is_current"] else "")
                            )
                            if st.button("פתיחה", key=f"admin_hist_{version['id']}"):
                                open_version(version["id"])
                                st.rerun()


# --- approved sources ---------------------------------------------------------

with sources_tab:
    show_flash()
    sources = guarded(lambda: cached_get("/v1/admin/approved-sources"))

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

    reports = guarded(lambda: cached_get("/v1/admin/knowledge-reports", params={"status": "OPEN"}))
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


def _when(raw: Any) -> str:
    """When a run happened, as `07/09/2026 17:50`.

    Added because the monitoring cards showed cost, latency and tokens but no
    time at all, so a run could not be tied to an incident or to a line on an
    Anthropic invoice. `created_at` was already in the payload and simply never
    rendered - `started_at` and `completed_at` are not worth using, since the
    gateway never sets them.

    Same parse-and-`astimezone` idiom as `health_card.assessed_at`. Note it
    resolves to the *server's* timezone, so on a UTC host this reads three hours
    behind Israel time - true of every date in this app, and a deliberate
    limitation rather than an oversight here.
    """
    if not raw:
        return "—"
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return str(raw)[:16]
    return f"{moment:%d/%m/%Y %H:%M}"


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

    executions = guarded(lambda: cached_get("/v1/admin/agent-executions", params=execution_params))
    if executions is not None:
        if not executions:
            st.caption("אין הרצות להצגה.")
        for execution in executions:
            with st.container(border=True):
                if execution["status"] == "FAILED":
                    st.badge("נכשל", color="red")
                st.markdown(f"**{execution['agent_type']}** · {execution['model']}")
                # Tokens and cost can be null, and null is not zero: a call that
                # failed after the model generated was still billed, and a model
                # with no price in its provider's table cannot be costed at all.
                # Formatting either as 0 would restate the understatement this
                # release exists to remove, so say "לא תועד" instead.
                tokens = "לא תועד"
                if execution.get("input_tokens") is not None:
                    tokens = (
                        f"{execution['input_tokens']}+{execution.get('output_tokens') or 0} טוקנים"
                    )
                cost = execution.get("estimated_cost")
                st.caption(
                    f"{_when(execution.get('created_at'))} · "
                    f"פרומפט {execution['prompt_version']} · ניסיון {execution['attempt']} · "
                    f"{execution['latency_ms']}ms · {tokens} · "
                    + (f"${cost:.4f}" if cost is not None else "עלות לא תועדה")
                )
                if execution.get("error_code"):
                    st.caption(f"שגיאה: {execution['error_code']}")

    # The requests those executions belong to. An execution row says a model call
    # happened; a request says whether the *user's* operation finished. They can
    # disagree - a run whose provider error escaped the gateway leaves a FAILED
    # request and no execution at all, which is precisely how PR 30's regression
    # hid - and only this view makes that visible.
    st.divider()
    st.subheader("בקשות סוכן", anchor=False)
    st.caption("מה שהמשתמש ביקש, לעומת הקריאות למודל שלמעלה. פער ביניהן הוא סימן לתקלה.")

    request_params: dict[str, Any] = {"limit": 50}
    if st.toggle("רק כשלים", key="admin_only_failed_requests"):
        request_params["status"] = "FAILED"

    requests = guarded(lambda: cached_get("/v1/admin/agent-requests", params=request_params))
    if requests is not None:
        if not requests:
            st.caption("אין בקשות להצגה.")
        for agent_request in requests:
            with st.container(border=True):
                if agent_request["status"] == "FAILED":
                    st.badge("נכשל", color="red")
                st.markdown(f"**{agent_request['agent_type']}** · {agent_request['status']}")
                st.caption(
                    f"{str(agent_request['created_at'])[:16]}"
                    + (f" · שלב {agent_request['stage']}" if agent_request.get("stage") else "")
                    + (
                        f" · {agent_request['error_code']}"
                        if agent_request.get("error_code")
                        else ""
                    )
                )


# --- notification deliveries ------------------------------------------------------

with deliveries_tab:
    # `GET /v1/admin/notification-deliveries` shipped in PR 19 and had no screen
    # until PR 31, which made "did we actually email anyone?" a question only a
    # database query could answer - on a system whose email provider is currently
    # a null provider, so the honest answer is "no", and nobody could see it.
    st.caption(
        "כל שליחה נרשמת לפני הקריאה לספק, כך שהיומן מראה גם ניסיונות שנכשלו. "
        "כשלא מוגדר ספק דואר, המערכת אינה שולחת דבר וזה ייראה כאן."
    )

    failures_only = st.toggle("רק כשלים", key="admin_delivery_failures")
    delivery_params: dict[str, Any] = {"limit": 50}
    if failures_only:
        delivery_params["status"] = "FAILED"

    deliveries = guarded(
        lambda: cached_get("/v1/admin/notification-deliveries", params=delivery_params)
    )
    if deliveries is not None:
        if not deliveries:
            st.caption("לא נשלחו התראות.")
        for delivery in deliveries:
            with st.container(border=True):
                if delivery["status"] == "FAILED":
                    st.badge("נכשל", color="red")
                elif delivery["status"] == "SENT":
                    st.badge("נשלח", color="green")
                else:
                    st.badge(delivery["status"], color="gray")
                st.caption(
                    f"{delivery['dedupe_key']} · תוזמן {str(delivery['scheduled_at'])[:16]}"
                    + (
                        f" · נשלח {str(delivery['sent_at'])[:16]}"
                        if delivery.get("sent_at")
                        else ""
                    )
                )
                if delivery.get("error_message"):
                    st.caption(f"שגיאה: {delivery['error_message']}")


# --- audit log --------------------------------------------------------------------

with audit_tab:
    # Append-only at the table, unreadable in the product: `GET /v1/admin/audit-log`
    # had no screen either. An audit log nobody can open records everything and
    # proves nothing.
    st.caption(
        "כל פעולת ניהול מהותית נרשמת כאן. הטבלה מסרבת לעדכון ולמחיקה עבור כל תפקיד, "
        "כך שהרישום אינו ניתן לשינוי בדיעבד."
    )

    entries = guarded(lambda: cached_get("/v1/admin/audit-log", params={"limit": 50}))
    if entries is not None:
        if not entries:
            st.caption("אין רישומים.")
        for entry in entries:
            with st.container(border=True):
                st.markdown(f"**{entry['action']}**")
                target = " · ".join(
                    part
                    for part in (entry.get("target_table"), str(entry.get("target_id") or "")[:8])
                    if part
                )
                st.caption(f"{str(entry['created_at'])[:16]}" + (f" · {target}" if target else ""))
                if entry.get("payload"):
                    with st.expander("פרטים"):
                        st.json(entry["payload"])


# --- accounts ---------------------------------------------------------------------

with accounts_tab:
    show_flash()
    st.caption(
        "חשבונות אינם נמחקים פיזית. אנונימיזציה מוחקת פרטים מזהים, חוסמת גישה "
        "ומשמרת את ההיסטוריה (FINAL §21)."
    )

    search = st.text_input("חיפוש לפי אימייל", key="admin_account_search")
    accounts = guarded(
        lambda: cached_get(
            "/v1/admin/accounts", params={"q": search.strip()} if search.strip() else {}
        )
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
