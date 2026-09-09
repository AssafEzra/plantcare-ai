"""The UI's only route to application data: the FastAPI backend.

PROJECT_STRUCTURE §7 forbids the UI from holding business logic, running SQL, or
calling Supabase for business operations. This module is the seam that keeps that
true — every page asks the API, and none of them know the database exists.

Errors arrive as the API_CONTRACTS envelope and are translated here into Hebrew
the user can act on. Pages therefore never format an error themselves, and an
unrecognised code degrades to a general message rather than leaking an English
internal string into a Hebrew interface.
"""

from __future__ import annotations

from typing import Any

import httpx
import streamlit as st

from app.config.settings import get_settings
from app.ui.state import session

_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0)


@st.cache_resource(show_spinner=False)
def _client() -> httpx.Client:
    """One connection pool for the whole process.

    Every call used to open its own `httpx.Client` and close it again, so a single
    rerun of the plant page - five requests - built and tore down five TCP
    connections. Measured at 5.7s of API time per rerun, of which the setup is
    pure overhead.

    Cached as a resource rather than a module global so Streamlit owns its
    lifetime and it survives a rerun without being rebuilt. It carries no
    credentials: the token is attached per request by `_headers`, because a client
    holding one user's Authorization header would be shared with every session on
    this server.
    """
    return httpx.Client(timeout=_TIMEOUT)


# Hebrew for the codes a user can actually encounter. Anything unmapped falls
# back to the generic message: an English code in a Hebrew UI is worse than a
# vague sentence the user can act on.
_MESSAGES: dict[str, str] = {
    "UNAUTHENTICATED": "פג תוקף החיבור. יש להתחבר מחדש.",
    "FORBIDDEN": "אין לך הרשאה לפעולה הזו.",
    "ADMIN_REQUIRED": "האזור הזה מיועד למנהלי מערכת בלבד.",
    "NOT_FOUND": "לא מצאנו את מה שחיפשת.",
    "PLANT_NOT_FOUND": "הצמח לא נמצא.",
    "VALIDATION_FAILED": "חלק מהפרטים אינם תקינים. אנא בדקו ונסו שוב.",
    "INVALID_TRANSITION": "לא ניתן לבצע את השינוי הזה במצב הנוכחי.",
    "IMAGE_INVALID": "לא הצלחנו לקרוא את התמונה. נסו קובץ אחר.",
    "PAYLOAD_TOO_LARGE": "הקובץ גדול מדי. הגודל המרבי הוא 10MB.",
    "DUPLICATE_ACTION": "הפעולה כבר נרשמה.",
    "RATE_LIMITED": "ביצעת יותר מדי בקשות. נסו שוב בעוד רגע.",
    "AGENT_FAILED": "הניתוח לא הושלם. אפשר לנסות שוב.",
    "AGENT_SCHEMA_INVALID": "הניתוח לא הושלם. אפשר לנסות שוב.",
    "AGENT_TIMEOUT": "הניתוח נמשך זמן רב מדי. אפשר לנסות שוב.",
    "UPSTREAM_UNAVAILABLE": "שירות חיצוני אינו זמין כרגע.",
    "CONFIGURATION_ERROR": "יש תקלה בהגדרות המערכת.",
}

_GENERIC = "משהו השתבש. אפשר לנסות שוב."
_OFFLINE = "לא הצלחנו להתחבר לשרת. בדקו את החיבור ונסו שוב."


