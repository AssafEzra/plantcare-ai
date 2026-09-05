"""The Knowledge Agent's contract (FINAL §11, A16).

The contract is the guard rail. `knowledge_versions.content` is `jsonb`, so
nothing in the database stops a malformed draft being written — the Pydantic
model is the only thing standing between a model's output and a document a user
will read as professional advice.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.agents.knowledge.agent import KnowledgeAgent
from app.agents.knowledge.contract import (
    SECTION_NAMES,
    KnowledgeContent,
    KnowledgeOutput,
    KnowledgeRequest,
    KnowledgeSection,
    ProposedSource,
)
from app.common.enums import AgentType
from app.common.errors import AgentSchemaError
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider

TEXT = "מונסטרה דליציוזה גדלה היטב באור עקיף בהיר ואינה אוהבת שמש ישירה."


def content(**overrides: KnowledgeSection) -> KnowledgeContent:
    base = {name: KnowledgeSection(text=TEXT, confidence=0.8) for name in SECTION_NAMES}
    base.update(overrides)
    return KnowledgeContent(**base)


def agent_with(*outputs: KnowledgeOutput) -> KnowledgeAgent:
    return KnowledgeAgent(AIGateway(MockProvider(list(outputs)), record_executions=False))


# --- the content schema (A16) --------------------------------------------------


def test_every_one_of_the_fourteen_sections_is_required():
    """FINAL §10 lists them; a draft missing one is not a draft.

    Without this, a model that ran out of tokens mid-answer produces a document
    whose Toxicity/Safety section is simply absent - the section a user with a cat
    goes looking for.
    """
    fields = set(KnowledgeContent.model_fields)
    assert fields == set(SECTION_NAMES)

    for missing in SECTION_NAMES:
        partial = {name: KnowledgeSection(text=TEXT) for name in SECTION_NAMES if name != missing}
        with pytest.raises(ValidationError):
            KnowledgeContent(**partial)


def test_a_blank_or_stub_section_is_rejected():
    for bad in ["", "   ", "אין מידע"]:
        with pytest.raises(ValidationError):
            KnowledgeSection(text=bad)


def test_a_section_cannot_run_forever():
    with pytest.raises(ValidationError):
        KnowledgeSection(text="א" * 4001)


def test_whitespace_is_collapsed():
    assert KnowledgeSection(text="  שורה  ראשונה\n\n  שורה שנייה  ").text == (
        "שורה ראשונה שורה שנייה"
    )


def test_confidence_stays_within_range():
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            KnowledgeSection(text=TEXT, confidence=bad)


def test_unknown_sections_are_refused():
    """`extra: forbid`. A model inventing a fifteenth section would otherwise
    write it into the content blob where nothing renders it and nobody reviews
    it."""
    with pytest.raises(ValidationError):
        KnowledgeContent(
            **{name: KnowledgeSection(text=TEXT) for name in SECTION_NAMES},
            pest_control=KnowledgeSection(text=TEXT),
        )


def test_weak_sections_come_back_worst_first():
    """The admin's reading order. A draft is reviewed by a person with limited
    time, and the least-supported section is where that time is worth spending."""
    doc = content(
        watering=KnowledgeSection(text=TEXT, confidence=0.2),
        propagation=KnowledgeSection(text=TEXT, confidence=0.4),
    )
    assert doc.weakest_sections == ["watering", "propagation"]


def test_a_confident_draft_flags_nothing():
    assert content().weakest_sections == []


# --- proposed sources ----------------------------------------------------------


def test_a_source_must_carry_an_absolute_http_url():
    for bad in ["rhs.org.uk/monstera", "ftp://rhs.org.uk/x", "/plants/monstera"]:
        with pytest.raises(ValidationError):
            ProposedSource(url=bad)


def test_a_source_has_no_field_for_its_own_class():
    """The model does not get to say a source is APPROVED.

    That classification is what `source_verification.py` decides after fetching
    the page, and a field here would be an invitation to trust the self-report
    (FINAL §23).
    """
    assert "source_class" not in ProposedSource.model_fields
    with pytest.raises(ValidationError):
        ProposedSource(url="https://rhs.org.uk/x", source_class="APPROVED")


def test_unknown_section_cross_references_are_dropped_not_fatal():
    """A mislabelled cross-reference is cosmetic; failing the run over it would
    spend two retries and produce nothing."""
    source = ProposedSource(
        url="https://rhs.org.uk/x", supports_sections=["watering", "feng_shui", "watering"]
    )
    assert source.supports_sections == ["watering"]


# --- the agent -----------------------------------------------------------------


def test_generate_returns_the_researched_content():
    agent = agent_with(
        KnowledgeOutput(
            content=content(),
            sources=[ProposedSource(url="https://rhs.org.uk/monstera")],
            research_notes="הנתונים על השקיה עקביים בין המקורות.",
        )
    )
    result = agent.generate(
        KnowledgeRequest(scientific_name="Monstera deliciosa"), request_id=uuid.uuid4()
    )

    assert result.content.watering.text == TEXT
    assert len(result.proposed_sources) == 1
    assert result.research_notes is not None


def test_the_same_url_cited_twice_becomes_one_source():
    agent = agent_with(
        KnowledgeOutput(
            content=content(),
            sources=[
                ProposedSource(url="https://rhs.org.uk/monstera", supports_sections=["watering"]),
                ProposedSource(url="https://rhs.org.uk/monstera/", supports_sections=["light"]),
                ProposedSource(url="https://mobot.org/monstera"),
            ],
        )
    )
    result = agent.generate(
        KnowledgeRequest(scientific_name="Monstera deliciosa"), request_id=uuid.uuid4()
    )

    urls = [source.url for source in result.proposed_sources]
    assert urls == ["https://rhs.org.uk/monstera", "https://mobot.org/monstera"]


def test_a_failed_research_run_raises_rather_than_returning_an_empty_draft():
    """Unlike identification, there is no useful partial answer here.

    Swallowing the failure would leave an administrator reviewing a blank draft;
    raising lets the workflow mark it FAILED, which A17 keeps retriable.
    """
    # Malformed on every attempt: the gateway spends its budget and gives up.
    agent = agent_with(*[{"content": {"watering": "just a string"}}] * 3)

    with pytest.raises(AgentSchemaError):
        agent.generate(
            KnowledgeRequest(scientific_name="Monstera deliciosa"), request_id=uuid.uuid4()
        )


def test_the_agent_uses_the_knowledge_model():
    """FINAL §23: each agent's model is configuration. A knowledge run using the
    identification model would be a silent cost and quality change."""
    provider = MockProvider([KnowledgeOutput(content=content())])
    agent = KnowledgeAgent(AIGateway(provider, record_executions=False))
    agent.generate(KnowledgeRequest(scientific_name="Monstera deliciosa"), request_id=uuid.uuid4())

    assert agent.agent_type is AgentType.KNOWLEDGE
    assert provider.calls[0]["model"] == agent.gateway.model_for(AgentType.KNOWLEDGE)


def test_the_users_language_and_approved_domains_reach_the_prompt():
    provider = MockProvider([KnowledgeOutput(content=content())])
    agent = KnowledgeAgent(AIGateway(provider, record_executions=False))
    agent.generate(
        KnowledgeRequest(
            scientific_name="Monstera deliciosa",
            common_name="מונסטרה",
            approved_domains=["rhs.org.uk", "missouribotanicalgarden.org"],
        ),
        request_id=uuid.uuid4(),
    )

    sent = provider.calls[0]["prompt"]
    assert "Monstera deliciosa" in sent
    assert "rhs.org.uk" in sent
    # The preference is stated as a preference. A model told these are the only
    # permitted sources will invent a citation on one of them rather than admit it
    # used something else - which FINAL §10 explicitly allows it to do.
    assert "מקורות מועדפים" in sent


def test_run_is_not_the_entry_point():
    agent = KnowledgeAgent(AIGateway(MockProvider(), record_executions=False))
    with pytest.raises(NotImplementedError):
        agent.run(KnowledgeRequest(scientific_name="Monstera deliciosa"))
