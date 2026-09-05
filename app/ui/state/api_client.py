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

from app.config.settings import get_settings
from app.ui.state import session

_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0)

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


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = session.access_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
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
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.request(
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


def post(path: str, **kwargs: Any) -> Any:
    return request("POST", path, **kwargs)


def patch(path: str, **kwargs: Any) -> Any:
    return request("PATCH", path, **kwargs)


def put(path: str, **kwargs: Any) -> Any:
    return request("PUT", path, **kwargs)
