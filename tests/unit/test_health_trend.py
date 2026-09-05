"""Health trend (A11, FINAL §16).

    "Do not claim a trend without sufficient evidence."

A trend is a comparison between stored assessments, which makes it arithmetic —
and FINAL §1.4 says use deterministic software where AI adds no value. A model
shown one photograph would answer from that photograph, which is the one thing a
trend is not about.
"""

from __future__ import annotations

import pytest

from app.common.enums import HealthStatus, HealthTrend
from app.domain.rules.health_trend import MIN_ASSESSMENTS, has_enough_history, trend_from

HEALTHY = HealthStatus.HEALTHY
ATTENTION = HealthStatus.NEEDS_ATTENTION
CRITICAL = HealthStatus.CRITICAL
UNKNOWN = HealthStatus.UNKNOWN


def test_one_assessment_cannot_be_a_trend():
    """Reporting "stable" from a single check would be a claim about history from
    a plant we have seen once."""
    assert trend_from([HEALTHY]) is HealthTrend.UNABLE_TO_DETERMINE


def test_no_assessments_cannot_be_a_trend():
    assert trend_from([]) is HealthTrend.UNABLE_TO_DETERMINE


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([HEALTHY, ATTENTION], HealthTrend.IMPROVING),
        ([HEALTHY, CRITICAL], HealthTrend.IMPROVING),
        ([ATTENTION, CRITICAL], HealthTrend.IMPROVING),
        ([ATTENTION, HEALTHY], HealthTrend.WORSENING),
        ([CRITICAL, HEALTHY], HealthTrend.WORSENING),
        ([CRITICAL, ATTENTION], HealthTrend.WORSENING),
        ([HEALTHY, HEALTHY], HealthTrend.STABLE),
        ([CRITICAL, CRITICAL], HealthTrend.STABLE),
    ],
)
def test_the_direction_is_the_newest_against_the_one_before(statuses, expected):
    """Newest first. The comparison is with the previous assessment, not an
    average: a plant that was critical, recovered, and has declined again is
    worsening, and averaging would call that an improvement."""
    assert trend_from(statuses) is expected


def test_only_the_two_most_recent_matter():
    """A long history must not dilute a recent change."""
    assert trend_from([CRITICAL, HEALTHY, HEALTHY, HEALTHY, HEALTHY]) is HealthTrend.WORSENING


def test_an_unknown_assessment_is_skipped_not_counted_as_a_low_point():
    """An assessment we could not read is not evidence the plant got worse.

    Counting UNKNOWN as a decline would report worsening every time someone
    submitted a blurred photograph.
    """
    assert trend_from([HEALTHY, UNKNOWN, HEALTHY]) is HealthTrend.STABLE
    assert trend_from([ATTENTION, UNKNOWN, HEALTHY]) is HealthTrend.WORSENING


def test_a_history_of_only_unknowns_yields_no_trend():
    assert trend_from([UNKNOWN, UNKNOWN, UNKNOWN]) is HealthTrend.UNABLE_TO_DETERMINE


def test_a_newest_unknown_does_not_hide_the_trend_beneath_it():
    """The two readable assessments still compare."""
    assert trend_from([UNKNOWN, HEALTHY, CRITICAL]) is HealthTrend.IMPROVING


def test_plain_strings_are_accepted():
    """The caller reads them from the database, where they are text."""
    assert trend_from(["HEALTHY", "NEEDS_ATTENTION"]) is HealthTrend.IMPROVING


def test_an_unrecognised_status_is_ignored_rather_than_raising():
    """A future enum value must not break the trend for every existing user."""
    assert trend_from(["SOMETHING_NEW", "HEALTHY", "CRITICAL"]) is HealthTrend.IMPROVING


def test_enough_history_matches_the_minimum():
    assert not has_enough_history([HEALTHY])
    assert has_enough_history([HEALTHY, HEALTHY])
    assert not has_enough_history([HEALTHY, UNKNOWN])
    assert MIN_ASSESSMENTS == 2