class ApiError(Exception):
    """A failed API call, already translated for display."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}
        self.request_id = request_id

    @property
    def is_auth_error(self) -> bool:
        return self.code == "UNAUTHENTICATED" or self.status == 401


#: Session-state key holding the user an administrator is currently looking at.
#: Read here rather than passed per call because every request must carry the header
#: for the mode to be coherent - a page that forgot it would show the admin their own
#: empty account mixed into somebody else's session.
ACT_AS_KEY = "pc_act_as"


def acting_as() -> str | None:
    """The user id being viewed, if the "view as user" mode is active."""
    try:
        return st.session_state.get(ACT_AS_KEY)
    except Exception:  # pragma: no cover - no script run context (tests, threads)
        return None


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = session.access_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # One place, so no caller can forget it. The API refuses any non-GET carrying
    # this header, so the mode cannot write even if a screen offers a button.
    target = acting_as()
    if target:
        headers["X-Act-As-User"] = str(target)
    return headers


def _translate(payload: dict[str, Any], status: int) -> ApiError:
    error = payload.get("error") or {}
    code = str(error.get("code") or "INTERNAL_ERROR")
    return ApiError(
        code=code,
        message=_MESSAGES.get(code, _GENERIC),
        status=status,
        details=error.get("details") or {},
        request_id=payload.get("request_id"),
    )


def request(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    files: Any = None,
) -> Any:
    """Call the API and return the envelope's `data`, or raise :class:`ApiError`."""
    url = f"{get_settings().api_base_url.rstrip('/')}{path}"

    try:
        response = _client().request(
            method, url, json=json, params=params, files=files, headers=_headers()
        )
    except httpx.RequestError as exc:
        # A transport failure is not the API's error envelope, so it needs its
        # own message: "the server is unreachable" is actionable, "something went
        # wrong" is not.
        raise ApiError("NETWORK_ERROR", _OFFLINE) from exc

    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            raise ApiError("INTERNAL_ERROR", _GENERIC, status=response.status_code) from None
        raise _translate(payload, response.status_code)

    if not response.content:
        return None
    return response.json().get("data")


def get(path: str, **kwargs: Any) -> Any:
    return request("GET", path, **kwargs)


# How long a cached read stays good. Streamlit re-runs the whole script on every
# interaction, so opening and closing a dialog - which changes nothing on the
# server - re-fetched the entire plant page twice.
#
# Five minutes, raised from 15s at the user's request. The TTL is not the only
# thing that expires a read: every write goes through `clear_cache`, so anything
# this session does is visible immediately. What the TTL bounds is staleness from
# a change made *elsewhere* - a second tab, another device, or the scheduler
# materialising a task on its own timer - which can now be up to five minutes old.
_CACHE_TTL_SECONDS = 300


@st.cache_data(ttl=_CACHE_TTL_SECONDS, show_spinner=False)
def _cached(user_key: str, path: str, params: tuple[tuple[str, Any], ...] | None) -> Any:
    # Through `get`, not `request`, so that a test which replaces `get` on this
    # module still intercepts every read a page makes. Calling `request` directly
    # made the UI suite issue real HTTP to a live API.
    return get(path, params=dict(params) if params else None)


def cached_get(path: str, *, params: dict[str, Any] | None = None) -> Any:
    """A GET that a rerun may serve from memory.

    Opt-in, not the default for `get`. `agent_progress` polls an endpoint in a
    sleep loop waiting for a run to finish, and a cache there would hide the
    completion it is waiting for. Only reads whose staleness a user would not
    notice belong here.

    `user_key` is not decoration. `st.cache_data` is keyed on arguments and shared
    across every browser session this server is handling, so a cache keyed only on
    the path would hand one person's plants to the next. The identity is part of
    the key, and `clear_cache` runs on every write.

    Params are flattened to a sorted tuple because Streamlit hashes each argument
    to build the key, and a dict is not reliably hashable there.

    "View as user" is part of the identity for exactly the reason above. The signed-in
    admin does not change when the mode is entered, so a key of `user_key()` alone
    would serve them their own cached plants while they believed they were looking at
    somebody else's - the same defect as leaking between accounts, only harder to
    notice because both answers look plausible.
    """
    key = tuple(sorted(params.items())) if params else None
    target = acting_as()
    identity = f"{session.user_key()}|as:{target}" if target else session.user_key()
    return _cached(identity, path, key)


def clear_cache() -> None:
    _cached.clear()


def post(path: str, **kwargs: Any) -> Any:
    clear_cache()
    return request("POST", path, **kwargs)


def patch(path: str, **kwargs: Any) -> Any:
    clear_cache()
    return request("PATCH", path, **kwargs)


def put(path: str, **kwargs: Any) -> Any:
    clear_cache()
    return request("PUT", path, **kwargs)


def delete(path: str, **kwargs: Any) -> Any:
    """Added in PR 31 for image removal, the last verb the UI had no way to send."""
    clear_cache()
    return request("DELETE", path, **kwargs)
