"""Shared page furniture: headers, empty states, and error/loading feedback.

Every page uses these so the strong empty, loading and error states FINAL §32
asks for are the default rather than something each page remembers to add.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from app.ui.state import session
from app.ui.state.api_client import ApiError


def page_header(title: str, subtitle: str | None = None) -> None:
    st.header(title, anchor=False)
    if subtitle:
        st.caption(subtitle)


def empty_state(
    title: str,
    body: str,
    *,
    icon: str = ":material/eco:",
    action_label: str | None = None,
    action_key: str | None = None,
) -> bool:
    """An empty state that explains and offers a way forward.

    Returns True when the call to action was clicked. FINAL §6 wants the empty
    plant list to invite a first plant rather than simply report emptiness.
    """
    with st.container(border=True):
        st.markdown(f"### {icon} {title}")
        st.write(body)
        if action_label:
            return st.button(action_label, type="primary", key=action_key)
    return False


def show_error(error: ApiError) -> None:
    """Render a failed call, or return the user to sign-in if their session ended.

    An expired session is not something to *report*. Sessions last an hour, so a
    user who leaves a tab open over lunch comes back to a page that looks signed
    in, shows a red banner, and offers no way forward but guessing to reload —
    which is what happened in the browser after two hours of testing.

    `session.access_token()` has already cleared the stored session by the time
    this runs, but the shell decided the routing at the top of the run and is
    still showing the signed-in navigation. Rerunning is what makes the next run
    route to the sign-in page.

    The request id is shown for a server-side failure only. It makes a user report
    traceable in the logs (DEPLOYMENT §9), and it is noise for a validation
    mistake the user can simply correct.
    """
    if error.is_auth_error:
        session.sign_out()
        st.warning("פג תוקף החיבור. אפשר להתחבר מחדש.", icon=":material/lock_clock:")
        st.rerun()

    st.error(error.message, icon=":material/error:")
    if error.request_id and (error.status or 0) >= 500:
        st.caption(f"מזהה בקשה: {error.request_id}")


def guarded(load: Callable[[], object], *, spinner: str = "טוען…"):
    """Run a loading call with a spinner, rendering any ApiError in place.

    Returns the loaded value, or None when the call failed. Pages branch on that
    rather than wrapping every call in their own try/except.
    """
    try:
        with st.spinner(spinner):
            return load()
    except ApiError as exc:
        show_error(exc)
        return None


# --- confirmations across a rerun ------------------------------------------------

FLASH_KEY = "pc_flash"

_RENDERERS = {"success": st.success, "info": st.info, "warning": st.warning}


def flash(message: str, *, kind: str = "success", icon: str = ":material/check_circle:") -> None:
    """Park a message across the rerun an action triggers.

    `st.rerun()` discards anything written before it, so a confirmation shown and
    immediately rerun away is one nobody sees.
    """
    st.session_state[FLASH_KEY] = (kind, message, icon)


def pending_flash() -> bool:
    """Is a message waiting to be shown on this run?

    Lets a control that triggered one stay open across the rerun, instead of
    collapsing and taking the user's context with it.
    """
    return FLASH_KEY in st.session_state


def show_flash() -> None:
    """Render the parked message, if there is one — twice, deliberately.

    Reported from real use: pressing שמירת השינוי appeared to do nothing. It had
    worked; the message was written at the top of the page while the user was at
    the bottom, because `show_flash()` is called just under `page_header` and the
    controls that park messages sit hundreds of pixels below it. Streamlit keeps
    the scroll position across a rerun, so the confirmation for an action was
    rendered where the user demonstrably was not looking. The plant dashboard
    alone parks 23 of them.

    `st.toast` is anchored to the viewport rather than the document, so it is
    visible wherever the reader is standing. The inline box stays because a toast
    dismisses itself after a few seconds and several of these messages say what
    has to happen next — a user who looks away should still find out.

    Lives here rather than in each page: the same helper was copied into three of
    them, which is three places for one behaviour to drift apart.
    """
    parked = st.session_state.pop(FLASH_KEY, None)
    if not parked:
        return

    kind, message, icon = parked
    st.toast(message, icon=icon)
    _RENDERERS[kind](message, icon=icon)
