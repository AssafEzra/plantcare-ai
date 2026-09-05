"""The Identification Agent's contract.

FINAL §9:

    IdentificationAgent.identify(request) -> IdentificationResult

What it does: analyse photographs, produce structured candidates, assess
confidence and image quality.

What it does **not** do: mutate the plant, modify Knowledge, create a Care Plan,
or touch Health. Persistence and the species decision belong to the orchestration
layer, after the user confirms — which is why the result below carries raw names
rather than species ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from app.common.enums import ConfidenceLevel, IdentificationStatus
from app.infrastructure.ai.provider import ImageInput

# A18. The specification fixes neither the scale nor the thresholds, so both are
# recorded here: a 0.0-1.0 probability, with the level derived in Python rather
# than taken from the model. Asking a model to self-report a category invites it
# to pick the label that sounds right rather than the one its evidence supports.
HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.60

# U+00D7 MULTIPLICATION SIGN, the botanical hybrid marker (as in Citrus x limon,
# where the "x" is really this character). Written by codepoint because it is
# visually indistinguishable from the letter x in most fonts.
HYBRID_SIGN = "\u00d7"


def confidence_level_for(score: float) -> ConfidenceLevel:
    if score >= HIGH_CONFIDENCE:
        return ConfidenceLevel.HIGH
    if score >= MEDIUM_CONFIDENCE:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


@dataclass(frozen=True)
class IdentificationRequest:
    """Everything the agent needs, assembled by orchestration.

    No client, no repository, no plant id: the agent looks at photographs and a
    sentence of context, and that is deliberately all it can see.
    """

    images: list[ImageInput]
    user_description: str | None = None
    locale: str = "he"


class Candidate(BaseModel):
    """One proposed species.

    Carries the raw name rather than a species id. Materialising a `species` row
    per candidate would let every low-confidence hallucinated binomial pollute the
    global taxonomy table; the row is created at confirmation, from the candidate
    the user actually chose (plan decision 2).
    """

    scientific_name: str = Field(min_length=3, max_length=200)
    common_name: str | None = Field(default=None, max_length=200)
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str | None = Field(
        default=None,
        max_length=500,
        description="Which visible features support this candidate. Not chain-of-thought: "
        "a short, user-facing justification that is shown on the confirmation screen.",
    )

    @field_validator("scientific_name")
    @classmethod
    def _looks_like_a_binomial(cls, value: str) -> str:
        """Reject anything that is plainly not a scientific name.

        A model asked for a binomial occasionally answers "unknown", "not a plant"
        or a whole sentence. Those are not names, and letting one through would
        create a species row for it at confirmation - permanently, in a table
        shared by every user.

        The shape of a binomial is narrow enough to check: a genus and an epithet,
        each a single word of letters, optionally with a hyphen. Latin has no
        digits and no punctuation beyond that, so anything else is prose.

        Hybrids are written with U+00D7 MULTIPLICATION SIGN, either standing alone
        between the two names or prefixed to one of them. It is dropped before the
        check rather than treated as a letter, so a hybrid name is accepted while
        the sign itself is never mistaken for an epithet.
        """
        cleaned = " ".join(value.split())
        parts = [part for part in cleaned.split() if part != HYBRID_SIGN]

        if len(parts) < 2:
            raise ValueError("a scientific name needs a genus and an epithet")
        if len(parts) > 5:
            raise ValueError("that is a sentence, not a scientific name")

        genus, epithet = parts[0], parts[1]

        def is_latin_word(word: str) -> bool:
            stripped = word.replace("-", "").replace(HYBRID_SIGN, "")
            return bool(stripped) and stripped.isalpha()

        if not is_latin_word(genus) or not is_latin_word(epithet):
            raise ValueError("a scientific name contains only letters and hyphens")

        # Real epithets are essentially never one or two letters, whereas the
        # filler words that make a sentence look like a name ("a", "is", "of")
        # always are.
        if len(genus.replace(HYBRID_SIGN, "")) < 3 or len(epithet.replace(HYBRID_SIGN, "")) < 3:
            raise ValueError("that does not look like a genus and epithet")

        return cleaned

    @property
    def confidence_level(self) -> ConfidenceLevel:
        return confidence_level_for(self.confidence_score)


class IdentificationOutput(BaseModel):
    """The schema the model is asked to fill.

    Separate from `IdentificationResult` on purpose: this is what an untrusted
    model produced, and the result is what the application concluded after
    checking it. Keeping them apart makes it obvious which is which.
    """

    status: IdentificationStatus
    candidates: list[Candidate] = Field(default_factory=list, max_length=3)
    image_quality: str | None = Field(default=None, max_length=300)
    request_more_photos: bool = False
    insufficient_reason: str | None = Field(default=None, max_length=500)


@dataclass
class IdentificationResult:
    """What the agent concluded, after the application's own checks.

    `wikipedia_url` is absent here and filled in later by deterministic
    verification against Wikipedia's own API (FINAL §8: the URL must never be
    invented). The agent is never asked for a link, so there is none to discard.
    """

    status: IdentificationStatus
    candidates: list[Candidate] = field(default_factory=list)
    image_quality: str | None = None
    request_more_photos: bool = False
    insufficient_reason: str | None = None

    @property
    def primary(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def succeeded(self) -> bool:
        return self.status is IdentificationStatus.SUCCESS and bool(self.candidates)
