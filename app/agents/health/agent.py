"""The Health Agent (FINAL §16).

Looks at photographs and says what it sees, what that might mean, and what is
worth doing. It does not diagnose, does not touch the care plan, and does not
decide the trend.

Its most important behaviour is the one that looks like a failure: when the
evidence is too weak it returns `UNKNOWN` **with a reason**, and that assessment
is saved. §16 asks for exactly that, and it is why the image-quality gate warns
rather than rejects — blocking the upload would put the documented outcome out of
reach.
"""

from __future__ import annotations

import json
from uuid import UUID

from app.agents.base import Agent
from app.agents.health.contract import (
    MAX_IMAGES,
    HealthOutput,
    HealthRequest,
    HealthResult,
)
from app.common.enums import AgentType, HealthStatus
from app.common.errors import AgentError, ValidationFailedError
from app.config.logging import get_logger
from app.infrastructure.ai.prompts import load as load_prompt

log = get_logger(__name__)

MAX_TOKENS = 6000

# How much history to show. Enough for the agent to notice "this is the third
# time this month", little enough that the context stays about the photographs.
MAX_HISTORY = 5


class HealthAgent(Agent[HealthRequest, HealthResult]):
    agent_type = AgentType.HEALTH

    def run(self, request: HealthRequest) -> HealthResult:
        raise NotImplementedError("use assess(), which carries the request id for logging")

    def assess(self, request: HealthRequest, *, request_id: UUID) -> HealthResult:
        """Assess a plant's health from 1-4 photographs.

        A failure returns `UNKNOWN` rather than raising. FINAL §16 wants an
        unusable check *saved* with its reason, and such a row is honest about
        itself: it carries no confidence and no issues, which CHECK constraints
        also enforce. That is not the authoritative record §25 forbids — it is a
        record that no authoritative finding could be made.
        """
        if not request.images:
            raise ValidationFailedError("יש לצרף לפחות תמונה אחת.")

        prompt = load_prompt(AgentType.HEALTH, "assess")

        try:
            result = self.gateway.run(
                agent=AgentType.HEALTH,
                request_id=request_id,
                prompt=prompt,
                user_content=self._user_content(request),
                schema=HealthOutput,
                images=request.images[:MAX_IMAGES],
                max_tokens=MAX_TOKENS,
            )
        except AgentError:
            log.info("health.failed", request_id=str(request_id))
            return HealthResult(
                overall_status=HealthStatus.UNKNOWN,
                insufficient_information_reason=(
                    "הבדיקה לא הושלמה. אפשר לנסות שוב עם תמונות נוספות."
                ),
            )

        return self._interpret(result.value)

    def _interpret(self, output: HealthOutput) -> HealthResult:
        """Turn model output into a conclusion.

        One correction is applied rather than trusted: an `UNKNOWN` verdict is
        stripped of its issues and recommendations. A model that could not tell
        what it was looking at has no business also listing what might be wrong,
        and showing both would let a user act on findings the verdict disowns.
        """
        unknown = output.overall_status is HealthStatus.UNKNOWN

        if unknown and (output.possible_issues or output.recommendations):
            log.info("health.unknown_findings_dropped", issues=len(output.possible_issues))

        return HealthResult(
            overall_status=output.overall_status,
            confidence_level=None if unknown else output.confidence_level,
            # An inconclusive check may still be worth a second look; that is the
            # one flag it can honestly raise.
            requires_attention=output.requires_attention,
            observations=output.observations,
            possible_issues=[] if unknown else output.possible_issues,
            recommendations=[] if unknown else output.recommendations,
            insufficient_information_reason=output.insufficient_information_reason,
        )

    def _user_content(self, request: HealthRequest) -> str:
        context = request.context
        count = len(request.images[:MAX_IMAGES])
        lines = [
            f"מצורפות {count} תמונות של הצמח.",
            f"מין: {context.scientific_name}"
            + (f" ({context.common_name})" if context.common_name else ""),
        ]
        if context.plant_name:
            lines.append(f"שם הצמח אצל המשתמש: {context.plant_name}")

        if request.image_warnings:
            # A25. A model told the photographs are weak returns UNKNOWN honestly
            # far more often than one left to work it out.
            lines.append("\n## הערות על איכות התמונות")
            lines.extend(f"- {warning}" for warning in request.image_warnings)

        if request.user_note:
            lines.append(
                f"\n## מה שהמשתמש כתב\nזהו תיאור שלו, לא ממצא. «{request.user_note.strip()[:1000]}»"
            )

        if context.knowledge_sections:
            lines.append("\n## מידע מקצועי על המין")
            lines.extend(f"- {name}: {text}" for name, text in context.knowledge_sections.items())

        if context.environment:
            lines.append("\n## סביבת הגידול")
            lines.append(self._as_json(context.environment))

        if context.previous_assessments:
            # Not so the agent can compute a trend — that is Python's job — but so
            # it can notice a recurrence, which changes what is worth suggesting.
            lines.append("\n## בדיקות קודמות")
            lines.append(self._as_json(context.previous_assessments[:MAX_HISTORY]))

        if context.care_history:
            lines.append("\n## היסטוריית טיפול בפועל")
            lines.append(self._as_json(context.care_history[:MAX_HISTORY]))

        if context.current_care_rules:
            lines.append("\n## תוכנית הטיפול הנוכחית")
            lines.append(self._as_json(context.current_care_rules))

        return "\n".join(lines)

    @staticmethod
    def _as_json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)
