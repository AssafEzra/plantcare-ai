"""Asking production what it is running, and never paying twice for the answer.

This is the one request the admin panel makes that leaves the machine, and it is a
diagnostic aside on a page full of real metrics. So every test here is about
degrading rather than failing: production scales to zero, so the call can land on a
cold start, and an older revision deployed before `/version` existed answers
something else entirely.

The caching tests matter as much as the parsing ones. Failures are cached
deliberately: an unreachable production must cost one timeout a minute, not one per
page load.
"""

from __future__ import annotations

import httpx
import pytest

BASE = "https://plantcare-ai.example.run.app"
VERSION_URL = f"{BASE}/version"


@pytest.fixture
def upstream():
    from app.infrastructure import upstream_version as module

    module.forget()
    yield module
    module.forget()


def test_a_good_answer_is_parsed(upstream, httpx_mock):
    httpx_mock.add_response(
        url=VERSION_URL,
        json={
            "commit": "cd0f30d",
            "started_at": "2026-10-07T08:02:00+00:00",
            "bundle_built_at": "2026-10-07T07:58:00+00:00",
        },
    )

    reported = upstream.current(BASE)

    assert reported is not None
    assert reported.commit == "cd0f30d"
    assert reported.started_at is not None
    assert reported.bundle_built_at is not None


def test_a_trailing_slash_does_not_double_up(upstream, httpx_mock):
    httpx_mock.add_response(url=VERSION_URL, json={"commit": "cd0f30d"})

    assert upstream.current(f"{BASE}/") is not None


def test_missing_timestamps_are_not_an_error(upstream, httpx_mock):
    """A local API answering has no bundle to date, and the commit alone is still
    the useful part of the answer."""
    httpx_mock.add_response(url=VERSION_URL, json={"commit": "cd0f30d"})

    reported = upstream.current(BASE)

    assert reported is not None
    assert reported.started_at is None
    assert reported.bundle_built_at is None


def test_an_unreachable_host_is_none(upstream, httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("no route"))

    assert upstream.current(BASE) is None


def test_a_timeout_is_none(upstream, httpx_mock):
    """The cold-start case, and the reason the timeout is shorter than one."""
    httpx_mock.add_exception(httpx.ReadTimeout("too slow"))

    assert upstream.current(BASE) is None


def test_an_error_status_is_none(upstream, httpx_mock):
    httpx_mock.add_response(url=VERSION_URL, status_code=503, text="unavailable")

    assert upstream.current(BASE) is None


def test_a_non_json_body_is_none(upstream, httpx_mock):
    """A proxy's own HTML error page, which is not the service answering at all."""
    httpx_mock.add_response(url=VERSION_URL, text="<html>502</html>")

    assert upstream.current(BASE) is None


def test_a_body_without_a_commit_is_none(upstream, httpx_mock):
    """Reachable, but not the endpoint meant: a revision deployed before
    `/version` existed serves the application shell or a 404 envelope."""
    httpx_mock.add_response(url=VERSION_URL, json={"status": "ok"})

    assert upstream.current(BASE) is None


def test_the_answer_is_cached(upstream, httpx_mock):
    httpx_mock.add_response(url=VERSION_URL, json={"commit": "cd0f30d"})

    assert upstream.current(BASE) is not None
    assert upstream.current(BASE) is not None

    assert len(httpx_mock.get_requests()) == 1


def test_a_failure_is_cached_too(upstream, httpx_mock):
    """The point of caching at all. Without this, an administrator with a dead
    `PRODUCTION_BASE_URL` pays the timeout on every page load."""
    httpx_mock.add_exception(httpx.ConnectError("no route"))

    assert upstream.current(BASE) is None
    assert upstream.current(BASE) is None

    assert len(httpx_mock.get_requests()) == 1


def test_the_cache_expires(upstream, httpx_mock, monkeypatch):
    """Checked with a moved clock rather than a sleep: a test that waits a real
    minute is a test nobody runs."""
    httpx_mock.add_response(url=VERSION_URL, json={"commit": "cd0f30d"})
    httpx_mock.add_response(url=VERSION_URL, json={"commit": "93a7853"})

    now = 1_000.0
    monkeypatch.setattr(upstream.time, "monotonic", lambda: now)

    first = upstream.current(BASE)
    assert first is not None and first.commit == "cd0f30d"

    now += upstream._TTL_SECONDS + 1

    second = upstream.current(BASE)
    assert second is not None and second.commit == "93a7853"
