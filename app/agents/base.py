"""The agent boundary.

FINAL §23 and PROJECT_STRUCTURE §5: each agent exposes a stable contract, agents
never call one another, and the orchestration layer coordinates them.

Two constraints are enforced structurally rather than by convention:

* an agent receives a **fully assembled context object** and the gateway, and
  nothing else. It has no client, no repository and no way to reach the database,
  so it cannot quietly acquire a dependency on persistence;
* agents cannot import one another. `tests/unit/test_agent_boundaries.py` walks
  the import graph and fails if one does, which is the only way a rule like this
  survives contact with a deadline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.common.enums import AgentType
from app.infrastructure.ai.gateway import AIGateway


class Agent[RequestT, ResultT](ABC):
    """Base for the four agents.

    The gateway is injected rather than constructed, so a test can drive an agent
    with a scripted provider and never touch a network.

    `ResultT` is deliberately unconstrained. What the *model* returns is always a
    schema-validated Pydantic model, enforced by the gateway; what the *agent*
    returns is the application's conclusion after its own checks, and those two
    are not the same thing. Requiring the conclusion to be a Pydantic model would
    blur exactly the line worth keeping visible.
    """

    agent_type: AgentType

    def __init__(self, gateway: AIGateway) -> None:
        self._gateway = gateway

    @property
    def gateway(self) -> AIGateway:
        return self._gateway

    @abstractmethod
    def run(self, request: RequestT) -> ResultT:
        """Execute the agent's contract.

        Implementations must not write to the database. Persistence is the
        orchestration layer's job, and keeping it there is what makes FINAL §25
        - "AI failure never creates an authoritative record" - straightforward
        rather than a thing every agent has to remember.
        """
        raise NotImplementedError
