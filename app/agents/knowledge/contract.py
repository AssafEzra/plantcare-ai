"""The Knowledge Agent's contract.

FINAL §11:

    KnowledgeAgent.generate(request) -> KnowledgeDraft

What it does: research a species, produce the fourteen sections of FINAL §10,
propose sources, and say plainly where it is uncertain.

What it does **not** do: publish, touch a user's plants, create a Care Plan, or
diagnose anything. Publication is an admin action (PR 15); everything here is a
proposal that an administrator reads before any user sees it.

A16 — the content schema
------------------------
`DATABASE_SCHEMA` types `knowledge_versions.content` as `jsonb` and says nothing
about its shape, which would make every consumer guess. `KnowledgeContent` below
is the recorded shape: it is validated when the draft is written *and* again at
publication, so a version that reaches a user has been checked twice against the
same model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

# The fourteen sections of FINAL §10, in the order the specification lists them.
# `Sources` is the fifteenth item there but is not prose: it is the provenance
# record, which lives in `knowledge_sources` rows rather than inside the content
# blob, so that a source can carry a class, a URL and a retrieval timestamp the
# database can constrain.
SECTION_NAMES: tuple[str, ...] = (
    "identification",
    "description",
    "light",
    "watering",
    "soil",
    "temperature",
    "humidity",
    "fertilization",
    "repotting",
    "pruning",
    "propagation",
    "common_problems",
    "toxicity_safety",
)

# Long enough for a genuinely useful paragraph or two, short enough that a model
# which starts rambling fails validation rather than filling a page.
_MIN_SECTION = 20
_MAX_SECTION = 4000


class KnowledgeSection(BaseModel):
    """One section of a species' knowledge.

    `confidence` is not shown to users; it is an admin review signal. A section
    the agent is unsure of is exactly what an administrator should read first,
    and burying that in prose would hide it.
    """

    model_config = {"extra": "forbid"}

    text: str = Field(min_length=_MIN_SECTION, max_length=_MAX_SECTION)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("text")
    @classmethod
    def _not_a_refusal(cls, value: str) -> str:
        """Reject a section that says it has nothing to say.

        A model that cannot research a species sometimes fills the field with an
        apology rather than failing. Publishing "I could not find information
        about this plant" as the Watering section would be worse than publishing
        nothing, because it looks like content.
        """
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("a section may not be blank")
        return collapsed


class ProposedSource(BaseModel):
    """A source the model claims to have used.

    A *claim*, not a record. Nothing here reaches `knowledge_sources` until
    `domain/services/source_verification.py` has fetched the URL itself and
    classified it. FINAL §23 makes verification authoritative, not the
    self-report — so this model deliberately has no `source_class` field for the
    model to fill in.
    """

    model_config = {"extra": "forbid"}

    url: str = Field(min_length=8, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    publisher: str | None = Field(default=None, max_length=200)
    supports_sections: list[str] = Field(default_factory=list, max_length=len(SECTION_NAMES))

    @field_validator("url")
    @classmethod
    def _absolute_http_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("a source URL must be absolute and http(s)")
        return cleaned

    @field_validator("supports_sections")
    @classmethod
    def _known_sections(cls, value: list[str]) -> list[str]:
        """Silently drop unknown section names rather than failing the draft.

        A mislabelled cross-reference is a cosmetic error in a field used only to
        show an administrator which claims a source backs. Failing the whole
        research run over it would spend two retries and produce nothing.
        """
        return [name for name in dict.fromkeys(value) if name in SECTION_NAMES]


class KnowledgeContent(BaseModel):
    """The fourteen sections, as stored in `knowledge_drafts.content` and,
    after approval, in `knowledge_versions.content` (A16)."""

    model_config = {"extra": "forbid"}

    identification: KnowledgeSection
    description: KnowledgeSection
    light: KnowledgeSection
    watering: KnowledgeSection
    soil: KnowledgeSection
    temperature: KnowledgeSection
    humidity: KnowledgeSection
    fertilization: KnowledgeSection
    repotting: KnowledgeSection
    pruning: KnowledgeSection
    propagation: KnowledgeSection
    common_problems: KnowledgeSection
    toxicity_safety: KnowledgeSection

    def section(self, name: str) -> KnowledgeSection:
        section: KnowledgeSection = getattr(self, name)
        return section

    @property
    def weakest_sections(self) -> list[str]:
        """Sections below the halfway mark, worst first — the admin's reading order."""
        scored = [(name, self.section(name).confidence) for name in SECTION_NAMES]
        return [name for name, score in sorted(scored, key=lambda p: p[1]) if score < 0.5]


class KnowledgeOutput(BaseModel):
    """The schema the model is asked to fill.

    Separate from :class:`KnowledgeResult` for the same reason the Identification
    Agent separates its two: this is what an untrusted model produced, and the
    result is what the application concluded after checking it.
    """

    model_config = {"extra": "forbid"}

    content: KnowledgeContent
    sources: list[ProposedSource] = Field(default_factory=list, max_length=20)
    research_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="What was hard to establish and what an administrator should check. "
        "A review aid, not chain-of-thought: it describes the state of the evidence, "
        "not the steps taken to reach a conclusion.",
    )


@dataclass(frozen=True)
class KnowledgeRequest:
    """Everything the agent needs, assembled by orchestration.

    A name and a language. No client, no repository, no draft id — the agent
    cannot read or write the database, which is what makes "the Knowledge Agent
    never publishes" structural rather than a matter of care.
    """

    scientific_name: str
    common_name: str | None = None
    language: str = "he"
    approved_domains: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass
class KnowledgeResult:
    """What the agent concluded.

    `proposed_sources` are still *claims* at this point. The agent has no network
    access beyond the model call, so it cannot verify a URL; orchestration passes
    them to `domain/services/source_verification.py`, which fetches each one and
    decides its class, before anything is written.
    """

    content: KnowledgeContent
    proposed_sources: list[ProposedSource] = field(default_factory=list)
    research_notes: str | None = None

    @property
    def needs_attention(self) -> list[str]:
        return self.content.weakest_sections
