"""The Care Agent.

FINAL §12. Turns Knowledge plus one plant's circumstances into a proposal. It
does not activate a plan, does not touch tasks, and does not schedule anything —
scheduling is deterministic Python (FINAL §1.4), and the agent's rules are the
*input* to that, not a substitute for it.
"""

from __future__ import annotations

import json
from uuid import UUID

from app.agents.base import Agent
from app.agents.care.contract import (
    CarePlanOutput,
    CarePlanProposal,
    CarePlanRequest,
    ProposedRule,
)
from app.common.enums import AgentType, CarePlanVersionSourceType
from app.common.errors import AgentError
from app.config.logging import get_logger
from app.domain.rules import care_rule_validation as rules
from app.infrastructure.ai.prompts import load as load_prompt

log = get_logger(__name__)

MAX_TOKENS = 6000

# How much history to show. Enough to see a pattern, little enough that the
# context stays about this plant rather than becoming a log dump.
MAX_HISTORY_ITEMS = 10

WHY = {
    CarePlanVersionSourceType.INITIAL_PLAN: "זוהי תוכנית הטיפול הראשונה עבור הצמח.",
    CarePlanVersionSourceType.ENVIRONMENT_CHANGE: (
        "תנאי הסביבה של הצמח השתנו. בדוק אם התוכנית הקיימת עדיין מתאימה."
    ),
    CarePlanVersionSourceType.HEALTH_DRIVEN: (
        "בבדיקת בריאות עלה ממצא שעשוי להצריך התאמה של תוכנית הטיפול."
    ),
    CarePlanVersionSourceType.RE_IDENTIFICATION: (
        "הצמח זוהה מחדש כמין אחר. יש לבנות תוכנית המתאימה למין החדש."
    ),
    CarePlanVersionSourceType.OPERATIONAL_ADJUSTMENT: (
        "המשתמש שינה העדפה תפעולית. ההמלצות המקצועיות נשארות כפי שהן."
    ),
}


class CareAgent(Agent[CarePlanRequest, CarePlanProposal]):
    agent_type = AgentType.CARE

    def run(self, request: CarePlanRequest) -> CarePlanProposal:
        raise NotImplementedError("use generate_plan(), which carries the request id for logging")

    def generate_plan(self, request: CarePlanRequest, *, request_id: UUID) -> CarePlanProposal:
        """Propose a plan. Raises on failure rather than returning an empty one.

        FINAL §25: a failed AI operation must leave no authoritative record. A
        proposal with no rules would be exactly that record - it would appear in
        the user's proposal list looking approvable, and approving it would
        activate a plan that schedules nothing.
        """
        prompt = load_prompt(AgentType.CARE, "plan")

        result = self.gateway.run(
            agent=AgentType.CARE,
            request_id=request_id,
            prompt=prompt,
            user_content=self._user_content(request),
            schema=CarePlanOutput,
            max_tokens=MAX_TOKENS,
        )

        proposal = self._interpret(result.value)
        log.info(
            "care.plan_proposed",
            request_id=str(request_id),
            reason=request.reason.value,
            rules=len(proposal.rules),
            dropped=len(result.value.rules) - len(proposal.rules),
        )

        if not proposal.is_actionable:
            raise AgentError("the proposed plan contained no schedulable rule")
        return proposal

    def _interpret(self, output: CarePlanOutput) -> CarePlanProposal:
        """Drop rules the scheduler could not honour, and collapse duplicates.

        Validation runs here rather than being left to the database because a rule
        the database rejects fails the whole insert, losing the six good rules
        alongside the bad one. Dropping the individual rule keeps a usable plan,
        and the drop is logged.

        A duplicate action type is a competing rule, not a richer schedule: the
        scheduler would materialise a task for each and tell the user to water the
        same plant twice. The first one wins, since the model lists in priority
        order.
        """
        kept: list[ProposedRule] = []
        seen: set[str] = set()

        for rule in output.rules:
            violations = rules.validate(
                action_type=rule.action_type,
                interval_days=rule.interval_days,
                preferred_time_local=rule.preferred_time_local,
                preferred_weekday=rule.preferred_weekday,
            )
            if violations:
                log.info(
                    "care.rule_rejected",
                    action_type=rule.action_type.value,
                    reasons=[v.reason for v in violations],
                )
                continue
            if rule.action_type.value in seen:
                log.info("care.rule_duplicate_dropped", action_type=rule.action_type.value)
                continue
            seen.add(rule.action_type.value)
            kept.append(rule)

        return CarePlanProposal(
            recommendations=output.recommendations,
            rules=kept,
            change_summary=output.change_summary,
            missing_context=output.missing_context,
        )

    def _user_content(self, request: CarePlanRequest) -> str:
        context = request.context
        lines = [
            WHY[request.reason],
            "",
            f"מין: {context.scientific_name}"
            + (f" ({context.common_name})" if context.common_name else ""),
        ]
        if context.plant_name:
            lines.append(f"שם הצמח אצל המשתמש: {context.plant_name}")
        lines.append(f"אזור זמן: {context.timezone}")

        if context.knowledge_sections:
            lines.append("\n## מידע מקצועי מאושר על המין")
            for name, text in context.knowledge_sections.items():
                lines.append(f"- {name}: {text}")

        if context.environment:
            lines.append("\n## סביבת הגידול בפועל")
            lines.append(self._as_json(context.environment))

        if context.current_health_status:
            lines.append(f"\n## מצב בריאות נוכחי\n{context.current_health_status}")

        if context.health_history:
            lines.append("\n## היסטוריית בריאות")
            lines.append(self._as_json(context.health_history[:MAX_HISTORY_ITEMS]))

        if context.care_history:
            # What the user actually did, which is often not what the plan said.
            lines.append("\n## היסטוריית טיפול בפועל")
            lines.append(self._as_json(context.care_history[:MAX_HISTORY_ITEMS]))

        if context.user_preferences:
            lines.append("\n## העדפות המשתמש")
            lines.append(self._as_json(context.user_preferences))

        if request.current_rules:
            lines.append("\n## כללי הטיפול הקיימים")
            lines.append(self._as_json(request.current_rules))

        if request.note:
            lines.append(f"\n## הערה לבקשה הזו\n{request.note.strip()[:1000]}")

        return "\n".join(lines)

    @staticmethod
    def _as_json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)
