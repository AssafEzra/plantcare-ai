"""Access-token verification.

The token is verified locally against Supabase's published JWKS rather than by
calling ``auth.get_user()`` on every request, which would add a network round
trip to each authenticated call.

What matters here is that verification is *cryptographic*, not structural. A
decoded-but-unverified JWT is attacker-controlled data: anyone can mint one
claiming ``sub`` of another user. `TESTING_STRATEGY §7` requires that a
client-supplied identity cannot override the authenticated one, and this module
is where that is actually enforced.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from uuid import UUID

import httpx
import jwt
from jwt import PyJWKClient

from app.common.errors import UnauthenticatedError
from app.config.settings import get_settings

# Supabase rotates signing keys rarely; an hour keeps the JWKS fetch off the hot
# path without pinning a revoked key for long.
_JWKS_CACHE_SECONDS = 3600

# Tolerance for clock skew between this process and Supabase's auth server.
#
# Not theoretical: without it, a token issued moments ago is rejected with
# ImmatureSignatureError ("not yet valid") whenever the local clock runs even
# slightly behind the issuer's. That produces intermittent 401s for perfectly
# valid sessions, on a machine whose clock looks fine. Sixty seconds absorbs
# ordinary NTP drift while extending an expired token's life by no more than a
# minute, which is the usual trade and what RFC 7519 contemplates by allowing
# "some small leeway".
_CLOCK_SKEW_LEEWAY_SECONDS = 60

_lock = threading.Lock()
_jwks_client: PyJWKClient | None = None
_jwks_fetched_at: float = 0.0


def _jwks_url() -> str:
    return f"{get_settings().supabase_url}/auth/v1/.well-known/jwks.json"


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client, _jwks_fetched_at
    with _lock:
        expired = (time.monotonic() - _jwks_fetched_at) > _JWKS_CACHE_SECONDS
        if _jwks_client is None or expired:
            _jwks_client = PyJWKClient(_jwks_url(), cache_keys=True, lifespan=_JWKS_CACHE_SECONDS)
            _jwks_fetched_at = time.monotonic()
        return _jwks_client


def reset_jwks_cache() -> None:
    """For tests, and for a forced refresh after key rotation."""
    global _jwks_client, _jwks_fetched_at
    with _lock:
        _jwks_client = None
        _jwks_fetched_at = 0.0


def _decode_symmetric(token: str) -> dict[str, Any]:
    """Fallback for projects still issuing HS256 tokens signed with the JWT secret.

    Supabase moved to asymmetric ES256 keys with a JWKS endpoint; older projects
    (and some local stacks) still use HS256. Supporting both keeps the API working
    across environments without weakening either path — the signature is still
    verified, just with a different key type.
    """
    settings = get_settings()
    secret = getattr(settings, "supabase_jwt_secret", None)
    if not secret:
        raise UnauthenticatedError("Token could not be verified.")
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience="authenticated",
        leeway=_CLOCK_SKEW_LEEWAY_SECONDS,
        options={"require": ["exp", "sub"]},
    )


def verify_access_token(token: str) -> dict[str, Any]:
    """Return the verified claims, or raise :class:`UnauthenticatedError`.

    Never returns unverified claims. Every failure path raises, so a caller cannot
    accidentally proceed with an unchecked token.
    """
    if not token or token.count(".") != 2:
        raise UnauthenticatedError("Malformed access token.")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise UnauthenticatedError("Malformed access token.") from exc

    algorithm = header.get("alg", "")

    try:
        if algorithm.startswith(("ES", "RS")):
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience="authenticated",
                leeway=_CLOCK_SKEW_LEEWAY_SECONDS,
                options={"require": ["exp", "sub"]},
            )
        elif algorithm == "HS256":
            claims = _decode_symmetric(token)
        else:
            raise UnauthenticatedError("Unsupported token algorithm.")
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("Session has expired. Please sign in again.") from exc
    except jwt.ImmatureSignatureError as exc:
        # Skew beyond the leeway above. Distinguished from a generic failure so the
        # logs point at the clock rather than at the token.
        raise UnauthenticatedError(
            "Token is not yet valid; the server clock may be out of sync."
        ) from exc
    except jwt.InvalidAudienceError as exc:
        raise UnauthenticatedError("Token was not issued for this application.") from exc
    except (jwt.PyJWTError, httpx.HTTPError) as exc:
        raise UnauthenticatedError("Token could not be verified.") from exc

    if not claims.get("sub"):
        raise UnauthenticatedError("Token carries no subject.")

    return claims


def user_id_from_claims(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError) as exc:
        raise UnauthenticatedError("Token subject is not a valid user id.") from exc
