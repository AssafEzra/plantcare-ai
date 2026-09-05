"""Shared page furniture: headers, empty states, and error/loading feedback.

Every page uses these so the strong empty, loading and error states FINAL §32
asks for are the default rather than something each page remembers to add.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

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
    """Render a failed call.

    The request id is shown for a server-side failure only. It is what makes a
    user report traceable in the logs (DEPLOYMENT §9), and it is noise for a
    validation mistake the user can simply correct.
    """
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
