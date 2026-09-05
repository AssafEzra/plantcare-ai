"""Admin review, publication and fan-out, against DEV.

The interesting assertions here are all things only a real database can answer:

* publication is one transaction, so a species never has two current versions and
  never has none;
* a published version is immutable — the trigger refuses the UPDATE, and DELETE
  is refused for everyone including administrators (FINAL §29);
* approving releases every `KNOWLEDGE_PENDING` plant of that species (A4), and
  touches no other plant;
* rejecting releases nobody and leaves the species retriable (A17);
* a regular user is refused every admin route, and RLS refuses them even if the
  dependency were removed.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.agents.knowledge.agent import KnowledgeAgent
from app.agents.knowledge.contract import (
    SECTION_NAMES,
    KnowledgeContent,
    KnowledgeOutput,
    KnowledgeSection,
    ProposedSource,
)
from app.api.routers.knowledge import get_knowledge_agent
from app.common.enums import KnowledgeDraftStatus, PlantStatus
from app.domain.services import source_verification as verification
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider
from tests.integration.conftest import unique_species_name

pytestmark = pytest.mark.integration

PASSWORD = "Admin-Passw0rd!"
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
def scripted():
    return MockProvider()


@pytest.fixture
def api(live_env, scripted) -> Iterator[TestClient]:
    from app.api.main import create_app

    app = create_app()
    app.dependency_overrides[get_knowledge_agent] = lambda: KnowledgeAgent(
        AIGateway(scripted, record_executions=False)
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def account(admin_sdk):
    """Makes users, optionally promoted to ADMIN."""
    from supabase import create_client

    created: list[str] = []

    def _make(role: str = "USER") -> tuple[str, dict[str, str]]:
        email = f"kadm-{uuid.uuid4().hex[:12]}@example.com"
        user = admin_sdk.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user
        created.append(user.id)
        if role == "ADMIN":
            # Through the service role: the guard trigger stops a user promoting
            # themselves, which is the point of it.
            admin_sdk.table("profiles").update({"role": "ADMIN"}).eq("id", user.id).execute()
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        token = anon.auth.sign_in_with_password(
            {"email": email, "password": PASSWORD}
        ).session.access_token
        return user.id, {"Authorization": f"Bearer {token}"}

    yield _make

    for user_id in created:
        with contextlib.suppress(Exception):
            admin_sdk.auth.admin.delete_user(user_id)


@pytest.fixture
def species(admin_sdk) -> Iterator[dict]:
    # unique_species_name(), not a hex string: normalize_scientific_name() strips
    # digits, so "Testus a1b2c3ensis" collapses to "testus aensis" and collides
    # with every other such name.
    row = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name()})
        .execute()
        .data[0]
    )
    yield row
    with contextlib.suppress(Exception):
        admin_sdk.table("plants").delete().eq("species_id", row["id"]).execute()
        admin_sdk.table("knowledge_drafts").delete().eq("species_id", row["id"]).execute()
        # Versions and their sources are ON DELETE RESTRICT and refuse deletion by
        # design, so a published version outlives its test. Harmless: every test
        # uses its own species.


def content() -> KnowledgeContent:
    return KnowledgeContent(
        **{name: KnowledgeSection(text=TEXT, confidence=0.8) for name in SECTION_NAMES}
    )


def researched_draft(
    admin_sdk, species_id: str, user_id: uuid.UUID, *, sources: list[ProposedSource] | None = None
) -> str:
    """A draft in READY_FOR_REVIEW, produced by a real research run."""
    from app.orchestration.workflows import knowledge

    run = knowledge.start_research(species_id=uuid.UUID(species_id), initiated_by=user_id)
    agent = KnowledgeAgent(
        AIGateway(
            MockProvider([KnowledgeOutput(content=content(), sources=sources or [])]),
            record_executions=False,
        )
    )
    knowledge.execute_research(
        request_id=run.request_id,
        draft_id=run.draft_id,
        species_id=run.species_id,
        language=run.language,
        reason=None,
        agent=agent,
    )
    return str(run.draft_id)


def pending_plant(admin_sdk, user_id: str, species_id: str) -> str:
    row = (
        admin_sdk.table("plants")
        .insert(
            {
                "user_id": user_id,
                "species_id": species_id,
                "status": PlantStatus.KNOWLEDGE_PENDING.value,
                "name": "צמח בהמתנה",
            }
        )
        .execute()
        .data[0]
    )
    return row["id"]


def plant_status(admin_sdk, plant_id: str) -> str:
    return admin_sdk.table("plants").select("status").eq("id", plant_id).execute().data[0]["status"]


# --- publication ---------------------------------------------------------------


def test_approving_publishes_version_one_and_marks_the_draft_approved(
    api, account, admin_sdk, species
):
    admin_id, admin_auth = account("ADMIN")
    draft_id = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))

    response = api.post(
        f"/v1/admin/knowledge-drafts/{draft_id}/approve", headers=admin_auth, json={}
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["version_number"] == 1

    version = (
        admin_sdk.table("knowledge_versions").select("*").eq("id", body["version_id"]).execute()
    ).data[0]
    assert version["is_current"] is True
    assert set(version["content"]) == set(SECTION_NAMES)

    draft = admin_sdk.table("knowledge_drafts").select("status").eq("id", draft_id).execute()
    assert draft.data[0]["status"] == KnowledgeDraftStatus.APPROVED.value


def test_a_second_publication_demotes_the_first_and_leaves_exactly_one_current(
    api, account, admin_sdk, species
):
    """The partial unique index permits one current row, so demote-then-insert is
    the only legal ordering — and a species with *no* current version would leave
    every plant of that species unable to find its knowledge."""
    admin_id, admin_auth = account("ADMIN")

    first = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))
    api.post(f"/v1/admin/knowledge-drafts/{first}/approve", headers=admin_auth, json={})

    second = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))
    response = api.post(f"/v1/admin/knowledge-drafts/{second}/approve", headers=admin_auth, json={})
    assert response.json()["data"]["version_number"] == 2

    versions = (
        admin_sdk.table("knowledge_versions")
        .select("version_number, is_current")
        .eq("species_id", species["id"])
        .execute()
    ).data
    assert len(versions) == 2
    assert [v["version_number"] for v in versions if v["is_current"]] == [2]


def test_a_published_version_cannot_be_edited_or_deleted(api, account, admin_sdk, species):
    """FINAL §29. The service role is used deliberately: if even that cannot
    change the text, no route can."""
    admin_id, admin_auth = account("ADMIN")
    draft_id = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))
    version_id = api.post(
        f"/v1/admin/knowledge-drafts/{draft_id}/approve", headers=admin_auth, json={}
    ).json()["data"]["version_id"]

    with pytest.raises(APIError):
        admin_sdk.table("knowledge_versions").update({"content": {"x": 1}}).eq(
            "id", version_id
        ).execute()

    with pytest.raises(APIError):
        admin_sdk.table("knowledge_versions").delete().eq("id", version_id).execute()


def test_only_a_reviewed_draft_can_be_published(api, account, admin_sdk, species, scripted):
    """FINAL §11: the Knowledge Agent never publishes.

    A draft still researching has content nobody has read, and approving it would
    make the review step decorative.
    """
    from app.orchestration.workflows import knowledge

    admin_id, admin_auth = account("ADMIN")
    run = knowledge.start_research(
        species_id=uuid.UUID(species["id"]), initiated_by=uuid.UUID(admin_id)
    )

    response = api.post(
        f"/v1/admin/knowledge-drafts/{run.draft_id}/approve", headers=admin_auth, json={}
    )
    assert response.status_code == 422

    assert (
        admin_sdk.table("knowledge_versions").select("id").eq("species_id", species["id"]).execute()
    ).data == []


# --- provenance ----------------------------------------------------------------


def test_sources_become_rows_carrying_the_class_python_decided(
    api, account, admin_sdk, species, monkeypatch
):
    admin_id, admin_auth = account("ADMIN")
    monkeypatch.setattr(verification, "fetch_page", lambda url: None)

    draft_id = researched_draft(
        admin_sdk,
        species["id"],
        uuid.UUID(admin_id),
        sources=[ProposedSource(url="https://example.invalid/made-up")],
    )
    version_id = api.post(
        f"/v1/admin/knowledge-drafts/{draft_id}/approve", headers=admin_auth, json={}
    ).json()["data"]["version_id"]

    sources = (
        admin_sdk.table("knowledge_sources")
        .select("*")
        .eq("knowledge_version_id", version_id)
        .execute()
    ).data
    assert len(sources) == 1
    assert sources[0]["source_class"] == "AI_GENERATED_REQUIRES_VERIFICATION"
    # The CHECK constraint permits a null URL only for this class, and forbids it
    # carrying an approved_source_id. Both hold because Python classified it, not
    # the model.
    assert sources[0]["url"] is None
    assert sources[0]["approved_source_id"] is None


# --- the fan-out (A4) ----------------------------------------------------------


def test_publishing_releases_every_pending_plant_of_that_species(api, account, admin_sdk, species):
    admin_id, admin_auth = account("ADMIN")
    owner_a, _ = account()
    owner_b, _ = account()

    plant_a = pending_plant(admin_sdk, owner_a, species["id"])
    plant_b = pending_plant(admin_sdk, owner_b, species["id"])

    draft_id = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))
    api.post(f"/v1/admin/knowledge-drafts/{draft_id}/approve", headers=admin_auth, json={})

    # Two different users' plants, released by one administrator's action. This is
    # why the RPC is SECURITY DEFINER: no admin JWT can write another user's plant
    # row through RLS, and it should not be able to in general.
    assert plant_status(admin_sdk, plant_a) == PlantStatus.ACTIVE.value
    assert plant_status(admin_sdk, plant_b) == PlantStatus.ACTIVE.value


def test_the_fan_out_leaves_archived_and_active_plants_alone(api, account, admin_sdk, species):
    """Restricted to KNOWLEDGE_PENDING on purpose.

    An archived plant must not be silently revived by an administrator publishing
    knowledge, and an already-active one (A21 re-identification) is working fine.
    """
    admin_id, admin_auth = account("ADMIN")
    owner, _ = account()

    archived = (
        admin_sdk.table("plants")
        .insert(
            {
                "user_id": owner,
                "species_id": species["id"],
                "status": "ARCHIVED",
                # A CHECK constraint keeps status and archived_at consistent, so an
                # archived plant with no timestamp is not a state the database allows.
                "archived_at": "2026-09-01T00:00:00Z",
                "name": "ארכיון",
            }
        )
        .execute()
        .data[0]["id"]
    )
    pending = pending_plant(admin_sdk, owner, species["id"])

    draft_id = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))
    api.post(f"/v1/admin/knowledge-drafts/{draft_id}/approve", headers=admin_auth, json={})

    assert plant_status(admin_sdk, archived) == "ARCHIVED"
    assert plant_status(admin_sdk, pending) == PlantStatus.ACTIVE.value


def test_a_plant_of_a_different_species_is_untouched(api, account, admin_sdk, species):
    admin_id, admin_auth = account("ADMIN")
    owner, _ = account()

    other = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name()})
        .execute()
        .data[0]
    )
    other_plant = pending_plant(admin_sdk, owner, other["id"])

    draft_id = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))
    api.post(f"/v1/admin/knowledge-drafts/{draft_id}/approve", headers=admin_auth, json={})

    assert plant_status(admin_sdk, other_plant) == PlantStatus.KNOWLEDGE_PENDING.value

    with contextlib.suppress(Exception):
        admin_sdk.table("plants").delete().eq("id", other_plant).execute()
        admin_sdk.table("species").delete().eq("id", other["id"]).execute()


# --- rejection (A17) -----------------------------------------------------------


def test_rejecting_leaves_plants_pending_and_the_species_retriable(
    api, account, admin_sdk, species, scripted
):
    """The failure the audit caught in the plan's first draft: A4 covered only
    success, so a rejected draft stranded every plant waiting on it."""
    from app.domain.rules.knowledge_lifecycle import is_retriable

    admin_id, admin_auth = account("ADMIN")
    owner, _ = account()
    plant = pending_plant(admin_sdk, owner, species["id"])

    draft_id = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))
    response = api.post(
        f"/v1/admin/knowledge-drafts/{draft_id}/reject",
        headers=admin_auth,
        json={"admin_note": "המידע על ההשקיה אינו מדויק."},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == KnowledgeDraftStatus.REJECTED.value
    assert plant_status(admin_sdk, plant) == PlantStatus.KNOWLEDGE_PENDING.value
    assert is_retriable(KnowledgeDraftStatus.REJECTED)

    # And the path out actually works: retry re-opens research on the same draft.
    scripted.queue(KnowledgeOutput(content=content()))
    retry = api.post(
        f"/v1/admin/knowledge-drafts/{draft_id}/retry",
        headers=admin_auth,
        json={"reason": "לתקן את סעיף ההשקיה"},
    )
    assert retry.status_code == 202

    draft = admin_sdk.table("knowledge_drafts").select("status").eq("id", draft_id).execute()
    assert draft.data[0]["status"] == KnowledgeDraftStatus.READY_FOR_REVIEW.value


def test_a_rejection_must_carry_a_reason(api, account, admin_sdk, species):
    admin_id, admin_auth = account("ADMIN")
    draft_id = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))

    response = api.post(
        f"/v1/admin/knowledge-drafts/{draft_id}/reject", headers=admin_auth, json={"admin_note": ""}
    )
    assert response.status_code == 422


# --- what a user may and may not do --------------------------------------------


ADMIN_ROUTES = [
    ("get", "/v1/admin/knowledge-drafts"),
    ("get", "/v1/admin/approved-sources"),
    ("post", "/v1/admin/approved-sources"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_a_regular_user_is_refused_every_admin_route(api, account, method: str, path: str):
    _, auth = account()
    kwargs = {"json": {}} if method == "post" else {}
    response = getattr(api, method)(path, headers=auth, **kwargs)
    assert response.status_code == 403


def test_a_user_cannot_read_a_draft_even_through_the_database(api, account, admin_sdk, species):
    """The dependency gives a clean 403; RLS is what makes a forgotten dependency
    a non-event. This asserts the second one."""
    from supabase import create_client

    admin_id, _ = account("ADMIN")
    researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))

    email = f"kread-{uuid.uuid4().hex[:10]}@example.com"
    reader = admin_sdk.auth.admin.create_user(
        {"email": email, "password": PASSWORD, "email_confirm": True}
    ).user
    try:
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        anon.auth.sign_in_with_password({"email": email, "password": PASSWORD})
        assert anon.table("knowledge_drafts").select("id").execute().data == []
    finally:
        with contextlib.suppress(Exception):
            admin_sdk.auth.admin.delete_user(reader.id)


def test_a_user_reads_published_knowledge_and_can_report_an_error(api, account, admin_sdk, species):
    admin_id, admin_auth = account("ADMIN")
    draft_id = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))
    api.post(f"/v1/admin/knowledge-drafts/{draft_id}/approve", headers=admin_auth, json={})

    _, user_auth = account()

    read = api.get(f"/v1/species/{species['id']}/knowledge", headers=user_auth)
    assert read.status_code == 200
    assert set(read.json()["data"]["content"]) == set(SECTION_NAMES)

    report = api.post(
        f"/v1/species/{species['id']}/knowledge-reports",
        headers=user_auth,
        json={"report_text": "נראה לי שההמלצה על ההשקיה שגויה."},
    )
    assert report.status_code == 201


def test_knowledge_is_not_found_before_anything_is_published(api, account, species):
    _, auth = account()
    response = api.get(f"/v1/species/{species['id']}/knowledge", headers=auth)
    assert response.status_code == 404


def test_a_user_cannot_write_knowledge(api, account, admin_sdk, species):
    """FINAL §10: users read and report; they never edit."""
    from supabase import create_client

    email = f"kwrite-{uuid.uuid4().hex[:10]}@example.com"
    user = admin_sdk.auth.admin.create_user(
        {"email": email, "password": PASSWORD, "email_confirm": True}
    ).user
    try:
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        anon.auth.sign_in_with_password({"email": email, "password": PASSWORD})

        with pytest.raises(APIError):
            anon.table("knowledge_versions").insert(
                {
                    "species_id": species["id"],
                    "version_number": 99,
                    "content": {"forged": True},
                    "is_current": True,
                }
            ).execute()
    finally:
        with contextlib.suppress(Exception):
            admin_sdk.auth.admin.delete_user(user.id)


# --- approved sources ----------------------------------------------------------


def test_an_admin_manages_the_approved_source_list(api, account, admin_sdk):
    _, admin_auth = account("ADMIN")
    domain = f"src-{uuid.uuid4().hex[:8]}.example.org"

    created = api.post(
        "/v1/admin/approved-sources",
        headers=admin_auth,
        # Pasted as a full URL, which is what an administrator actually has in
        # their clipboard; stored bare, which is what matching needs.
        json={
            "name": "Test Source",
            "domain": f"https://www.{domain}/plants/",
            "reliability_level": 4,
        },
    )
    assert created.status_code == 201
    source = created.json()["data"]
    assert source["domain"] == domain

    disabled = api.post(f"/v1/admin/approved-sources/{source['id']}/disable", headers=admin_auth)
    assert disabled.status_code == 200
    assert disabled.json()["data"]["is_enabled"] is False

    audit = (
        admin_sdk.table("admin_audit_log").select("action").eq("target_id", source["id"]).execute()
    ).data
    assert {row["action"] for row in audit} == {
        "approved_source.create",
        "approved_source.disable",
    }

    with contextlib.suppress(Exception):
        admin_sdk.table("approved_sources").delete().eq("id", source["id"]).execute()


def test_publication_writes_an_audit_entry(api, account, admin_sdk, species):
    """FINAL §29. Written inside the publishing transaction, so it cannot be lost
    separately from the action it describes."""
    admin_id, admin_auth = account("ADMIN")
    draft_id = researched_draft(admin_sdk, species["id"], uuid.UUID(admin_id))
    version_id = api.post(
        f"/v1/admin/knowledge-drafts/{draft_id}/approve", headers=admin_auth, json={}
    ).json()["data"]["version_id"]

    entry = (
        admin_sdk.table("admin_audit_log").select("*").eq("target_id", version_id).execute()
    ).data[0]
    assert entry["action"] == "knowledge.publish"
    assert entry["admin_user_id"] == admin_id
    assert entry["payload"]["version_number"] == 1
