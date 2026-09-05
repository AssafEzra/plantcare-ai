"""Rate limiting (A14).

The clock is injected rather than slept on. A limiter tested with `time.sleep`
is slow and only ever samples one point on the curve; an injected clock lets the
window boundary itself be asserted.
"""

from __future__ import annotations

import pytest

from app.api.rate_limit import InMemorySlidingWindow, RateLimiter
from app.common.errors import RateLimitedError


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def limiter(clock: FakeClock) -> RateLimiter:
    return RateLimiter(clock=clock)


ONE_PER_MINUTE = [(1, 60)]
THREE_PER_MINUTE = [(3, 60)]
LAYERED = [(3, 60), (10, 3600)]


def test_requests_within_the_limit_are_allowed(limiter: RateLimiter):
    for _ in range(3):
        limiter.check("user-a", THREE_PER_MINUTE)


def test_the_request_over_the_limit_is_refused(limiter: RateLimiter):
    for _ in range(3):
        limiter.check("user-a", THREE_PER_MINUTE)

    with pytest.raises(RateLimitedError):
        limiter.check("user-a", THREE_PER_MINUTE)


def test_limits_are_per_key(limiter: RateLimiter):
    """Keyed on the verified user id: one user's spend must not throttle another."""
    for _ in range(3):
        limiter.check("user-a", THREE_PER_MINUTE)

    limiter.check("user-b", THREE_PER_MINUTE)


def test_the_window_slides(limiter: RateLimiter, clock: FakeClock):
    for _ in range(3):
        limiter.check("user-a", THREE_PER_MINUTE)
    with pytest.raises(RateLimitedError):
        limiter.check("user-a", THREE_PER_MINUTE)

    clock.advance(61)

    limiter.check("user-a", THREE_PER_MINUTE)


def test_the_window_is_sliding_not_fixed(limiter: RateLimiter, clock: FakeClock):
    """A fixed window would let a caller spend the whole allowance twice across a
    boundary. Spending one per 30s must stay allowed indefinitely under 3/minute."""
    for _ in range(10):
        limiter.check("user-a", THREE_PER_MINUTE)
        clock.advance(30)


def test_partial_expiry_frees_exactly_one_slot(limiter: RateLimiter, clock: FakeClock):
    limiter.check("user-a", THREE_PER_MINUTE)
    clock.advance(30)
    limiter.check("user-a", THREE_PER_MINUTE)
    limiter.check("user-a", THREE_PER_MINUTE)

    # 31s later the first request has aged out, but the other two have not.
    clock.advance(31)
    limiter.check("user-a", THREE_PER_MINUTE)
    with pytest.raises(RateLimitedError):
        limiter.check("user-a", THREE_PER_MINUTE)


def test_a_refused_request_reports_retry_after(limiter: RateLimiter, clock: FakeClock):
    limiter.check("user-a", ONE_PER_MINUTE)
    clock.advance(20)

    with pytest.raises(RateLimitedError) as exc:
        limiter.check("user-a", ONE_PER_MINUTE)

    # 60s window, 20s elapsed, so roughly 40s remain.
    assert 35 <= exc.value.details["retry_after_seconds"] <= 40


def test_a_refused_request_does_not_consume_allowance(limiter: RateLimiter, clock: FakeClock):
    """Otherwise a client retrying in a tight loop would hold its own window open
    forever, and never recover."""
    limiter.check("user-a", ONE_PER_MINUTE)
    for _ in range(5):
        with pytest.raises(RateLimitedError):
            limiter.check("user-a", ONE_PER_MINUTE)

    clock.advance(61)
    limiter.check("user-a", ONE_PER_MINUTE)


def test_the_stricter_rule_wins(limiter: RateLimiter, clock: FakeClock):
    """3/minute and 10/hour together: the minute rule bites first."""
    for _ in range(3):
        limiter.check("user-a", LAYERED)

    with pytest.raises(RateLimitedError):
        limiter.check("user-a", LAYERED)


def test_the_hourly_rule_still_applies_after_minutes_pass(limiter: RateLimiter, clock: FakeClock):
    """The point of layering: spacing requests out defeats the minute limit but
    must not defeat the hourly one."""
    for _ in range(10):
        limiter.check("user-a", LAYERED)
        clock.advance(70)

    with pytest.raises(RateLimitedError):
        limiter.check("user-a", LAYERED)


def test_a_rejected_request_does_not_spend_the_looser_allowance(
    limiter: RateLimiter, clock: FakeClock
):
    """Every rule is checked before anything is recorded, so a request refused by
    the minute limit must not quietly consume an hourly slot."""
    for _ in range(3):
        limiter.check("user-a", LAYERED)
    for _ in range(20):
        with pytest.raises(RateLimitedError):
            limiter.check("user-a", LAYERED)

    clock.advance(61)
    # Three were spent; seven of the hourly ten should remain.
    for _ in range(3):
        limiter.check("user-a", LAYERED)


def test_a_zero_limit_disables_the_operation(limiter: RateLimiter):
    with pytest.raises(RateLimitedError, match="disabled"):
        limiter.check("user-a", [(0, 60)])


def test_idle_keys_are_evicted(clock: FakeClock):
    """A long-running process must not keep one deque per user who ever called."""
    storage = InMemorySlidingWindow()
    limiter = RateLimiter(storage=storage, clock=clock)

    for i in range(50):
        limiter.check(f"user-{i}", THREE_PER_MINUTE)

    clock.advance(7200)
    limiter.check("user-fresh", THREE_PER_MINUTE)

    assert len(storage._events) < 50, "idle keys were not swept"


def test_reset_clears_state(limiter: RateLimiter):
    limiter.check("user-a", ONE_PER_MINUTE)
    limiter.reset()

    limiter.check("user-a", ONE_PER_MINUTE)
