"""Authentication state for the Streamlit process.

Auth is the one thing the UI does directly against Supabase rather than through
the API. That is deliberate and consistent with PROJECT_STRUCTURE §7: signing in
is not a business operation, it is how the caller obtains the credential the API
then requires. Everything else — plants, care, health — goes through FastAPI.

The **anon** key is used here and only here. The service-role key must never
reach this process (SETUP §5).

Token refresh
-------------
Sessions expire after an hour. Without renewal the app would simply start
returning 401s mid-session, which reads to a user as the app breaking rather than
as a session ending. `access_token()` refreshes shortly before expiry, so callers
never have to think about it.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import streamlit as st

from app.config.settings import get_settings
from supabase import create_client

_SESSION_KEY = "pc_auth_session"

# Refresh this far ahead of expiry, so a request never leaves with a token that
# expires while it is in flight.
_REFRESH_MARGIN = timedelta(minutes=5)


@dataclass
class AuthSession:
    user_id: str
    email: str
    access_token: str
    refresh_token: str
    expires_at: datetime

    @property
    def needs_refresh(self) -> bool:
        return datetime.now(UTC) >= (self.expires_at - _REFRESH_MARGIN)


def _client():
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)


def _store(session) -> AuthSession:
    stored = AuthSession(
        user_id=session.user.id,
        email=session.user.email or "",
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_at=datetime.fromtimestamp(session.expires_at, tz=UTC),
    )
    st.session_state[_SESSION_KEY] = stored
    return stored


# --- public API ---------------------------------------------------------------


def current() -> AuthSession | None:
    return st.session_state.get(_SESSION_KEY)


def is_signed_in() -> bool:
    return current() is not None


def access_token() -> str | None:
    """A valid access token, refreshing first if it is close to expiring."""
    session = current()
    if session is None:
        return None

    if session.needs_refresh:
        try:
            refreshed = _client().auth.refresh_session(session.refresh_token)
            if refreshed and refreshed.session:
                session = _store(refreshed.session)
            else:
                sign_out()
                return None
        except Exception:
            # A refresh token can be revoked or simply too old. Treat any failure
            # as "signed out" rather than leaving a half-valid session behind.
            sign_out()
            return None

    return session.access_token


def sign_in(email: str, password: str) -> AuthSession:
    result = _client().auth.sign_in_with_password({"email": email, "password": password})
    if not result.session:
        raise RuntimeError("sign-in returned no session")
    return _store(result.session)


def sign_up(email: str, password: str, display_name: str | None = None) -> bool:
    """Register an account. Returns True when email confirmation is required.

    Confirmation is on (FINAL §22), so sign-up normally yields a user with no
    session; the caller must tell the user to check their inbox rather than
    assume they are signed in.
    """
    options = {"data": {"display_name": display_name}} if display_name else {}
    result = _client().auth.sign_up({"email": email, "password": password, "options": options})
    if result.session:
        _store(result.session)
        return False
    return True


def send_password_reset(email: str) -> None:
    _client().auth.reset_password_for_email(email)


def sign_out() -> None:
    session = current()
    if session is not None:
        # A failed remote sign-out must not strand the user in a signed-in UI;
        # clearing local state is what actually matters.
        with contextlib.suppress(Exception):
            _client().auth.sign_out()
    st.session_state.pop(_SESSION_KEY, None)
