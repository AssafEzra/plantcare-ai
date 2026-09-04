"""SETUP_AND_ENVIRONMENT §11: startup validates configuration and fails clearly."""

from __future__ import annotations

import pytest

from app.common.errors import ConfigurationError
from app.config.settings import Settings, get_settings


def test_settings_load_when_all_required_values_present(env):
    settings = get_settings()
    assert settings.app_env == "test"
    assert settings.supabase_url == "https://example-dev.supabase.co"
    assert settings.default_timezone == "Asia/Jerusalem"
    assert settings.default_content_language == "he"


def test_settings_are_cached(env):
    assert get_settings() is get_settings()


def test_missing_required_variable_names_the_variable(env):
    env.delenv("SUPABASE_URL", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError) as exc:
        get_settings()

    message = str(exc.value)
    assert "SUPABASE_URL" in message
    assert ".env.example" in message


def test_several_missing_variables_are_all_reported(env):
    for key in ("AI_API_KEY", "CARE_MODEL", "INTERNAL_TICK_SECRET"):
        env.delenv(key, raising=False)
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError) as exc:
        get_settings()

    message = str(exc.value)
    for key in ("AI_API_KEY", "CARE_MODEL", "INTERNAL_TICK_SECRET"):
        assert key in message


def test_email_is_optional_and_degrades(env):
    """SETUP §11: optional integrations are feature-configurable, not fatal."""
    assert get_settings().email_enabled is False


def test_email_enabled_when_both_resend_values_present(env):
    env.setenv("RESEND_API_KEY", "re_test")
    env.setenv("RESEND_FROM_EMAIL", "care@example.com")
    get_settings.cache_clear()

    assert get_settings().email_enabled is True


def test_partial_resend_config_does_not_enable_email(env):
    env.setenv("RESEND_API_KEY", "re_test")
    get_settings.cache_clear()

    assert get_settings().email_enabled is False


@pytest.mark.parametrize("value", [3, 5, -1])
def test_retry_ceiling_is_an_invariant_not_a_knob(env, value):
    """FINAL_SPECIFICATION §23 caps structured-output retries at 2."""
    env.setenv("AI_MAX_STRUCTURED_RETRIES", str(value))
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError):
        get_settings()


def test_supabase_url_must_be_absolute(env):
    env.setenv("SUPABASE_URL", "example-dev.supabase.co")
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError):
        get_settings()


def test_trailing_slash_is_normalised(env):
    env.setenv("SUPABASE_URL", "https://example-dev.supabase.co/")
    get_settings.cache_clear()

    assert get_settings().supabase_url == "https://example-dev.supabase.co"


def test_is_production_flag(env):
    assert get_settings().is_production is False
    env.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    assert get_settings().is_production is True


def test_unknown_app_env_is_rejected(env):
    env.setenv("APP_ENV", "staging")
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError):
        get_settings()


def test_settings_type_is_exported():
    assert Settings.__name__ == "Settings"
