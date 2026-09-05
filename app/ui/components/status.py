"""Health status presentation.

UI_DESIGN_TOKENS is explicit: status is **always text plus an icon**, and colour
alone must never carry the meaning. That rule is encoded here rather than left to
each caller, so a page cannot accidentally render a bare coloured dot.

Hebrew labels come from the approved wireframes verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import streamlit as st

from app.common.enums import HealthStatus, HealthTrend


@dataclass(frozen=True)
class StatusStyle:
    label: str
    icon: str
    # A Streamlit semantic colour name; the actual hex lives in config.toml,
    # so the approved palette is applied without any per-call styling.
    colour: Literal["red", "orange", "green", "gray"]


_STATUS: dict[HealthStatus, StatusStyle] = {
    HealthStatus.HEALTHY: StatusStyle("בריא", ":material/check_circle:", "green"),
    HealthStatus.NEEDS_ATTENTION: StatusStyle("דורש תשומת לב", ":material/warning:", "orange"),
    HealthStatus.CRITICAL: StatusStyle("מצב קריטי", ":material/error:", "red"),
    HealthStatus.UNKNOWN: StatusStyle("לא ידוע", ":material/help:", "gray"),
}

_TREND: dict[HealthTrend, StatusStyle] = {
    HealthTrend.IMPROVING: StatusStyle("משתפר", ":material/trending_up:", "green"),
    HealthTrend.WORSENING: StatusStyle("מחמיר", ":material/trending_down:", "red"),
    HealthTrend.STABLE: StatusStyle("יציב", ":material/trending_flat:", "gray"),
    HealthTrend.UNABLE_TO_DETERMINE: StatusStyle("אין מספיק נתונים", ":material/help:", "gray"),
}


def status_style(status: HealthStatus | str) -> StatusStyle:
    try:
        return _STATUS[HealthStatus(status)]
    except ValueError:
        return _STATUS[HealthStatus.UNKNOWN]


def trend_style(trend: HealthTrend | str) -> StatusStyle:
    try:
        return _TREND[HealthTrend(trend)]
    except ValueError:
        return _TREND[HealthTrend.UNABLE_TO_DETERMINE]


def status_badge(status: HealthStatus | str) -> None:
    """Render a health badge: icon and text together, never colour alone."""
    style = status_style(status)
    st.badge(style.label, icon=style.icon, color=style.colour)


def trend_badge(trend: HealthTrend | str) -> None:
    style = trend_style(trend)
    st.badge(style.label, icon=style.icon, color=style.colour)
