"""Access-token verification.

These use a real ES256 keypair and a stubbed JWKS, so the signature check is
genuinely exercised rather than mocked away. The distinction matters: a decoded
but unverified JWT is attacker-controlled data, and every test below is really
asking "can a caller forge an identity?"
"""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.common.errors import UnauthenticatedError
from app.infrastructure.supabase import jwt as jwt_module


@pytest.fixture
def keypair():
    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key()


@pytest.fixture
def attacker_keypair():
    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key()


@pytest.fixture
def issue(keypair, monkeypatch):
    """Issue a token signed by the "real" key, with the JWKS stubbed to match."""
    private, public = keypair

    class _StubKey:
        key = public

    class _StubJWKS:
        def get_signing_key_from_jwt(self, token: str):
            return _StubKey()

    monkeypatch.setattr(jwt_module, "_get_jwks_client", lambda: _StubJWKS())

    def _issue(private_key=None, **overrides):
        now = int(time.time())
        claims = {
            "sub": str(uuid.uuid4()),
            "aud": "authenticated",
            "role": "authenticated",
            "email": "user@example.com",
            "iat": now,
            "exp": now + 3600,
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key or private, algorithm="ES256"), claims

    return _issue


def test_valid_token_is_accepted(issue, env):
    token, claims = issue()

    verified = jwt_module.verify_access_token(token)

    assert verified["sub"] == claims["sub"]
    assert verified["email"] == "user@example.com"


def test_expired_token_is_rejected(issue, env):
    """Comfortably beyond the clock-skew leeway, which is 60 seconds."""
    token, _ = issue(exp=int(time.time()) - 3600)

    with pytest.raises(UnauthenticatedError, match="expired"):
        jwt_module.verify_access_token(token)


def test_token_signed_by_another_key_is_rejected(issue, attacker_keypair, env):
    """The core forgery case: right shape, right claims, wrong signature."""
    attacker_private, _ = attacker_keypair
    token, _ = issue(private_key=attacker_private)

    with pytest.raises(UnauthenticatedError):
        jwt_module.verify_access_token(token)


def test_token_for_another_audience_is_rejected(issue, env):
    token, _ = issue(aud="some-other-service")

    with pytest.raises(UnauthenticatedError):
        jwt_module.verify_access_token(token)


def test_token_without_a_subject_is_rejected(issue, env):
    token, _ = issue(sub=None)

    with pytest.raises(UnauthenticatedError):
        jwt_module.verify_access_token(token)


@pytest.mark.parametrize("token", ["", "not-a-token", "a.b", "a.b.c.d", "....", "Bearer something"])
def test_malformed_tokens_are_rejected(token: str, env):
    with pytest.raises(UnauthenticatedError):
        jwt_module.verify_access_token(token)


def test_unsigned_token_is_rejected(env, monkeypatch):
    """alg=none is the classic JWT bypass; it must not be honoured."""
    token = jwt.encode({"sub": str(uuid.uuid4()), "aud": "authenticated"}, key="", algorithm="none")

    with pytest.raises(UnauthenticatedError):
        jwt_module.verify_access_token(token)


def test_hs256_token_is_rejected_without_a_configured_secret(env):
    """This project uses asymmetric keys. An HS256 token can only be honoured if a
    shared secret is configured, and none is - so it must not be trusted."""
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "authenticated", "exp": int(time.time()) + 60},
        key="guessable",
        algorithm="HS256",
    )

    with pytest.raises(UnauthenticatedError):
        jwt_module.verify_access_token(token)


def test_user_id_is_parsed_from_claims():
    user_id = uuid.uuid4()
    assert jwt_module.user_id_from_claims({"sub": str(user_id)}) == user_id


@pytest.mark.parametrize("value", ["not-a-uuid", "", "12345"])
def test_non_uuid_subject_is_rejected(value: str):
    with pytest.raises(UnauthenticatedError):
        jwt_module.user_id_from_claims({"sub": value})


def test_jwks_url_is_derived_from_the_project(env):
    jwt_module.reset_jwks_cache()
    assert jwt_module._jwks_url().endswith("/auth/v1/.well-known/jwks.json")
    assert jwt_module._jwks_url().startswith("https://")


def test_clock_skew_leeway_accepts_a_slightly_future_token(issue, env):
    """Regression test for a real failure found against DEV.

    Without leeway, a token issued seconds ago is rejected with
    ImmatureSignatureError whenever this process's clock trails the auth server's.
    That surfaces as intermittent 401s for valid sessions on a machine whose clock
    looks fine, which is a miserable thing to debug in production.
    """
    token, _ = issue(iat=int(time.time()) + 30, nbf=int(time.time()) + 30)

    claims = jwt_module.verify_access_token(token)

    assert claims["sub"]


def test_skew_beyond_the_leeway_is_still_rejected(issue, env):
    """The leeway absorbs drift; it must not become an open door."""
    token, _ = issue(iat=int(time.time()) + 600, nbf=int(time.time()) + 600)

    with pytest.raises(UnauthenticatedError, match="not yet valid"):
        jwt_module.verify_access_token(token)
