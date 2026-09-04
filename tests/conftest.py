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
