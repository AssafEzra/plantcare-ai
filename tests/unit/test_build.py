"""What this process says it is running, and why it must not change its mind.

The whole value of the version block is that it can be trusted when nothing else
can, so the interesting cases here are the ones where the answer is unavailable:
git is not installed in the container image, `spa_dist_dir` is unset outside it, and
a sha built on another machine is not an object in this clone. None of those may
raise, and none may be guessed at.

The load-bearing test is `test_the_running_commit_is_frozen_at_the_first_answer`.
A process that re-reads HEAD reports the tree's current commit, so it always looks
up to date - including when it is an hour behind, which is the exact false "ok" this
module exists to prevent.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest


@pytest.fixture
def build(env):
    """The module, with its cached commit cleared so each test starts fresh."""
    from app.infrastructure import build as module

    module.commit.cache_clear()
    yield module
    module.commit.cache_clear()


def fake_git(monkeypatch, module, *, stdout: str = "", returncode: int = 0, raises=None):
    """Replace the git subprocess with a fixed answer, and count the calls."""
    calls: list[list[str]] = []

    def run(argv, **_kwargs):
        calls.append(list(argv))
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)
    return calls


# --- what this process is running ----------------------------------------------


def test_the_declared_commit_wins(env, build):
    """In the container there is no git to ask, which is why the Dockerfile bakes
    the value in. Asking anyway shipped `unknown` to production for a week."""
    env.setenv("APP_COMMIT", "abc1234")
    fake_git(env, build, stdout="9999999")

    assert build.commit() == "abc1234"


def test_git_answers_when_nothing_is_declared(env, build):
    """A development machine, where the checkout is the source of truth."""
    fake_git(env, build, stdout="93a7853\n")

    assert build.commit() == "93a7853"


def test_a_dirty_commit_is_reported_verbatim(env, build):
    """`scripts/deploy.py` marks a build made from an uncommitted tree, because
    `builds submit` uploads the tree rather than the commit - so a clean sha would
    be a false claim about what is running. The suffix must survive to the reader."""
    env.setenv("APP_COMMIT", "abc1234-dirty")

    assert build.commit() == "abc1234-dirty"


def test_no_git_and_nothing_declared_is_unknown(env, build):
    """The deployed image: python:slim with no git installed. `subprocess.run`
    raises `FileNotFoundError`, an OSError - not the CalledProcessError a reader
    would expect - and catching only the latter would 500 the endpoint."""
    fake_git(env, build, raises=FileNotFoundError("git"))

    assert build.commit() == "unknown"


def test_a_failing_git_is_unknown_not_an_error(env, build):
    fake_git(env, build, returncode=128, stdout="")

    assert build.commit() == "unknown"


def test_a_hanging_git_is_unknown(env, build):
    """Blocked on an index lock held by an editor. A diagnostic may not hang the
    request it is answering."""
    fake_git(env, build, raises=subprocess.TimeoutExpired(["git"], 2.0))

    assert build.commit() == "unknown"


def test_the_running_commit_is_frozen_at_the_first_answer(env, build):
    """The point of the whole module.

    Two calls, one subprocess: the answer describes the code this process started
    with. Were it re-read, a server left running across a commit would report the
    new HEAD and claim to be current while serving the old code - and the "stale
    API" row of the admin block could never be reached.
    """
    calls = fake_git(env, build, stdout="93a7853")

    assert build.commit() == "93a7853"
    assert build.commit() == "93a7853"
    assert len(calls) == 1


def test_the_tree_head_is_read_fresh_every_time(env, build):
    """The counterpart. This one *must* follow the tree, because the comparison
    between it and the frozen commit is what detects the stale process."""
    calls = fake_git(env, build, stdout="cd0f30d")

    assert build.head_commit() == "cd0f30d"
    assert build.head_commit() == "cd0f30d"
    assert len(calls) == 2


def test_the_tree_head_is_none_where_there_is_no_git(env, build):
    fake_git(env, build, raises=FileNotFoundError("git"))

    assert build.head_commit() is None


# --- am I production? -----------------------------------------------------------


def test_cloud_run_is_recognised_by_the_platform_not_by_app_env(env, build):
    """`APP_ENV` is a developer's string and can say anything. `K_REVISION` is
    injected by the platform, and a process that believes it is production will not
    go looking for one."""
    assert build.is_cloud_run() is False

    env.setenv("K_REVISION", "plantcare-ai-00010-z44")
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    assert build.is_cloud_run() is True
    assert build.revision() == "plantcare-ai-00010-z44"


# --- the bundle this process serves ---------------------------------------------


def test_no_bundle_is_served_locally(env, build):
    """`SPA_DIST_DIR` is unset outside the container: Vite serves the interface in
    development, so there is no built file to date."""
    assert build.bundle_built_at() is None


def test_a_missing_index_is_none_rather_than_an_error(env, build, tmp_path):
    env.setenv("SPA_DIST_DIR", str(tmp_path))
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    assert build.bundle_built_at() is None


def test_the_bundle_date_is_the_index_mtime(env, build, tmp_path):
    """Which `COPY --from=web` preserves, so it is the moment `vite build` wrote the
    file - the same instant the bundle baked its own build time. Comparable times
    are the only way to tell an old bundle from a rolled-back deployment."""
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    env.setenv("SPA_DIST_DIR", str(tmp_path))
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    built = build.bundle_built_at()

    assert built is not None
    assert built.tzinfo is not None
    assert abs((datetime.now(UTC) - built).total_seconds()) < 60


# --- how far apart two commits are ----------------------------------------------


def test_offsets_read_both_directions(env, build):
    """`--left-right --count prod...HEAD` prints "only in prod<TAB>only in HEAD".
    Production being ahead is not hypothetical - deploying and then resetting
    produces it - and two dots would silently report zero for it."""
    fake_git(env, build, stdout="0\t3\n")

    assert build.offsets("cd0f30d", "93a7853") == (3, 0)


def test_offsets_report_a_production_that_is_ahead(env, build):
    fake_git(env, build, stdout="2\t0\n")

    assert build.offsets("cd0f30d", "93a7853") == (0, 2)


def test_the_dirty_suffix_is_stripped_before_asking_git(env, build):
    calls = fake_git(env, build, stdout="0\t1")

    build.offsets("abc1234-dirty", "93a7853")

    assert "abc1234...93a7853" in calls[0]


def test_an_unknown_commit_is_not_compared(env, build):
    """Every comparison against an unknown value is vacuous, so it is not made."""
    calls = fake_git(env, build, stdout="0\t1")

    assert build.offsets("unknown", "93a7853") == (None, None)
    assert build.offsets("93a7853", "unknown") == (None, None)
    assert calls == []


def test_a_commit_this_clone_never_fetched_gives_no_number(env, build):
    """Deployed from another machine, or the branch was force-pushed. git exits
    non-zero on a bad revision, and the row then says only that the two differ."""
    fake_git(env, build, returncode=128)

    assert build.offsets("cd0f30d", "93a7853") == (None, None)


def test_unparseable_counts_give_no_number(env, build):
    fake_git(env, build, stdout="not a pair of numbers")

    assert build.offsets("cd0f30d", "93a7853") == (None, None)
