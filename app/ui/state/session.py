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

Surviving a refresh
-------------------
`st.session_state` lives for one Streamlit session and a browser reload starts a
new one, so holding the session only there made F5 identical to signing out.
`restore()` rebuilds it from a refresh token kept in the browser - see
`app/ui/components/session_store.py` for what is stored and why only that.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import streamlit as st

from app.config.settings import get_settings
from app.ui.components import session_store as store
from supabase import create_client

_SESSION_KEY = "pc_auth_session"
# A refresh token waiting to be written to the browser. Held for a moment
# because `_store` is called from inside `sign_in`, which may run in a
# callback where mounting a component is not allowed.
_PENDING_WRITE = "pc_auth_pending_write"
_RESTORE_TRIED = "pc_auth_restore_tried"

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


def _store(session, *, persist: bool = True) -> AuthSession:
    stored = AuthSession(
        user_id=session.user.id,
        email=session.user.email or "",
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_at=datetime.fromtimestamp(session.expires_at, tz=UTC),
    )
    st.session_state[_SESSION_KEY] = stored
    if persist:
        # Every renewal rotates the refresh token, so the browser copy has to be
        # rewritten or the next reload would present a token Supabase has already
        # retired - which is a delayed version of the same logout.
        st.session_state[_PENDING_WRITE] = stored.refresh_token
    return stored


# --- surviving a browser refresh ------------------------------------------------


def restore() -> AuthSession | None:
    """Rebuild the session from the browser's cookie, if it has one to give.

    Called once per rerun from the entry point, before routing.

    Where the cookie arrives with the connection it is readable on the first run
    and there is no intermediate state at all. Where it does not - Community
    Cloud - the browser is asked directly and answers a rerun later, which is
    what `restoring()` covers: the caller waits rather than drawing a sign-in
    form it may be about to replace.

    A stored token that Supabase rejects is discarded rather than retried: it is
    revoked, expired, or from another deployment, and all three mean sign in
    again.
    """
    pending = st.session_state.pop(_PENDING_WRITE, None)
    if pending is not None:
        store.write(pending)

    if is_signed_in():
        return current()

    # Once per Streamlit session. A failed restore must not re-attempt on every
    # rerun: it is a network call, and it would fail the same way each time.
    if st.session_state.get(_RESTORE_TRIED):
        return None

    token = store.read()

    # The browser may not have answered yet. On hosts where the cookie does not
    # reach `st.context.cookies` - Community Cloud among them - the value arrives
    # from a component one rerun later, and treating that gap as "signed out"
    # would mark the attempt used and strand a signed-in user on the login form.
    if token is None and store.awaiting():
        return None

    st.session_state[_RESTORE_TRIED] = True
    if not token:
        return None

    try:
        restored = _client().auth.refresh_session(token)
    except Exception:
        store.clear()
        return None

    if not restored or not restored.session:
        store.clear()
        return None

    return _store(restored.session)


# --- public API ---------------------------------------------------------------


def current() -> AuthSession | None:
    return st.session_state.get(_SESSION_KEY)


def user_key() -> str:
    """Identity for anything keyed per user across sessions.

    `st.cache_data` is shared by every browser session this server handles, so a
    cached read keyed only on its path would serve one person's data to another.
    Anything cached is keyed on this.
    """
    current_session = current()
    return current_session.user_id if current_session else "anonymous"


def is_signed_in() -> bool:
    return current() is not None


def restoring() -> bool:
    """True while we are still waiting to hear whether the browser has a session.

    The caller must render something neutral and stop rather than draw the
    sign-in form: showing it to somebody who is in fact signed in is the bug this
    whole mechanism exists to prevent, and a flash of it is the same bug for a
    third of a second.
    """
    return not is_signed_in() and store.awaiting()


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
    st.session_state.pop(_PENDING_WRITE, None)
    # Marked as tried so the cookie - which the browser has not dropped yet, the
    # component runs on the *next* render - cannot immediately sign them back in.
    st.session_state[_RESTORE_TRIED] = True
    store.clear()
