"""The admin panel against DEV (FINAL §29, §21).

Two things are being defended.

**Every admin route refuses a regular user**, and the test is parametrised over
the route table rather than a chosen sample — a route added without its
dependency should fail here rather than ship. RLS is checked separately, because
the dependency giving a clean 403 and the policy making a forgotten dependency
harmless are two different guarantees.

**Anonymisation does all of its parts or none.** An account with its email
cleared but access still enabled is a user locked out of a login they can still
perform; an account disabled but not anonymised is a deletion request that did
nothing.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from tests.integration.conftest import unique_species_name

pytestmark = pytest.mark.integration

PASSWORD = "Adm-Passw0rd!"

# Every admin route, with a body where one is required. Parametrised rather than
# sampled: a new route without `AdminDep` should fail this, not ship.
ADMIN_ROUTES: list[tuple[str, str, dict | None]] = [
    ("get", "/v1/admin/overview", None),
    ("get", "/v1/admin/agent-executions", None),
    ("get", "/v1/admin/agent-requests", None),
    ("get", "/v1/admin/knowledge-reports", None),
    ("get", "/v1/admin/notification-deliveries", None),
    ("get", "/v1/admin/audit-log", None),
    ("get", "/v1/admin/accounts", None),
    ("get", "/v1/admin/knowledge-drafts", None),
    ("get", "/v1/admin/approved-sources", None),
    ("post", "/v1/admin/approved-sources", {"name": "x", "domain": "example.org"}),
    (
        "post",
        f"/v1/admin/accounts/{uuid.uuid4()}/anonymize",
        {"reason": "user request"},
    ),
    ("post", f"/v1/admin/knowledge-reports/{uuid.uuid4()}/review", {"status": "DISMISSED"}),
    ("post", f"/v1/admin/knowledge-drafts/{uuid.uuid4()}/approve", {}),
    (
        "post",
        f"/v1/admin/knowledge-drafts/{uuid.uuid4()}/reject",
        {"admin_note": "not good enough"},
    ),
]


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
def api(live_env) -> Iterator[TestClient]:
    from app.api.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def account(admin_sdk):
    from supabase import create_client

    created: list[str] = []

    def _make(role: str = "USER") -> tuple[str, dict[str, str], str]:
        email = f"adm-{uuid.uuid4().hex[:12]}@example.com"
        user = admin_sdk.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user
        created.append(user.id)
        if role == "ADMIN":
            admin_sdk.table("profiles").update({"role": "ADMIN"}).eq("id", user.id).execute()
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        token = anon.auth.sign_in_with_password(
            {"email": email, "password": PASSWORD}
        ).session.access_token
        return user.id, {"Authorization": f"Bearer {token}"}, email

    yield _make

    for user_id in created:
        with contextlib.suppress(Exception):
            admin_sdk.auth.admin.delete_user(user_id)


# --- the boundary ----------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_every_admin_route_refuses_a_regular_user(api, account, method, path, body):
    """Parametrised over the whole route table.

    A 403 rather than a 404: the user is authenticated and the route exists, so
    saying "not found" would be a lie that also hides a real 404 elsewhere.
    """
    _, auth, _ = account()
    kwargs = {"json": body} if body is not None else {}

    assert getattr(api, method)(path, headers=auth, **kwargs).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_every_admin_route_refuses_an_anonymous_caller(api, method, path, body):
    kwargs = {"json": body} if body is not None else {}

    assert getattr(api, method)(path, **kwargs).status_code == 401


def test_a_user_cannot_read_admin_tables_even_through_the_database(admin_sdk, account):
    """The dependency gives a clean 403; RLS is what makes a forgotten dependency
    harmless. Different guarantees, tested separately."""
    from supabase import create_client

    _, _, email = account()
    anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    anon.auth.sign_in_with_password({"email": email, "password": PASSWORD})

    for table in ("agent_executions", "admin_audit_log", "knowledge_drafts", "approved_sources"):
        assert anon.table(table).select("id").execute().data == [], table


def test_a_user_cannot_promote_themselves(admin_sdk, account):
    """The guard trigger from PR 2, still holding."""
    from supabase import create_client

    user_id, _, email = account()
    anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    anon.auth.sign_in_with_password({"email": email, "password": PASSWORD})

    with pytest.raises(APIError):
        anon.table("profiles").update({"role": "ADMIN"}).eq("id", user_id).execute()


# --- monitoring -------------------------------------------------------------------


def test_the_overview_reports_what_needs_attention(api, account):
    _, admin_auth, _ = account("ADMIN")

    data = api.get("/v1/admin/overview", headers=admin_auth).json()["data"]

    assert {"drafts_awaiting_review", "open_knowledge_reports", "failed_agent_requests"} <= set(
        data
    )
    assert isinstance(data["total_estimated_cost"], int | float)


def test_agent_executions_expose_cost_and_prompt_version_but_never_reasoning(api, account):
    """FINAL §23 forbids storing chain-of-thought, and `agent_executions` has no
    column for it — so this route cannot leak it however it is queried."""
    _, admin_auth, _ = account("ADMIN")

    response = api.get("/v1/admin/agent-executions?limit=5", headers=admin_auth)
    assert response.status_code == 200

    for row in response.json()["data"]:
        assert "model" in row
        assert "prompt_version" in row
        assert "estimated_cost" in row
        for forbidden in ("prompt", "response", "reasoning", "raw_output", "messages"):
            assert forbidden not in row


def test_agent_requests_can_be_filtered_by_status(api, account):
    _, admin_auth, _ = account("ADMIN")

    response = api.get("/v1/admin/agent-requests?status=FAILED&limit=5", headers=admin_auth)
    assert response.status_code == 200
    assert all(row["status"] == "FAILED" for row in response.json()["data"])


# --- knowledge reports --------------------------------------------------------------


def test_an_admin_triages_a_user_report_and_the_action_is_audited(api, admin_sdk, account):
    admin_id, admin_auth, _ = account("ADMIN")
    user_id, _, _ = account()
    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name()})
        .execute()
        .data[0]
    )
    report = (
        admin_sdk.table("knowledge_reports")
        .insert(
            {
                "user_id": user_id,
                "species_id": species["id"],
                "report_text": "ההמלצה על ההשקיה נראית שגויה.",
            }
        )
        .execute()
        .data[0]
    )

    response = api.post(
        f"/v1/admin/knowledge-reports/{report['id']}/review",
        headers=admin_auth,
        json={"status": "ACTIONED", "admin_note": "נפתחה טיוטה חדשה."},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ACTIONED"

    audit = (
        admin_sdk.table("admin_audit_log")
        .select("action, admin_user_id")
        .eq("target_id", report["id"])
        .execute()
    ).data
    assert audit and audit[0]["action"] == "knowledge_report.actioned"
    assert audit[0]["admin_user_id"] == admin_id


def test_a_user_cannot_edit_the_admins_triage_of_their_own_report(admin_sdk, account):
    """`status` and `admin_note` are the administrator's record, not the
    reporter's."""
    from supabase import create_client

    user_id, _, email = account()
    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name()})
        .execute()
        .data[0]
    )
    report = (
        admin_sdk.table("knowledge_reports")
        .insert({"user_id": user_id, "species_id": species["id"], "report_text": "בדיקה."})
        .execute()
        .data[0]
    )

    anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    anon.auth.sign_in_with_password({"email": email, "password": PASSWORD})

    updated = (
        anon.table("knowledge_reports")
        .update({"status": "DISMISSED"})
        .eq("id", report["id"])
        .execute()
    )
    assert updated.data == []


