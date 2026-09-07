"""Centralised application configuration.

PROJECT_STRUCTURE §6: no module outside this one may read ``os.environ``.
The ruff ``banned-api`` rule in ``pyproject.toml`` enforces that mechanically.

SETUP_AND_ENVIRONMENT §11: startup validates required configuration and fails
clearly when a required secret or endpoint is missing. Optional integrations
(currently Resend) are feature-configurable and degrade to a null implementation
rather than bringing the whole application down.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.common.errors import ConfigurationError


class Settings(BaseSettings):
    """Every environment-provided value the application reads."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_env: Literal["development", "test", "production"] = "development"
    app_debug: bool = True
    default_timezone: str = "Asia/Jerusalem"
    default_content_language: str = "he"

    # --- Supabase ---
    supabase_url: str = Field(..., description="DEV or PROD Supabase project URL")
    supabase_anon_key: str = Field(..., description="Public anon key; safe for the UI process")
    supabase_service_role_key: str = Field(
        ..., description="Server-side only. Never exposed to Streamlit browser code."
    )
    supabase_storage_bucket: str = "plant-images"

    # --- AI provider ---
    ai_provider: str = "anthropic"
    ai_api_key: str = Field(..., description="Credential for the configured AI provider")
    identification_model: str = Field(..., description="Model id for the Identification Agent")
    knowledge_model: str = Field(..., description="Model id for the Knowledge Agent")
    care_model: str = Field(..., description="Model id for the Care Agent")
    health_model: str = Field(..., description="Model id for the Health Agent")
    # One timeout for four agents was wrong, and it took a real user to show it.
    # Identification is a vision call returning three candidates and measured at
    # about thirty seconds; Knowledge research writes thirteen sections of Hebrew
    # prose with source retrieval behind it and does not fit in ninety seconds -
    # the first real research run in DEV died at 90,354 ms with AGENT_TIMEOUT, and
    # a timeout is not retried, so the draft failed and the plant stayed
    # KNOWLEDGE_PENDING with nothing to approve.
    #
    # These are per-agent budgets, not guesses at how long a call takes: the point
    # is the boundary past which waiting longer is worse than failing. All four
    # are now measured against the live API (PR 31 walked the whole product in a
    # browser): identification 16-32s, health 73s, care 106s, knowledge research
    # 262s. Each budget is roughly twice its observed run, which leaves room for a
    # slow day without leaving a user waiting on something that is never coming.
    ai_request_timeout_seconds: int = 90
    identification_timeout_seconds: int = 90
    knowledge_timeout_seconds: int = 600
    care_timeout_seconds: int = 180
    health_timeout_seconds: int = 180
    # FINAL_SPECIFICATION §23: invalid structured output is retried at most twice.
    ai_max_structured_retries: int = 2

    # --- Email (optional; see `email_enabled`) ---
    resend_api_key: str | None = None
    resend_from_email: str | None = None

    # --- Internal scheduler tick ---
    internal_tick_secret: str = Field(
        ..., description="Shared secret guarding POST /v1/internal/tick"
    )
    # How often the API runs the sweep itself. PR 24 plans a Railway cron hitting
    # the endpoint; this exists so an API deployed without one is not silently
    # inert - no tasks, no overdue transitions, no reminders. 0 disables it, which
    # is what the test suite and CI use: a background timer inside a test process
    # writes to DEV on its own schedule and makes failures irreproducible.
    internal_tick_interval_seconds: int = 900

    # --- UI → API ---
    api_base_url: str = "http://localhost:8000"
    # Run the API inside the Streamlit process instead of beside it.
    #
    # Off everywhere except a single-process host. Streamlit Community Cloud runs
    # one process from one repository and offers no way to start a second, so the
    # UI would come up with nothing behind it. With this on, the entry point
    # starts uvicorn on a daemon thread bound to loopback and `api_base_url`
    # points at it. See DEPLOYMENT §3 - it is a deviation, not the target shape.
    embedded_api: bool = False

    # --- Rate limits for AI-triggering endpoints (A14) ---
    ai_rate_limit_per_hour: int = 10
    ai_rate_limit_per_minute: int = 3

    @field_validator("ai_max_structured_retries")
    @classmethod
    def _cap_retries(cls, v: int) -> int:
        # The 2-retry ceiling is an architectural invariant, not a tuning knob.
        if not 0 <= v <= 2:
            raise ValueError("ai_max_structured_retries must be between 0 and 2 (FINAL §23)")
        return v

    @field_validator("supabase_url")
    @classmethod
    def _require_https_in_prod(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("supabase_url must be an absolute http(s) URL")
        return v.rstrip("/")

    @property
    def email_enabled(self) -> bool:
        """Resend is optional. Without it the app runs with a null email provider."""
        return bool(self.resend_api_key and self.resend_from_email)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, failing loudly on missing configuration."""
    try:
        return Settings()
    except ValidationError as exc:
        missing = sorted(
            ".".join(str(p) for p in err["loc"]).upper()
            for err in exc.errors()
            if err["type"] == "missing"
        )
        invalid = [
            f"{'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}"
            for err in exc.errors()
            if err["type"] != "missing"
        ]
        lines = ["Application configuration is incomplete."]
        if missing:
            lines.append("Missing required variables:")
            lines.extend(f"  - {name}" for name in missing)
        if invalid:
            lines.append("Invalid values:")
            lines.extend(f"  - {item}" for item in invalid)
        lines.append("Copy .env.example to .env and fill in the values (see SETUP §5).")
        raise ConfigurationError("\n".join(lines)) from exc
