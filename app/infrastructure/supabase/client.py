"""Supabase client construction.

Three clients, with deliberately different reach:

* :func:`anon_client` — the public anon key, no user. Auth flows only.
* :func:`user_client` — the anon key plus the caller's access token. **This is the
  default for everything user-facing**: PostgREST forwards the token, Postgres
  resolves ``auth.uid()``, and RLS applies as that user. Verified by spike and by
  ``tests/integration/test_auth_api.py``.
* :func:`service_client` — the service-role key, which **bypasses RLS entirely**.

The plan reserves the service role for a closed list of system writes:
``agent_executions``, ``agent_requests`` status transitions, ``system_events``,
knowledge publication, notification sends, and ``/v1/internal/tick``. Reaching for
it anywhere else means RLS has stopped being the security boundary, which
FINAL §26 forbids — so it is never the convenient default, and never reachable
from a request handler without an explicit dependency.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, ClientOptions, create_client

from app.config.settings import get_settings

# PostgREST's own default is 5s, which is tight for the dashboard aggregate.
_POSTGREST_TIMEOUT_SECONDS = 20


def _options(**kwargs) -> ClientOptions:
    return ClientOptions(postgrest_client_timeout=_POSTGREST_TIMEOUT_SECONDS, **kwargs)


@lru_cache(maxsize=1)
def anon_client() -> Client:
    """Public client with no user context. Used for sign-up, sign-in and reset."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key, options=_options())


def user_client(access_token: str) -> Client:
    """A client that acts as the caller, with RLS applied.

    Built per request rather than cached: the token identifies the user, so a
    shared instance would leak one user's authority to another.
    """
    settings = get_settings()
    client = create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options=_options(headers={"Authorization": f"Bearer {access_token}"}),
    )
    # Belt and braces: the header covers PostgREST, this covers the storage and
    # functions sub-clients, which read the session separately.
    client.postgrest.auth(access_token)
    return client


@lru_cache(maxsize=1)
def service_client() -> Client:
    """Server-side client that bypasses RLS.

    Never construct this in a request handler without a written reason. It must
    never reach the Streamlit process (SETUP §5: service-role credentials are
    server-side only).
    """
    settings = get_settings()
    return create_client(
        settings.supabase_url, settings.supabase_service_role_key, options=_options()
    )


def reset_clients() -> None:
    """Drop cached clients. For tests that change configuration."""
    anon_client.cache_clear()
    service_client.cache_clear()