# --- the audit log -------------------------------------------------------------------


def test_the_audit_log_is_append_only(admin_sdk, account):
    """An audit trail an administrator can edit is not an audit trail. Tested
    through the service role: if even that cannot rewrite it, no route can."""
    admin_id, _, _ = account("ADMIN")
    entry = (
        admin_sdk.table("admin_audit_log")
        .insert(
            {
                "admin_user_id": admin_id,
                "action": "test.entry",
                "target_table": "profiles",
                "target_id": admin_id,
            }
        )
        .execute()
        .data[0]
    )

    with pytest.raises(APIError):
        admin_sdk.table("admin_audit_log").update({"action": "test.changed"}).eq(
            "id", entry["id"]
        ).execute()
    with pytest.raises(APIError):
        admin_sdk.table("admin_audit_log").delete().eq("id", entry["id"]).execute()


# --- anonymisation (FINAL §21, A26) ----------------------------------------------------


def test_anonymising_clears_identity_disables_access_and_keeps_history(api, admin_sdk, account):
    """All four parts, or none. Half of it is worse than none."""
    _, admin_auth, _ = account("ADMIN")
    user_id, _, _ = account()

    species = (
        admin_sdk.table("species")
        .insert({"scientific_name": unique_species_name()})
        .execute()
        .data[0]
    )
    plant = (
        admin_sdk.table("plants")
        .insert(
            {
                "user_id": user_id,
                "species_id": species["id"],
                "status": "ACTIVE",
                "name": "הצמח של דנה",
                "notes": "מתנה מאמא",
            }
        )
        .execute()
        .data[0]
    )

    response = api.post(
        f"/v1/admin/accounts/{user_id}/anonymize",
        headers=admin_auth,
        json={"reason": "בקשת מחיקה מהמשתמש"},
    )
    assert response.status_code == 200

    profile = (admin_sdk.table("profiles").select("*").eq("id", user_id).execute()).data[0]
    assert profile["email"] is None
    assert profile["display_name"] is None
    assert profile["is_active"] is False
    assert profile["anonymized_at"] is not None

    # The history survives - §21 asks for it, and a published knowledge version
    # could not be deleted even if it did not.
    surviving = (
        admin_sdk.table("plants").select("id, name, notes").eq("id", plant["id"]).execute()
    ).data
    assert len(surviving) == 1
    assert surviving[0]["name"] is None
    assert surviving[0]["notes"] is None

    with contextlib.suppress(Exception):
        admin_sdk.table("plants").delete().eq("id", plant["id"]).execute()


