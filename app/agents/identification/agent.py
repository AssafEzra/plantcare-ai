"""The Identification Agent.

Analyses photographs and proposes candidate species. It never writes anything:
the orchestration layer persists the result, and only after the user confirms
does a species become authoritative (FINAL §9).
"""

from __future__ import annotations

from uuid import UUID

from app.agents.base import Agent
from app.agents.identification.contract import (
    Candidate,
    IdentificationOutput,
    IdentificationRequest,
    IdentificationResult,
)
from app.common.enums import AgentType, IdentificationStatus
from app.common.errors import AgentError
from app.config.logging import get_logger
from app.infrastructure.ai.prompts import load as load_prompt

log = get_logger(__name__)

# Four photographs is the documented maximum (FINAL §8), and more images cost
# tokens without adding evidence.
MAX_IMAGES = 4


class IdentificationAgent(Agent[IdentificationRequest, IdentificationResult]):
    agent_type = AgentType.IDENTIFICATION

    def run(self, request: IdentificationRequest) -> IdentificationResult:
        raise NotImplementedError("use identify(), which carries the request id for logging")

    def identify(self, request: IdentificationRequest, *, request_id: UUID) -> IdentificationResult:
        if not request.images:
            # Not a model failure, so it does not spend a call or a retry.
            return IdentificationResult(
                status=IdentificationStatus.NEEDS_MORE_INFORMATION,
                request_more_photos=True,
                insufficient_reason="לא צורפו תמונות.",
            )

        prompt = load_prompt(AgentType.IDENTIFICATION, "identify")

        try:
            result = self.gateway.run(
                agent=AgentType.IDENTIFICATION,
                request_id=request_id,
                prompt=prompt,
                user_content=self._user_content(request),
                schema=IdentificationOutput,
                images=request.images[:MAX_IMAGES],
                max_tokens=4000,
            )
        except AgentError:
            # The gateway has already recorded the failed attempts. Returning
            # FAILED rather than re-raising lets the caller store a failed
            # identification row - which FINAL §25 permits, because a row whose
            # status is FAILED cannot carry a species or a confidence verdict.
            log.info("identification.failed", request_id=str(request_id))
            return IdentificationResult(
                status=IdentificationStatus.FAILED,
                insufficient_reason="הזיהוי לא הושלם. אפשר לנסות שוב.",
            )

        return self._interpret(result.value)

    def _user_content(self, request: IdentificationRequest) -> str:
        lines = [
            f"מצורפות {len(request.images[:MAX_IMAGES])} תמונות של צמח אחד.",
            "זהה את המין על סמך מה שנראה בתמונות בלבד.",
        ]
        if request.user_description:
            # Framed explicitly as a guess. FINAL §8: what the user thinks the
            # plant is, is contextual information and not confirmed fact - and a
            # model told "this is a monstera" will tend to agree.
            lines.append(
                "המשתמש כתב את ההערה הבאה. זהו ניחוש שלו, לא עובדה, "
                f"ואין להסתמך עליו כראיה: «{request.user_description.strip()[:500]}»"
            )
        return "\n".join(lines)

    def _interpret(self, output: IdentificationOutput) -> IdentificationResult:
        """Turn model output into a conclusion.

        Two corrections happen here rather than being trusted from the model:

        * candidates are **re-sorted by confidence**, so "primary" means the
          highest-scoring candidate rather than whichever the model listed first;
        * a SUCCESS with no candidates is downgraded. A model can report success
          and then return nothing, and a success with nothing in it would show the
          user an empty confirmation screen.
        """
        candidates = sorted(
            output.candidates, key=lambda candidate: candidate.confidence_score, reverse=True
        )[:3]
        candidates = self._deduplicate(candidates)

        status = output.status
        if status is IdentificationStatus.SUCCESS and not candidates:
            status = IdentificationStatus.NEEDS_MORE_INFORMATION

        return IdentificationResult(
            status=status,
            candidates=candidates if status is IdentificationStatus.SUCCESS else [],
            image_quality=output.image_quality,
            request_more_photos=output.request_more_photos
            or status is IdentificationStatus.NEEDS_MORE_INFORMATION,
            insufficient_reason=output.insufficient_reason,
        )

    @staticmethod
    def _deduplicate(candidates: list[Candidate]) -> list[Candidate]:
        """Drop repeats of the same species.

        A model sometimes offers the same plant twice with different spellings or
        authorship. Showing the user "Monstera deliciosa" and "Monstera deliciosa
        Liebm." as two options to choose between is confusing, and they resolve to
        one species at confirmation anyway.
        """
        seen: set[str] = set()
        unique: list[Candidate] = []
        for candidate in candidates:
            key = " ".join(candidate.scientific_name.lower().split()[:2])
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique
