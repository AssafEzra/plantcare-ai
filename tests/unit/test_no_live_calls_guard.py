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
