"""Health trend (A11, FINAL §16).

    "Do not claim a trend without sufficient evidence."

The trend is a comparison between stored assessments, which makes it arithmetic
rather than judgement — and FINAL §1.4 says use deterministic software where AI
adds no value. A model asked "is this plant improving?" would answer from the
photograph in front of it, which is the one thing a trend is *not* about.

Pure: no clock, no database, no model.
"""

from __future__ import annotations

from app.common.enums import HealthStatus, HealthTrend

# Ordered worst to best, so a comparison is a subtraction. UNKNOWN is absent
# deliberately — it is not a point on this scale, it is the absence of one.
_SEVERITY: dict[HealthStatus, int] = {
    HealthStatus.CRITICAL: 0,
    HealthStatus.NEEDS_ATTENTION: 1,
    HealthStatus.HEALTHY: 2,
}

# Below this many usable assessments there is no trend to report. Two is the
# minimum that can express a direction at all, and reporting "stable" from a
# single check would be a claim about history from a plant we have seen once.
MIN_ASSESSMENTS = 2


def trend_from(statuses: list[HealthStatus | str]) -> HealthTrend:
    """The direction of travel, newest status first.

    Compares the newest usable assessment with the one before it. Not a longer
    window: a plant that was critical a month ago, recovered, and has now
    declined again is *worsening*, and averaging across the month would call that
    an improvement.

    `UNKNOWN` assessments are skipped rather than treated as a low point. An
    assessment we could not read is not evidence the plant got worse, and
    counting it as one would report a decline every time someone submitted a
    blurred photograph.
    """
    usable = [
        _SEVERITY[status] for status in (_coerce(value) for value in statuses) if status is not None
    ]

    if len(usable) < MIN_ASSESSMENTS:
        return HealthTrend.UNABLE_TO_DETERMINE

    newest, previous = usable[0], usable[1]
    if newest > previous:
        return HealthTrend.IMPROVING
    if newest < previous:
        return HealthTrend.WORSENING
    return HealthTrend.STABLE


def _coerce(value: HealthStatus | str) -> HealthStatus | None:
    """A status we can place on the scale, or None."""
    try:
        status = HealthStatus(value)
    except ValueError:
        return None
    return status if status in _SEVERITY else None


def has_enough_history(statuses: list[HealthStatus | str]) -> bool:
    """Whether a trend may be claimed at all (FINAL §16)."""
    return sum(1 for value in statuses if _coerce(value) is not None) >= MIN_ASSESSMENTS
