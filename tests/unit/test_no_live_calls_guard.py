"""The guard that keeps the test suite free.

Every agent is reachable through a dependency a test can override, and the suites
do override them - except that `tick._reconcile_plans` built its own
`CareAgent(AIGateway())`. A gateway with no injected provider resolves one from
configuration, so there was nowhere for a scripted double to go in: running
`tests/integration/test_scheduler.py` and the e2e journeys made seventeen real CARE
calls on `claude-opus-5`, cost $1.11, and exhausted the Google free-tier quota that
a real user's next identification then needed.

That injection point is fixed. This file is the part that keeps it fixed: if a new
path constructs its own gateway, or an override is forgotten, it fails here loudly
instead of billing quietly.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.common.enums import AgentType
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.prompts import Prompt


class Answer(BaseModel):
    species: str


PROMPT = Prompt(agent=AgentType.IDENTIFICATION, name="identify", version="001", text="system text")


def test_a_gateway_with_no_injected_provider_cannot_reach_a_vendor(env):
    """The exact shape of the accident: `AIGateway()` with nothing passed."""
    with pytest.raises(AssertionError, match="reached the real"):
        AIGateway(record_executions=False).run(
            agent=AgentType.IDENTIFICATION,
            request_id=uuid4(),
            prompt=PROMPT,
            user_content="analyse this",
            schema=Answer,
        )


def test_the_guard_names_the_way_out(env):
    """A guard that only says "no" costs the next person an hour."""
    from app.infrastructure.ai import gateway

    with pytest.raises(AssertionError) as raised:
        gateway.provider_for("google")

    message = str(raised.value)
    assert "dependency_overrides" in message
    assert "'live'" in message


# --- which vendor a live test may reach ------------------------------------------
#
# A standing instruction: real model calls in testing go through Google, and
# specifically gemini-3.5-flash-lite, with no exceptions.
#
# The first version of this guard returned early for anything marked `live`, which
# turned the marker into a way out of the rule rather than a declaration of intent.
# `tests/agents/test_live_provider.py` - the one file that exists to spend money on a
# real API - was still calling `claude-opus-5` a day after the rule was set, and the
# enforcement everywhere else was decoration.
#
# These tests are marked `live` and make no call: they assert on what the guard does
# with the vendor name, which is decided before any request is built.


@pytest.mark.live
def test_a_live_test_may_reach_google(env):
    """The permitted path. A credential is needed only because `GoogleProvider`
    checks for one at construction - no request is made here."""
    env.setenv("GOOGLE_API_KEY", "google-key-for-tests")

    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    from app.infrastructure.ai import gateway

    provider = gateway.provider_for("google")

    assert provider.__class__.__name__ == "GoogleProvider"


@pytest.mark.live
@pytest.mark.parametrize("vendor", ["anthropic", "openai"])
def test_a_live_test_may_reach_nothing_else(env, vendor):
    """Named vendors rather than "not google", because the rule names one vendor.
    An openai call is exactly as much a mistake as an anthropic one."""
    from app.infrastructure.ai import gateway

    with pytest.raises(AssertionError) as raised:
        gateway.provider_for(vendor)

    message = str(raised.value)
    assert vendor in message
    assert "no exceptions" in message


@pytest.mark.live
def test_the_refusal_explains_the_rule_rather_than_only_refusing(env):
    """A guard that says only "no" costs the next person an hour working out whether
    they have hit a bug or a policy."""
    from app.infrastructure.ai import gateway

    with pytest.raises(AssertionError) as raised:
        gateway.provider_for("anthropic")

    assert "google" in str(raised.value)
