"""The Knowledge Agent.

FINAL §11. Researches a species and produces a draft. It never publishes, never
touches a plant, and never verifies its own sources — that last one matters:
asking a model whether the page it cited exists gets you a confident yes.
"""

from __future__ import annotations

from uuid import UUID

from app.agents.base import Agent
from app.agents.knowledge.contract import (
    KnowledgeOutput,
    KnowledgeRequest,
    KnowledgeResult,
    ProposedSource,
)
from app.common.enums import AgentType
from app.config.logging import get_logger
from app.infrastructure.ai.prompts import load as load_prompt

log = get_logger(__name__)

# Fourteen sections of Hebrew prose plus a source list. Generous, because a draft
# truncated mid-section fails schema validation and spends a retry.
MAX_TOKENS = 16_000

# How many approved domains to name in the prompt. All of them would be a long
# list that buries the instruction; the preference is a steer, and unapproved
# sources are permitted anyway (FINAL §10) as long as they are marked.
MAX_LISTED_DOMAINS = 25


class KnowledgeAgent(Agent[KnowledgeRequest, KnowledgeResult]):
    agent_type = AgentType.KNOWLEDGE

    def run(self, request: KnowledgeRequest) -> KnowledgeResult:
        raise NotImplementedError("use generate(), which carries the request id for logging")

    def generate(self, request: KnowledgeRequest, *, request_id: UUID) -> KnowledgeResult:
        """Research a species.

        Unlike identification, a failure here is **not** caught and turned into a
        result. There is no useful partial answer to a research request: an empty
        draft is not knowledge, and swallowing the error would leave an
        administrator reviewing a blank one. The caller marks the draft FAILED,
        which A17 makes retriable — plants stay `KNOWLEDGE_PENDING` rather than
        being released against knowledge nobody produced.
        """
        prompt = load_prompt(AgentType.KNOWLEDGE, "research")

        result = self.gateway.run(
            agent=AgentType.KNOWLEDGE,
            request_id=request_id,
            prompt=prompt,
            user_content=self._user_content(request),
            schema=KnowledgeOutput,
            max_tokens=MAX_TOKENS,
        )

        output = result.value
        log.info(
            "knowledge.generated",
            request_id=str(request_id),
            scientific_name=request.scientific_name,
            proposed_sources=len(output.sources),
            weak_sections=len(output.content.weakest_sections),
        )

        return KnowledgeResult(
            content=output.content,
            proposed_sources=self._deduplicate(output.sources),
            research_notes=output.research_notes,
        )

    def _user_content(self, request: KnowledgeRequest) -> str:
        lines = [f"מין: {request.scientific_name}"]
        if request.common_name:
            lines.append(f"שם נפוץ: {request.common_name}")
        lines.append(f"שפת הכתיבה: {request.language}")

        if request.approved_domains:
            listed = ", ".join(request.approved_domains[:MAX_LISTED_DOMAINS])
            lines.append(
                "מקורות מועדפים (העדף אותם כשהם מכסים את השאלה, "
                f"אך אל תמציא ציטוט כדי להשתמש בהם): {listed}"
            )

        if request.reason:
            # A retry after a rejection carries the administrator's note, so the
            # second attempt can address the objection instead of reproducing it.
            lines.append(f"הקשר לבקשה הזו: {request.reason.strip()[:1000]}")

        return "\n".join(lines)

    @staticmethod
    def _deduplicate(sources: list[ProposedSource]) -> list[ProposedSource]:
        """One entry per URL.

        A model citing the same page under three section headings produces three
        identical rows, three HTTP fetches during verification, and a provenance
        list that looks padded.
        """
        seen: set[str] = set()
        unique: list[ProposedSource] = []
        for source in sources:
            key = source.url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(source)
        return unique
