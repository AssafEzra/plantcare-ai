"""Keep the user signed in across a browser refresh.

Reported from real use: *"every time i hit refresh to the browser window it
logges me out and require a new sign in"*.

`st.session_state` lives for one Streamlit session, and a browser refresh starts a
new one. The auth session was held there and nowhere else, so F5 was
indistinguishable from signing out — on a page that polls a 260-second research
run, that is not a small annoyance.

**Why a cookie rather than `localStorage`.** Streamlit can *read* cookies
(`st.context.cookies`, populated from the connection headers) but cannot write
them, and it can read nothing else about the browser. A cookie is therefore the
only store whose contents are available on the **first script run of a new
session** — which is the exact moment the decision "sign-in form or dashboard"
has to be made. Reading `localStorage` would need a component to report back,
which takes a rerun, and a rerun means either a flash of the sign-in form or a
blank page while the browser answers. Writing is the half Streamlit lacks, so
that is all this component does.

**What is stored.** Only the *refresh* token — never the access token, never the
password, never the email. An access token is short-lived and re-derived from the
refresh token on load, so the stored value is one round trip away from being
useless rather than immediately authoritative. This is the same thing
`supabase-js` does by default in every browser app, and the same exposure: the
cookie is written by JavaScript so it cannot be `HttpOnly`, and a script injected
into this origin could read it. Recorded as a decision in `FINAL §22` rather than
left implicit.

Cleared on sign-out, and discarded the moment Supabase rejects it — `restore()`
treats any refresh failure as signed out.
"""

from __future__ import annotations

import streamlit as st

COOKIE_NAME = "pc_refresh_token"

# Matches the DEV Supabase refresh window. A cookie that outlives the token it
# holds only produces a failed refresh and a second sign-in prompt.
MAX_AGE_SECONDS = 60 * 60 * 24 * 30

_JS = f"""
export default function (component) {{
  const {{ data }} = component
  const NAME = "{COOKIE_NAME}"
  // `Secure` only over https: setting it on a plain-http localhost would make
  // the browser drop the cookie silently and the fix would appear not to work.
  const secure = window.location.protocol === "https:" ? "; Secure" : ""

  if (!data) return

  if (data.op === "save" && data.token) {{
    document.cookie =
      NAME + "=" + encodeURIComponent(data.token) +
      "; path=/; max-age={MAX_AGE_SECONDS}; SameSite=Lax" + secure
  }} else if (data.op === "clear") {{
    document.cookie = NAME + "=; path=/; max-age=0; SameSite=Lax" + secure
  }}
}}
"""


def _renderer():
    """Register the component and return its mount callable.

    Registered on each call rather than once at import. The registry belongs to
    the Streamlit runtime, not to this module, so a callable captured at import
    outlives the runtime it was registered in - which raises "component is not
    registered" the moment a second runtime starts. That is not only a test
    artefact: it is what a Streamlit server does when it recycles a session.

    Re-registering is safe here because the name and the sources are constants;
    the warning against it is about binding one name to different components.
    """
    return st.components.v2.component("pc_session_store", html="<span></span>", js=_JS)


def read() -> str | None:
    """The stored refresh token, straight from the request headers.

    Synchronous and available on the first run of a new session, which is the
    whole reason this is a cookie. Returns `None` when nothing is stored.
    """
    try:
        raw = st.context.cookies.get(COOKIE_NAME)
    except Exception:  # pragma: no cover - no context outside a script run
        return None

    if not raw:
        return None

    from urllib.parse import unquote

    return unquote(raw)


def write(token: str) -> None:
    """Persist the refresh token in the browser."""
    _renderer()(data={"op": "save", "token": token}, key="pc_session_store", height=0)


def clear() -> None:
    """Remove it. Called on sign-out and whenever a stored token is rejected."""
    _renderer()(data={"op": "clear", "token": None}, key="pc_session_store", height=0)
