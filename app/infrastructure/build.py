"""What this process is running, and what the tree around it says.

Three things go stale independently and look identical from the outside: the
deployed service, the local API process, and the bundle a browser cached. Twice
this cost real time - once `/livez` answered `{"status": "ok"}` from a process
started an hour earlier and the restart was reported as done, which sent us looking
for a feature that was in the code and missing from the running server.

The distinction this module exists for is between two different questions:

* `commit()` - what code *this process* is running. Resolved once, at startup, and
  never re-read. A process that re-read it would report the tree's current HEAD and
  so would always look up to date, including the moment it is an hour behind. That
  false "ok" is the entire failure being fixed here.
* `head_commit()` - what the *tree* says right now, read fresh every time.

Comparing the two is what distinguishes "the server needs restarting" from "the
browser needs refreshing": two different shas say only that they differ, never
which one is older.

Nothing here raises. git is absent from the container image, `spa_dist_dir` is
unset outside it, and a diagnostic that fails when the thing it diagnoses is broken
is worse than no diagnostic. Every answer is therefore optional, and an unknown
answer is reported as unknown rather than guessed.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from app.config.settings import get_settings

#: The repository root, from this file's location rather than the process's working
#: directory - uvicorn, pytest and the container each start somewhere different.
_ROOT = Path(__file__).resolve().parents[2]

#: Short, because every caller is answering an HTTP request. git normally replies in
#: milliseconds; this is the ceiling for the case where it is blocked on an index
#: lock held by an editor or another command.
_GIT_TIMEOUT_SECONDS = 2.0

#: What a commit is called when it cannot be established. Rendered as such, never
#: compared - every comparison against an unknown value is vacuous.
UNKNOWN = "unknown"

#: When this process started. Module import is close enough, and it is the quantity
#: an operator actually wants beside the commit: "running since 08:02" is what makes
#: a stale process obvious.
STARTED_AT = datetime.now(UTC)


def _git(*args: str) -> str | None:
    """Run git in the repository, or return None if that is not possible."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=_ROOT,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        # `FileNotFoundError` is the container: the runtime image is python:slim with
        # no git installed, and it is an OSError rather than the CalledProcessError a
        # reader expects. `TimeoutExpired` is the lock case above.
        return None

    if result.returncode != 0:
        # A bad revision is the common one - a sha built on another machine, or a
        # branch that was force-pushed - and it is not an error worth logging on
        # every request.
        return None

    return result.stdout.strip() or None


@lru_cache(maxsize=1)
def commit() -> str:
    """The commit this process is running, frozen for its lifetime.

    The declared value wins: in the container there is no git to ask, and the
    Dockerfile bakes the commit in precisely because asking failed silently and
    shipped `unknown` to production.
    """
    return get_settings().app_commit or _git("rev-parse", "--short", "HEAD") or UNKNOWN


def head_commit() -> str | None:
    """What the working tree's HEAD is *now*. Deliberately not cached."""
    return _git("rev-parse", "--short", "HEAD")


def bundle_built_at() -> datetime | None:
    """When the interface this process serves was built.

    The mtime of the `index.html` being served, which `COPY --from=web` preserves,
    so it is the moment `vite build` wrote the file - the same instant the bundle
    baked its own `__APP_BUILT_AT__`. That makes the two comparable, and comparable
    build times are the only way to tell a browser holding an old bundle from a
    deployment that was rolled back to an older revision. The process start time
    cannot do it: a rolled-back revision starts now and was built long ago.

    None where no bundle is served, which is every local API process.
    """
    dist = get_settings().spa_dist_dir
    if dist is None:
        return None

    try:
        return datetime.fromtimestamp((dist / "index.html").stat().st_mtime, UTC)
    except OSError:
        return None


def revision() -> str | None:
    """The Cloud Run revision name, when running there."""
    return get_settings().k_revision


def is_cloud_run() -> bool:
    """Is this process the deployed service?

    Asked of the platform rather than of `APP_ENV`, which a developer can set to
    anything. A process that believes it is production will not go looking for one.
    """
    return bool(get_settings().k_revision)


def _revisable(sha: str) -> str | None:
    """A sha git can be asked about, or None.

    The deployed commit may carry the `-dirty` suffix `scripts/deploy.py` adds when
    the tree it uploaded had uncommitted changes. The suffix is the honest part of
    the label and useless to git, so it is stripped for the comparison and kept for
    display.
    """
    base = sha.removesuffix("-dirty")
    return None if not base or base == UNKNOWN else base


def offsets(production: str, head: str) -> tuple[int | None, int | None]:
    """How far apart two commits are, as (behind, ahead) from production's side.

    `behind` counts commits the local tree has and production does not; `ahead`
    counts the reverse, which happens when something was deployed and then reset or
    force-pushed. Three dots rather than two on purpose: `a..b` reports zero for a
    production that is ahead, hiding the divergence that matters more.

    (None, None) whenever the question cannot be answered - an unknown sha, or a
    commit this clone has never fetched.
    """
    left = _revisable(production)
    right = _revisable(head)
    if left is None or right is None:
        return (None, None)

    counts = _git("rev-list", "--left-right", "--count", f"{left}...{right}")
    if counts is None:
        return (None, None)

    parts = counts.split()
    if len(parts) != 2:
        return (None, None)

    try:
        only_in_production, only_in_head = (int(part) for part in parts)
    except ValueError:
        return (None, None)

    return (only_in_head, only_in_production)
