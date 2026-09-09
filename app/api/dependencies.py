"""FastAPI dependencies for authentication and authorisation.

Ownership is derived from the JWT and nothing else. A client-supplied ``user_id``
or ``role`` in a body, query string or header is never consulted — API_CONTRACTS
is explicit about this, and `TESTING_STRATEGY §7` requires a test for it.

One deliberate exception, added for the admin "view as user" feature:
``X-Act-As-User`` names a user whose data an **administrator** wants to read. It is
not an exception to the rule above so much as an application of it - the header is
believed only after the caller's own role has been read from the database, so the
authority still comes from the verified token and never from the client's claim
about itself. The credential stays the admin's throughout, which is what keeps the
admin RLS policies (and only those) in force.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.api.rate_limit import ai_limiter
from app.common.enums import UserRole
from app.common.errors import (
    AdminRequiredError,
    ForbiddenError,
    NotFoundError,
    UnauthenticatedError,
    ValidationFailedError,
)
from app.config.settings import get_settings
from app.infrastructure.supabase.client import user_client
from app.infrastructure.supabase.jwt import user_id_from_claims, verify_access_token
from app.repositories.base import first_row
from supabase import Client

#: Names the user an administrator wants to look at. See the module docstring.
ACT_AS_HEADER = "X-Act-As-User"


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller and a database client scoped to them.

    Under "view as user" these come apart: `id` is the user being *looked at* and
    `client` still carries the *administrator's* credential. Every user-facing read
    filters on an owner id explicitly rather than trusting RLS to scope it - see the
    comment at `repositories/plants.py:89`, which exists for precisely this reason -
    so those reads return the target's rows and no one else's, while the admin's
    `_select_admin` policies are what permit them at all.
    """

    id: UUID
    email: str | None
    access_token: str
    client: Client
    #: The administrator looking, when this is a "view as user" request. `None` on
    #: every ordinary request, and the only way to tell the two apart downstream.
    impersonator_id: UUID | None = None

    @property
    def is_impersonated(self) -> bool:
        return self.impersonator_id is not None

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # Keeps the token out of tracebacks and logs.
        return f"CurrentUser(id={self.id}, impersonator_id={self.impersonator_id})"


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthenticatedError("Authorization header must be 'Bearer <token>'.")
    return token.strip()


async def get_current_user(request: Request) -> CurrentUser:
    """Verify the caller's token and build a client that acts as them.

    Deliberately does *not* load the profile row. Most requests never need the
    role, and paying for a query on every authenticated call to support the
    minority that do would be the wrong default; `require_admin` loads it.

    The one exception is an ``X-Act-As-User`` request, which cannot be answered
    without knowing whether the caller is an administrator. That read happens only
    when the header is present, so the ordinary path is unchanged.

    Note what impersonation does to the routes downstream: `get_current_role` reads
    the role of `user.id`, which is now the *target*, so `/v1/admin/*` is closed
    while acting as a user. That is the behaviour we want - an administrator looking
    at somebody's plants is not simultaneously an administrator - and it is why the
    client has to leave the mode before returning to the admin panel.
    """
    token = _bearer_token(request)
    claims = verify_access_token(token)
    user_id = user_id_from_claims(claims)
    client = user_client(token)

    requested = request.headers.get(ACT_AS_HEADER)
    if requested:
        return _acting_as(client, token, caller_id=user_id, requested=requested)

    return CurrentUser(
        id=user_id,
        email=claims.get("email"),
        access_token=token,
        client=client,
    )


def _acting_as(client: Client, token: str, *, caller_id: UUID, requested: str) -> CurrentUser:
    """Resolve an ``X-Act-As-User`` header, or refuse it.

    Refusing is the common case and the important one: a header that were silently
    ignored when the caller is not an administrator would turn a privilege bug into
    a screen that merely looks empty.

    The role is read here rather than taken from the token for the same reason
    `get_current_role` reads it: a role claim from the client is exactly the
    escalation `TESTING_STRATEGY §7` forbids. This costs one query, and only on a
    request that actually carries the header.
    """
    try:
        target_id = UUID(requested.strip())
    except ValueError:
        raise ValidationFailedError(f"{ACT_AS_HEADER} must be a user id.") from None

    # Acting as yourself is the ordinary request, not a special mode. Handled rather
    # than refused so a client that sets the header unconditionally still works.
    if target_id == caller_id:
        profile = first_row(
            client.table("profiles").select("email").eq("id", str(caller_id)).execute()
        )
        return CurrentUser(
            id=caller_id,
            email=(profile or {}).get("email"),
            access_token=token,
            client=client,
        )

    caller = first_row(
        client.table("profiles")
        .select("role, is_active, anonymized_at")
        .eq("id", str(caller_id))
        .execute()
    )
    if caller is None:
        raise UnauthenticatedError("No profile exists for this account.")
    if not caller.get("is_active", True) or caller.get("anonymized_at"):
        raise ForbiddenError("This account has been disabled.")
    if UserRole(str(caller["role"])) is not UserRole.ADMIN:
        raise AdminRequiredError()

    # Read through the administrator's own client, so `profiles_select_admin` is
    # what admits this row - the same policy the accounts list already relies on.
    target = first_row(
        client.table("profiles").select("id, email").eq("id", str(target_id)).execute()
    )
    if target is None:
        raise NotFoundError("החשבון לא נמצא.")

    return CurrentUser(
        id=target_id,
        email=target.get("email"),
        access_token=token,
        client=client,
        impersonator_id=caller_id,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def get_current_role(user: CurrentUserDep) -> UserRole:
    """Read the caller's role from the database, server-side.

    The role lives in ``profiles``, not in the token, and is read through the
    user's own client — so RLS applies and a caller can only ever read their own
    row. Trusting a role claim from the client would be exactly the escalation
    `TESTING_STRATEGY §7` forbids.
    """
    result = (
        user.client.table("profiles").select("role, is_active").eq("id", str(user.id)).execute()
    )
    row = first_row(result)
    if row is None:
        # The signup trigger creates this row, so its absence means a deleted or
        # never-provisioned account rather than a permissions problem.
        raise UnauthenticatedError("No profile exists for this account.")

    if not row.get("is_active", True):
        raise ForbiddenError("This account has been disabled.")

    return UserRole(str(row["role"]))


RoleDep = Annotated[UserRole, Depends(get_current_role)]


async def require_admin(user: CurrentUserDep, role: RoleDep) -> CurrentUser:
    """Gate an admin-only route.

    Belt and braces on top of RLS, not a replacement for it: every admin table
    also has an ``is_admin()`` policy, so a missing dependency here cannot by
    itself expose admin data.
    """
    if role is not UserRole.ADMIN:
        raise AdminRequiredError()
    return user


AdminDep = Annotated[CurrentUser, Depends(require_admin)]


async def enforce_ai_rate_limit(user: CurrentUserDep) -> None:
    """Gate an AI-triggering endpoint (API_CONTRACTS §Security, A14).

    Keyed on the verified user id rather than the client address: AI endpoints are
    authenticated, and keying on IP would punish everyone behind one NAT while
    letting a single user spread their spend across addresses.

    Runs after authentication by construction, since it depends on it - so an
    unauthenticated caller is refused before consuming any allowance.
    """
    settings = get_settings()
    ai_limiter.check(
        f"ai:{user.id}",
        rules=[
            (settings.ai_rate_limit_per_minute, 60),
            (settings.ai_rate_limit_per_hour, 3600),
        ],
    )


AIRateLimitDep = Annotated[None, Depends(enforce_ai_rate_limit)]
