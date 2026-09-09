"""The admin "view as user" mode, at the layers that need no database.

An administrator can open an account and read it as its owner does. Three things make
that safe, and two of them are tested here (the third — that the reads return exactly
one user's rows — needs real RLS and lives in
`tests/integration/test_view_as_user.py`):

* the header is believed only after the caller's role is read from the database, so
  a normal user sending it is refused rather than quietly served their own data;
* the mode cannot write. Every non-GET carrying the header is refused before it
  reaches a route.

The second is enforced in middleware rather than per route on purpose: a rule each
route has to remember is a rule that will be forgotten by the next route added.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.api.dependencies import ACT_AS_HEADER, CurrentUser, get_current_user

probe = APIRouter()

TARGET = uuid.uuid4()


@probe.get("/v1/_probe/read")
async def read_probe() -> dict[str, str]:
    return {"ok": "true"}


@probe.post("/v1/_probe/write")
async def write_probe() -> dict[str, str]:  # pragma: no cover - must never be reached
    return {"ok": "true"}


@probe.patch("/v1/_probe/write")
async def patch_probe() -> dict[str, str]:  # pragma: no cover - must never be reached
    return {"ok": "true"}


@probe.delete("/v1/_probe/write")
async def delete_probe() -> dict[str, str]:  # pragma: no cover - must never be reached
    return {"ok": "true"}


@pytest.fixture
def client(env):
    from app.api.main import create_app

    app = create_app()
    app.include_router(probe)

    stub = CurrentUser(id=uuid.uuid4(), email="admin@example.com", access_token="x", client=None)
    app.dependency_overrides[get_current_user] = lambda: stub

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


ACTING = {ACT_AS_HEADER: str(TARGET)}


def test_a_read_is_allowed_while_acting_as_a_user(client):
    assert client.get("/v1/_probe/read", headers=ACTING).status_code == 200


@pytest.mark.parametrize("method", ["post", "patch", "delete"])
def test_every_write_verb_is_refused_while_acting_as_a_user(client, method):
    """The whole safety property. Postgres would refuse these anyway - every write
    policy is `*_own` - but as an opaque PostgREST failure, and a rule that merely
    happens to fail is not a rule."""
    response = getattr(client, method)("/v1/_probe/write", headers=ACTING)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_a_refusal_still_carries_a_request_id(client):
    """The middleware runs inside `request_context`, so its response is logged and
    correlatable like any other. Registered afterwards precisely for this."""
    response = client.post("/v1/_probe/write", headers=ACTING)

    assert response.headers.get("X-Request-ID")
    assert response.json()["request_id"]


def test_without_the_header_writes_are_untouched(client):
    """The guard must key on the header, not on being an admin: this is the ordinary
    request path and it has to stay exactly as it was."""
    assert client.post("/v1/_probe/write").status_code == 200


# --- who may send it -----------------------------------------------------------


class Table:
    """Just enough postgrest to answer the two profile reads `_acting_as` makes."""

    def __init__(self, rows: list[dict] | None):
        self._rows = rows

    def select(self, *_a, **_k) -> Table:
        return self

    def eq(self, *_a, **_k) -> Table:
        return self

    def execute(self):
        return type("R", (), {"data": self._rows or []})()


def resolve(caller: dict | None, target: dict | None, *, requested: str, caller_id: uuid.UUID):
    """Call `_acting_as` with scripted profile reads, in the order it makes them."""
    from app.api import dependencies

    answers = [caller, target]

    class ScriptedTable(Table):
        def __init__(self):
            row = answers.pop(0)
            super().__init__([row] if row else [])

    class ScriptedClient:
        def table(self, _name: str):
            return ScriptedTable()

    return dependencies._acting_as(
        ScriptedClient(), "token", caller_id=caller_id, requested=requested
    )


ADMIN = {"role": "ADMIN", "is_active": True, "anonymized_at": None}
USER = {"role": "USER", "is_active": True, "anonymized_at": None}


def test_an_admin_becomes_the_target_while_keeping_their_own_credential(env):
    """The trick the whole feature rests on: the identity is the target, the token
    stays the admin's. That is what puts the `_select_admin` policies in force while
    the owner filters confine the rows."""
    admin_id = uuid.uuid4()

    result = resolve(
        ADMIN,
        {"id": str(TARGET), "email": "owner@example.com"},
        requested=str(TARGET),
        caller_id=admin_id,
    )

    assert result.id == TARGET
    assert result.email == "owner@example.com"
    assert result.access_token == "token"
    assert result.impersonator_id == admin_id
    assert result.is_impersonated


def test_a_normal_user_sending_the_header_is_refused(env):
    """Refused, never quietly ignored. A header that were dropped silently would turn
    a privilege bug into a screen that merely looks empty."""
    from app.common.errors import AdminRequiredError

    with pytest.raises(AdminRequiredError):
        resolve(USER, None, requested=str(TARGET), caller_id=uuid.uuid4())


def test_a_disabled_admin_may_not_act_as_anyone(env):
    """Same rule `is_admin()` applies in the database: an admin must be active and
    not anonymised. A closed account keeps no privileges."""
    from app.common.errors import ForbiddenError

    with pytest.raises(ForbiddenError):
        resolve(
            {"role": "ADMIN", "is_active": False, "anonymized_at": None},
            None,
            requested=str(TARGET),
            caller_id=uuid.uuid4(),
        )


def test_a_malformed_header_is_a_validation_error(env):
    from app.common.errors import ValidationFailedError

    with pytest.raises(ValidationFailedError):
        resolve(ADMIN, None, requested="not-a-uuid", caller_id=uuid.uuid4())


def test_an_unknown_target_is_not_found(env):
    from app.common.errors import NotFoundError

    with pytest.raises(NotFoundError):
        resolve(ADMIN, None, requested=str(TARGET), caller_id=uuid.uuid4())


def test_acting_as_yourself_is_an_ordinary_request(env):
    """Handled rather than refused, so a client that sets the header unconditionally
    still works - and it must not report itself as impersonation."""
    me = uuid.uuid4()

    result = resolve({"email": "me@example.com"}, None, requested=str(me), caller_id=me)

    assert result.id == me
    assert result.impersonator_id is None
    assert not result.is_impersonated
