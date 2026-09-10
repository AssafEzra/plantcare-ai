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
that is all this component did.

**That advantage does not survive deployment.** On Streamlit Community Cloud the
cookie never reaches `st.context.cookies` at all, so the synchronous read returns
nothing and every refresh landed on the sign-in form. The component therefore
reads as well as writes: it reports `document.cookie` back to Python, which costs
the rerun the cookie was chosen to avoid. The header path is kept as a fast path
because where it works - locally - it is still strictly better.

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

# Twelve hours, and an *idle* window rather than a session length: the cookie is
# rewritten every time a session is restored and every time the token rotates, so
# the clock runs from the last visit rather than from signing in.
#
# Raised from thirty days after the deployed app was observed never signing anybody
# out - thirty days that restart on every use is, in practice, never. Twelve hours
# leaves a working day uninterrupted and asks for the password again on a machine
# left alone overnight (FINAL 22).
#
# This is enforced by the browser alone. Supabase would still honour the token
# itself, so `supabase/config.toml` carries the matching `inactivity_timeout`; if
# the project's plan does not allow that setting, this constant is the whole of it.
MAX_AGE_SECONDS = 60 * 60 * 12

# Per *operation*, not one key for all three. Two operations can run in a single
# script pass - `restore()` reads the stored token and then clears it when the
# refresh is rejected - and a shared key made that pair a
# `StreamlitDuplicateElementKey` rather than a sign-out.
#
# It broke exactly when it mattered least visibly and most often: an idle app is
# precisely when the stored token has expired, so returning to one raised on every
# visit. Worse, the exception came *before* the clear's JavaScript ran, so the token
# it was trying to remove survived and the next visit did the same thing. The
# failure preserved its own cause; only pressing Rerun got past it, because the
# "already tried" flag is set before the crash.
#
# `restore()` also writes a pending token and then reads, on a rarer path. Keying on
# the operation fixes that one too, rather than only the reported pair.
_MOUNT_KEY = "pc_session_store"

# How many reruns to wait for the browser to report its cookie before giving up
# and showing the sign-in form. Two is enough for a component that mounts on the
# first run; more would only lengthen the wait for someone who is signed out.
_ASKED = "pc_session_store_asked"
_MAX_WAITS = 2

_JS = f"""
export default function (component) {{
  const {{ data, setStateValue }} = component
  const NAME = "{COOKIE_NAME}"
  // `Secure` only over https: setting it on a plain-http localhost would make
  // the browser drop the cookie silently and the fix would appear not to work.
  const secure = window.location.protocol === "https:" ? "; Secure" : ""

  const op = data && data.op

  if (op === "save" && data.token) {{
    document.cookie =
      NAME + "=" + encodeURIComponent(data.token) +
      "; path=/; max-age={MAX_AGE_SECONDS}; SameSite=Lax" + secure
  }} else if (op === "clear") {{
    document.cookie = NAME + "=; path=/; max-age=0; SameSite=Lax" + secure
  }}

  // Always report what the browser actually holds, whatever the operation was.
  // An empty string means "asked and answered: nothing there", which is a
  // different answer from "has not replied yet" and the Python side needs both.
  const found = document.cookie
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith(NAME + "="))
  setStateValue("token", found ? decodeURIComponent(found.slice(NAME.length + 1)) : "")
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


def _mount(op: str, token: str | None):
    """Render the component and hand back whatever the browser reported.

    `on_token_change` is passed so `result.token` always exists; without a
    callback the attribute is absent until the value changes.

    The key carries the operation, so a pass that both reads and clears mounts two
    distinct elements instead of the same one twice. See `_MOUNT_KEY`.
    """
    return _renderer()(
        data={"op": op, "token": token},
        key=f"{_MOUNT_KEY}_{op}",
        height=0,
        on_token_change=lambda: None,
    )


def read() -> str | None:
    """The stored refresh token, or `None`.

    Two paths, and the second one is why this function is no longer three lines.

    `st.context.cookies` is populated from the headers of the request that opened
    the session, so it answers synchronously on the very first run — no rerun, no
    flash of the sign-in form. That is the whole reason a cookie was chosen over
    `localStorage`, and it works locally.

    **It returns nothing on Streamlit Community Cloud.** Proven on 2026-09-07 on
    the deployed app: the browser held a valid `pc_refresh_token`, that exact
    token was present and unrevoked in `auth.refresh_tokens`, and the app still
    rendered the sign-in form — so `refresh_session` was never reached. Whatever
    the platform does to the connection, the header does not survive it.

    So when the fast path is empty, ask the browser directly. `document.cookie`
    needs no headers and no cooperation from the host. It costs a rerun, which is
    what `awaiting()` exists to cover.
    """
    try:
        raw = st.context.cookies.get(COOKIE_NAME)
    except Exception:  # pragma: no cover - no context outside a script run
        raw = None

    if raw:
        from urllib.parse import unquote

        st.session_state.pop(_ASKED, None)
        return unquote(raw)

    reported = getattr(_mount("read", None), "token", None)

    if reported is None:
        # Mounted, not yet answered. The component triggers a rerun when it does.
        st.session_state[_ASKED] = int(st.session_state.get(_ASKED, 0)) + 1
        return None

    st.session_state.pop(_ASKED, None)
    return str(reported) or None


def awaiting() -> bool:
    """True while the browser has been asked for the cookie and has not replied.

    Bounded deliberately. If the component never reports — a blocked script, a
    runtime that cannot mount it — the caller must fall through to the sign-in
    form rather than hold a spinner forever. A user who can sign in is better off
    than a user watching a page that never resolves.
    """
    return 0 < int(st.session_state.get(_ASKED, 0)) <= _MAX_WAITS


def write(token: str) -> None:
    """Persist the refresh token in the browser."""
    _mount("save", token)


def clear() -> None:
    """Remove it. Called on sign-out and whenever a stored token is rejected."""
    _mount("clear", None)
