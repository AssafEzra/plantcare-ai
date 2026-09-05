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
