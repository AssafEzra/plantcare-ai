"""Ask the deployed service what it is running.

The admin panel shows three versions side by side, and one of them belongs to a
server this process is not. A browser cannot ask for it either: there is no CORS
configuration anywhere in `app/` - the SPA and `/v1` share an origin by design - so
a page served from localhost cannot read a response from Cloud Run. This module is
the way round that. The local API asks, server to server, and passes the answer on.

Only a local API ever calls it. A Cloud Run instance *is* production and has
nothing to ask, which `app/infrastructure/build.py:is_cloud_run` decides and the
admin route enforces - otherwise the single instance would spend its one request
slot fetching itself.

Never raises and never blocks for long. Production scales to zero, so the first
request after an idle period pays a cold start, and an administrator opening the
panel is exactly when that happens. A version line that cannot be filled in is a
blank line; a version line that hangs the page is a worse bug than the one this
block exists to diagnose.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config.logging import get_logger

log = get_logger(__name__)

# Deliberately shorter than the cold start it may land on. The question is a
# diagnostic aside on a page full of real metrics: better to report "unavailable"
# in two and a half seconds and let the administrator press again than to hold the
# panel while a container boots.
_TIMEOUT = httpx.Timeout(2.5, connect=2.0)

# Long enough that opening the tab repeatedly, or two administrators looking at
# once, is one request; short enough that checking again after a deploy gives a
# fresh answer without a restart. Failures are cached for the same period, which is
# the point: an unreachable production must cost one timeout a minute, not one per
# page load.
_TTL_SECONDS = 60.0

_cache: tuple[float, UpstreamVersion | None] | None = None


@dataclass(frozen=True)
class UpstreamVersion:
    """What `GET /version` on the deployed service reported."""

    commit: str
    started_at: datetime | None = None
    bundle_built_at: datetime | None = None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _fetch(base_url: str) -> UpstreamVersion | None:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/version", timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        log.warning("upstream_version.unreachable", error_type=type(exc).__name__)
        return None

    if response.status_code != 200:
        log.warning("upstream_version.refused", status=response.status_code)
        return None

    try:
        body = response.json()
    except ValueError:
        # An HTML error page from a proxy in front of the service, which is not the
        # service answering at all.
        log.warning("upstream_version.unparseable")
        return None

    if not isinstance(body, dict):
        return None

    commit = body.get("commit")
    if not isinstance(commit, str) or not commit:
        # Reachable but not the endpoint we meant - an older revision deployed
        # before `/version` existed answers the SPA shell or a 404 envelope.
        log.warning("upstream_version.unexpected_body")
        return None

    return UpstreamVersion(
        commit=commit,
        started_at=_parse_time(body.get("started_at")),
        bundle_built_at=_parse_time(body.get("bundle_built_at")),
    )


def current(base_url: str) -> UpstreamVersion | None:
    """What production is running, or None if it could not be established."""
    global _cache

    now = time.monotonic()
    if _cache is not None and now < _cache[0]:
        return _cache[1]

    value = _fetch(base_url)
    _cache = (now + _TTL_SECONDS, value)
    return value


def forget() -> None:
    """Drop the cache. For tests, and for a caller that must not see a stale answer."""
    global _cache
    _cache = None
