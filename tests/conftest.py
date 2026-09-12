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


#: Markers that mean "this test is *supposed* to call a real provider". They buy a
#: narrower permission than they used to - see `ALLOWED_LIVE_PROVIDER`.
LIVE_MARKERS = ("live", "browser")

#: The only vendor any test may reach, marked or not.
#:
#: A standing instruction: real model calls made in testing go through Google, and
#: specifically `gemini-3.5-flash-lite`, with no exceptions. Enforced here rather
#: than trusted, because the first version of this guard exempted `live` tests
#: entirely - and the one file whose whole purpose is calling a real API was
#: therefore free to call Anthropic, which it did.
#:
#: The model itself is not checked here. `provider_for` only sees the vendor, and a
#: vendor check is the part that can be made structural; the model is named once in
#: `tests/agents/test_live_provider.py`.
ALLOWED_LIVE_PROVIDER = "google"


@pytest.fixture(autouse=True)
def no_unintended_live_calls(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Refuse to let a test reach a real AI vendor it has no business reaching.

    Two rules, and the second was missing for a day.

    **An unmarked test may reach no vendor at all.** Every agent is reachable
    through a dependency a test can override, and the suites do that - except that
    `tick._reconcile_plans` used to build its own `CareAgent(AIGateway())`, which
    resolves its provider from configuration and so had no seam at all. Running the
    scheduler suite and the e2e journeys made seventeen live CARE calls on
    `claude-opus-5`, cost $1.11, and exhausted the Google quota that the next real
    identification needed. The injection point is fixed; this keeps it fixed.

    **A marked test may reach Google and nothing else.** The first version of this
    guard returned early for anything marked `live`, which made the marker a way out
    of the rule rather than a declaration of intent - and `test_live_provider.py`,
    the one file that exists to spend money on a real API, was still calling
    Anthropic. A rule with an exception carved out for the exact case it was written
    about is not a rule.

    Patched at `gateway.provider_for` rather than at the provider classes, because
    that is the "no double was injected" path and because the vendor name is right
    there to check. A provider constructed directly - `AnthropicProvider()` - does
    not pass through here, which is why the live test had to change as well. Both,
    not either.
    """
    from app.infrastructure.ai import gateway

    marked = any(request.node.get_closest_marker(name) for name in LIVE_MARKERS)

    # Captured before patching, so the one allowed path resolves a real provider
    # rather than recursing into the replacement.
    real_provider_for = gateway.provider_for

    def refuse(name: str):
        if marked and name.strip().lower() == ALLOWED_LIVE_PROVIDER:
            return real_provider_for(name)
        if marked:
            raise AssertionError(
                f"this live test reached {name!r}. Real model calls in testing go "
                f"through {ALLOWED_LIVE_PROVIDER!r} only - no exceptions - so a "
                "billable call to any other vendor is a mistake even in a test that "
                "means to make one."
            )
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