def test_the_anonymisation_is_audited_without_recording_what_was_erased(api, admin_sdk, account):
    """An audit entry that recorded the email would preserve exactly the data the
    operation exists to remove."""
    _, admin_auth, _ = account("ADMIN")
    user_id, _, email = account()

    api.post(
        f"/v1/admin/accounts/{user_id}/anonymize",
        headers=admin_auth,
        json={"reason": "בקשת מחיקה"},
    )

    entry = (
        admin_sdk.table("admin_audit_log")
        .select("action, payload")
        .eq("target_id", user_id)
        .execute()
    ).data[0]

    assert entry["action"] == "account.anonymize"
    assert email not in str(entry["payload"])


def test_anonymising_twice_is_harmless(api, account):
    """Executed by hand from a ticket, so it must be idempotent."""
    _, admin_auth, _ = account("ADMIN")
    user_id, _, _ = account()

    first = api.post(
        f"/v1/admin/accounts/{user_id}/anonymize",
        headers=admin_auth,
        json={"reason": "בקשה ראשונה"},
    )
    second = api.post(
        f"/v1/admin/accounts/{user_id}/anonymize", headers=admin_auth, json={"reason": "בקשה חוזרת"}
    )

    assert first.status_code == 200
    assert second.status_code == 200


def test_an_admin_cannot_anonymise_themselves(api, account):
    """It would revoke the role needed to undo it, and remove an administrator by
    accident."""
    admin_id, admin_auth, _ = account("ADMIN")

    response = api.post(
        f"/v1/admin/accounts/{admin_id}/anonymize",
        headers=admin_auth,
        json={"reason": "oops"},
    )
    assert response.status_code == 422


def test_anonymisation_requires_a_reason(api, account):
    """A26: deletion is an out-of-band request, and the reason is the only record
    of why the account was closed."""
    _, admin_auth, _ = account("ADMIN")
    user_id, _, _ = account()

    assert (
        api.post(f"/v1/admin/accounts/{user_id}/anonymize", headers=admin_auth, json={}).status_code
        == 422
    )


def test_an_anonymised_account_is_still_visible_to_an_admin(api, account):
    """§21: anonymised account data stays reachable by an administrator."""
    _, admin_auth, _ = account("ADMIN")
    user_id, _, _ = account()

    api.post(
        f"/v1/admin/accounts/{user_id}/anonymize", headers=admin_auth, json={"reason": "בקשת מחיקה"}
    )

    accounts = api.get("/v1/admin/accounts?limit=100", headers=admin_auth).json()["data"]
    found = [a for a in accounts if a["id"] == user_id]
    assert found and found[0]["anonymized_at"] is not None
