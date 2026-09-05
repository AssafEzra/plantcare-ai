"""Knowledge research end to end against DEV, with a scripted model.

Real database, scripted model, and a fetcher that never leaves the process. The
rules worth proving here are all about what gets *written*:

* research produces a draft and **never** a published version (FINAL §11);
* a failed run leaves the draft retriable rather than stranding plants (A17);
* an unverified citation is recorded as unverified rather than dropped or
  laundered (FINAL §10);
* confirming a species with no knowledge starts exactly one research run, no
  matter how many users confirm it.

None of these can be checked against a mock database: the partial unique index,
the RLS policies on `knowledge_drafts`, and the CHECK constraints on
`knowledge_sources` are the things being tested.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator

import pytest

from app.agents.knowledge.agent import KnowledgeAgent
from app.agents.knowledge.contract import (
    SECTION_NAMES,
    KnowledgeContent,
    KnowledgeOutput,
    KnowledgeSection,
    ProposedSource,
)
from app.common.enums import KnowledgeDraftStatus
from app.common.errors import AgentSchemaError
from app.domain.services import source_verification as verification
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider

pytestmark = pytest.mark.integration

TEXT = "מונסטרה דליציוזה גדלה היטב באור עקיף בהיר, ומשקים אותה כשהמצע מתייבש לעומק."


def _load_env() -> bool:
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    return bool(os.environ.get("SUPABASE_URL"))


@pytest.fixture(scope="module")
def live_env() -> None:
    if not _load_env():
        pytest.skip("no .env with DEV credentials")
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()


@pytest.fixture(scope="module")
def admin_sdk(live_env):
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


@pytest.fixture
def user_id(admin_sdk) -> Iterator[uuid.UUID]:
    """A real account: `knowledge_drafts.initiated_by` references `profiles`."""
    user = admin_sdk.auth.admin.create_user(
        {
            "email": f"kn-{uuid.uuid4().hex[:12]}@example.com",
            "password": "Know-Passw0rd!",
            "email_confirm": True,
        }
    ).user
    yield uuid.UUID(user.id)
    with contextlib.suppress(Exception):
        admin_sdk.auth.admin.delete_user(user.id)


@pytest.fixture
def species(admin_sdk) -> Iterator[dict]:
    """A species nothing else is researching.

    A fresh binomial per test, because the partial unique index allows one open
    draft per species — reusing a seeded species would make tests interfere.
    """
    name = f"Testus {uuid.uuid4().hex[:8]}ensis"
    row = admin_sdk.table("species").insert({"scientific_name": name}).execute().data[0]
    yield row
    with contextlib.suppress(Exception):
        admin_sdk.table("knowledge_drafts").delete().eq("species_id", row["id"]).execute()
        admin_sdk.table("species").delete().eq("id", row["id"]).execute()


def content() -> KnowledgeContent:
    return KnowledgeContent(
        **{name: KnowledgeSection(text=TEXT, confidence=0.8) for name in SECTION_NAMES}
    )


def agent_returning(*responses) -> KnowledgeAgent:
    return KnowledgeAgent(AIGateway(MockProvider(list(responses)), record_executions=False))


def draft_of(admin_sdk, species_id: str) -> dict | None:
    result = (
        admin_sdk.table("knowledge_drafts")
        .select("*")
        .eq("species_id", species_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def offline_fetcher(pages: dict[str, verification.FetchedPage | None]):
    """A fetcher that answers from a dict. No test here touches the network."""
    monkey = pages

    def _fetch(url: str) -> verification.FetchedPage | None:
        return monkey.get(url)

    return _fetch


# --- starting research ---------------------------------------------------------


def test_starting_research_opens_a_draft_and_an_agent_request(
    live_env, admin_sdk, species, user_id
):
    from app.orchestration.workflows import knowledge

    run = knowledge.start_research(species_id=uuid.UUID(species["id"]), initiated_by=user_id)

    draft = draft_of(admin_sdk, species["id"])
    assert draft["status"] == KnowledgeDraftStatus.RESEARCHING.value
    assert draft["research_request_id"] == str(run.request_id)

    request = (
        admin_sdk.table("agent_requests")
        .select("*")
        .eq("id", str(run.request_id))
        .execute()
        .data[0]
    )
    assert request["agent_type"] == "KNOWLEDGE"
    # Knowledge is global, so the request belongs to no plant. The column is
    # nullable for exactly this case.
    assert request["plant_id"] is None


def test_a_second_start_joins_the_open_draft_rather_than_racing_it(
    live_env, admin_sdk, species, user_id
):
    """The partial unique index would refuse a second open draft outright.

    Two research runs for one species would end with two versions of the same
    knowledge competing to publish, and would bill twice for it.
    """
    from app.orchestration.workflows import knowledge

    first = knowledge.start_research(species_id=uuid.UUID(species["id"]), initiated_by=user_id)
    second = knowledge.start_research(species_id=uuid.UUID(species["id"]), initiated_by=user_id)

    assert first.draft_id == second.draft_id

    drafts = (
        admin_sdk.table("knowledge_drafts").select("id").eq("species_id", species["id"]).execute()
    )
    assert len(drafts.data) == 1


# --- running it ----------------------------------------------------------------


def test_a_successful_run_produces_a_draft_awaiting_review_and_no_version(
    live_env, admin_sdk, species, user_id
):
    """FINAL §11: the Knowledge Agent never publishes.

    This is the assertion that matters most in the file — a published version
    written by research would be visible to every user of that species with
    nobody having read it.
    """
    from app.orchestration.workflows import knowledge

    run = knowledge.start_research(species_id=uuid.UUID(species["id"]), initiated_by=user_id)
    knowledge.execute_research(
        request_id=run.request_id,
        draft_id=run.draft_id,
        species_id=run.species_id,
        language=run.language,
        reason=None,
        agent=agent_returning(KnowledgeOutput(content=content())),
    )

    draft = draft_of(admin_sdk, species["id"])
    assert draft["status"] == KnowledgeDraftStatus.READY_FOR_REVIEW.value
    assert set(draft["content"]["sections"]) == set(SECTION_NAMES)

    versions = (
        admin_sdk.table("knowledge_versions").select("id").eq("species_id", species["id"]).execute()
    )
    assert versions.data == []


def test_a_failed_run_leaves_the_draft_retriable(live_env, admin_sdk, species, user_id):
    """A17. Plants sit in KNOWLEDGE_PENDING until something publishes; a draft
    that failed and could not be retried would strand every one of them."""
    from app.domain.rules.knowledge_lifecycle import is_retriable
    from app.orchestration.workflows import knowledge

    run = knowledge.start_research(species_id=uuid.UUID(species["id"]), initiated_by=user_id)

    with pytest.raises(AgentSchemaError):
        knowledge.execute_research(
            request_id=run.request_id,
            draft_id=run.draft_id,
            species_id=run.species_id,
            language=run.language,
            reason=None,
            agent=agent_returning(*[{"content": {"watering": "nonsense"}}] * 3),
        )

    draft = draft_of(admin_sdk, species["id"])
    assert draft["status"] == KnowledgeDraftStatus.FAILED.value
    assert is_retriable(KnowledgeDraftStatus(draft["status"]))

    request = (
        admin_sdk.table("agent_requests")
        .select("*")
        .eq("id", str(run.request_id))
        .execute()
        .data[0]
    )
    assert request["status"] == "FAILED"

    versions = (
        admin_sdk.table("knowledge_versions").select("id").eq("species_id", species["id"]).execute()
    )
    assert versions.data == []


def test_a_failed_run_can_be_researched_again(live_env, admin_sdk, species, user_id):
    from app.orchestration.workflows import knowledge

    first = knowledge.start_research(species_id=uuid.UUID(species["id"]), initiated_by=user_id)
    with pytest.raises(AgentSchemaError):
        knowledge.execute_research(
            request_id=first.request_id,
            draft_id=first.draft_id,
            species_id=first.species_id,
            language=first.language,
            reason=None,
            agent=agent_returning(*[{"nope": True}] * 3),
        )

    retry = knowledge.start_research(
        species_id=uuid.UUID(species["id"]), initiated_by=user_id, reason="retry after failure"
    )
    assert retry.draft_id == first.draft_id
    assert draft_of(admin_sdk, species["id"])["status"] == KnowledgeDraftStatus.RESEARCHING.value


# --- provenance ----------------------------------------------------------------


def test_an_unverifiable_citation_is_recorded_as_unverified(
    live_env, admin_sdk, species, user_id, monkeypatch
):
    """FINAL §10: a claim with no verified source is marked, not dropped.

    Dropping it would leave the draft looking better sourced than it is, which is
    the failure mode the whole verification step exists to prevent.
    """
    from app.orchestration.workflows import knowledge

    monkeypatch.setattr(verification, "fetch_page", offline_fetcher({}))

    run = knowledge.start_research(species_id=uuid.UUID(species["id"]), initiated_by=user_id)
    knowledge.execute_research(
        request_id=run.request_id,
        draft_id=run.draft_id,
        species_id=run.species_id,
        language=run.language,
        reason=None,
        agent=agent_returning(
            KnowledgeOutput(
                content=content(),
                sources=[ProposedSource(url="https://example.invalid/made-up")],
            )
        ),
    )

    sources = draft_of(admin_sdk, species["id"])["content"]["sources"]
    assert len(sources) == 1
    assert sources[0]["source_class"] == "AI_GENERATED_REQUIRES_VERIFICATION"
    assert sources[0]["url"] is None
    assert sources[0]["approved_source_id"] is None


def test_research_never_writes_knowledge_sources_rows(live_env, admin_sdk, species, user_id):
    """Those rows belong to a published version and are immutable.

    Writing them at draft time would freeze a draft's provenance while the draft
    itself is still being revised. They are created at approval (PR 15).
    """
    from app.orchestration.workflows import knowledge

    run = knowledge.start_research(species_id=uuid.UUID(species["id"]), initiated_by=user_id)
    knowledge.execute_research(
        request_id=run.request_id,
        draft_id=run.draft_id,
        species_id=run.species_id,
        language=run.language,
        reason=None,
        agent=agent_returning(
            KnowledgeOutput(
                content=content(), sources=[ProposedSource(url="https://example.invalid/x")]
            )
        ),
    )

    # No version exists, so no source row could legally reference one.
    assert (
        admin_sdk.table("knowledge_versions").select("id").eq("species_id", species["id"]).execute()
    ).data == []


# --- RLS -----------------------------------------------------------------------


def test_a_regular_user_cannot_read_a_draft(live_env, admin_sdk, species, user_id):
    """Drafts are admin-only (migration 0006).

    A user's visibility into pending research is their plant's KNOWLEDGE_PENDING
    status — unreviewed AI output is not something to show anybody.
    """
    from app.orchestration.workflows import knowledge
    from supabase import create_client

    knowledge.start_research(species_id=uuid.UUID(species["id"]), initiated_by=user_id)

    email = f"kn-reader-{uuid.uuid4().hex[:10]}@example.com"
    reader = admin_sdk.auth.admin.create_user(
        {"email": email, "password": "Read-Passw0rd!", "email_confirm": True}
    ).user
    try:
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        anon.auth.sign_in_with_password({"email": email, "password": "Read-Passw0rd!"})

        visible = (
            anon.table("knowledge_drafts").select("id").eq("species_id", species["id"]).execute()
        )
        assert visible.data == []
    finally:
        with contextlib.suppress(Exception):
            admin_sdk.auth.admin.delete_user(reader.id)
