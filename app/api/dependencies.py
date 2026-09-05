"""FastAPI dependencies for authentication and authorisation.

Ownership is derived from the JWT and nothing else. A client-supplied ``user_id``
or ``role`` in a body, query string or header is never consulted — API_CONTRACTS
is explicit about this, and `TESTING_STRATEGY §7` requires a test for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.api.rate_limit import ai_limiter
from app.common.enums import UserRole
from app.common.errors import AdminRequiredError, ForbiddenError, UnauthenticatedError
from app.config.settings import get_settings
from app.infrastructure.supabase.client import user_client
from app.infrastructure.supabase.jwt import user_id_from_claims, verify_access_token
from app.repositories.base import first_row
from supabase import Client


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller and a database client scoped to them."""

    id: UUID
    email: str | None
    access_token: str
    client: Client

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # Keeps the token out of tracebacks and logs.
        return f"CurrentUser(id={self.id})"


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
    """
    token = _bearer_token(request)
    claims = verify_access_token(token)
    user_id = user_id_from_claims(claims)

    return CurrentUser(
        id=user_id,
        email=claims.get("email"),
        access_token=token,
        client=user_client(token),
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
