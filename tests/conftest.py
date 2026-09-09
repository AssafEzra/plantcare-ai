from __future__ import annotations

import pytest

REQUIRED_ENV = {
    "SUPABASE_URL": "https://example-dev.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key-for-tests",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-for-tests",
    "AI_API_KEY": "ai-key-for-tests",
    "IDENTIFICATION_MODEL": "test-model",
    "KNOWLEDGE_MODEL": "test-model",
    "CARE_MODEL": "test-model",
    "HEALTH_MODEL": "test-model",
    "INTERNAL_TICK_SECRET": "tick-secret-for-tests",
    # Off in every test process. The API's in-process sweep would otherwise run
    # against DEV on its own schedule while a test asserted on the same rows,
    # which is a failure nobody can reproduce.
    "INTERNAL_TICK_INTERVAL_SECONDS": "0",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """Populate the required configuration and isolate tests from a local .env.

    Disabling `env_file` is essential, not tidiness: pydantic-settings falls back
    to `.env` for anything absent from the environment, so a developer who has a
    real `.env` would see `monkeypatch.delenv` silently do nothing and the
    "missing variable" tests pass for the wrong reason. These tests must describe
    the code's behaviour, not the machine's filesystem.
    """
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import settings as settings_module

    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)

    settings_module.get_settings.cache_clear()
    yield monkeypatch
    settings_module.get_settings.cache_clear()


#: Markers that mean "this test is *supposed* to call a real provider". Everything
#: else is guarded below.
LIVE_MARKERS = ("live", "browser")


@pytest.fixture(autouse=True)
def no_unintended_live_calls(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Refuse to let an unmarked test reach a real AI vendor.

    Every agent is reachable through a dependency a test can override, and the
    suites do that - except that `tick._reconcile_plans` used to build its own
    `CareAgent(AIGateway())`, which resolves its provider from configuration and so
    had no seam at all. Running the scheduler suite and the e2e journeys made
    seventeen live CARE calls on `claude-opus-5`, cost $1.11, and exhausted the
    Google quota that the next real identification needed.

    The injection point is fixed now. This is the guard that keeps it fixed: an
    override that gets forgotten, or a new path that constructs its own gateway,
    fails loudly here instead of billing quietly.

    Patched at `gateway.provider_for` rather than at the provider classes, because
    that is exactly the "no double was injected" path. A provider unit test that
    constructs `GoogleProvider()` directly makes no network call and is untouched.
    """
    if any(request.node.get_closest_marker(name) for name in LIVE_MARKERS):
        return

    from app.infrastructure.ai import gateway

    def refuse(name: str):
        raise AssertionError(
            f"this test reached the real {name!r} provider. Inject a scripted "
            "provider - AIGateway(provider=...) - or override the agent dependency "
            "with app.dependency_overrides. Mark the test 'live' if a real, "
            "billable call is genuinely the point."
        )

    monkeypatch.setattr(gateway, "provider_for", refuse)


def pytest_terminal_summary(terminalreporter) -> None:
    """Say what teardown could not remove.

    The accounts these suites create cannot be deleted - `system_events` is
    append-only and refuses the cascade - and the old teardown hid that inside
    `contextlib.suppress(Exception)`. Twenty-five PRs later the DEV project held
    1,375 orphaned accounts, a quarter of them administrators, and the Auth rate
    limit they contributed to was being blamed on the tests that hit it last.

    A silent failure that accumulates is worse than a loud one that does not, so
    the count goes in the summary with the script that can act on it.
    """
    try:
        from tests.integration.conftest import undeleted_accounts
    except ImportError:  # pragma: no cover - unit-only runs
        return

    left = undeleted_accounts()
    if not left:
        return

    terminalreporter.write_sep("-", "test accounts left behind")
    terminalreporter.write_line(
        f"{len(left)} account(s) could not be deleted: system_events is append-only, "
        "so the cascade from auth.users is refused (FINAL 1.5)."
    )
    terminalreporter.write_line(
        "Remove them with: uv run python scripts/purge_dev_test_accounts.py --delete"
    )
