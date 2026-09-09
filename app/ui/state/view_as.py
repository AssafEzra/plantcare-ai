"""The admin "view as user" mode.

An administrator can open an account and see it as its owner does — their plants,
their health history, their care plan. That answers the question an admin could not
answer before: *why* is this user confused, and what are they actually looking at.

Three properties hold it together, and none of them lives here:

* **The reads are permitted** by the `_select_admin` RLS policy on every user-owned
  table, so no service role and no new endpoints are involved.
* **The reads are confined** to one user because every user-facing query filters on
  an owner id explicitly rather than trusting RLS to scope it — see the comment at
  `app/repositories/plants.py:89`, which was written for this exact reason.
* **Nothing can be written.** The API refuses every non-GET request carrying the
  `X-Act-As-User` header, before it reaches a route.

What lives here is the client half: which user is being viewed, and making that
impossible to forget. An administrator who loses track of the mode and reads a screen
as their own data is the failure this module is shaped around, which is why entering
and leaving both go through one function and why the banner is not optional.
"""

from __future__ import annotations

import streamlit as st

from app.ui.state.api_client import ACT_AS_KEY, clear_cache

#: The viewed account's email, kept only so the banner can name it. Not authoritative
#: for anything - the id in `ACT_AS_KEY` is what the header carries.
EMAIL_KEY = "pc_act_as_email"


def active() -> bool:
    return bool(st.session_state.get(ACT_AS_KEY))


def active_target() -> str | None:
    """The viewed user id, or None. Used as part of cache keys as well as for display.

    Distinct from `active()` because a boolean is not enough for a cache key: two
    different viewed accounts must not share cached reads any more than two different
    signed-in accounts may.
    """
    target = st.session_state.get(ACT_AS_KEY)
    return str(target) if target else None


def target_email() -> str | None:
    return st.session_state.get(EMAIL_KEY)


def enter(user_id: str, email: str | None) -> None:
    """Start viewing `user_id`, and rerun into their application.

    The cache is cleared on the way in even though `cached_get` already keys on the
    viewed user: the key makes the reads *correct*, and clearing makes the first
    screen current rather than up to five minutes old.
    """
    st.session_state[ACT_AS_KEY] = str(user_id)
    st.session_state[EMAIL_KEY] = email
    clear_cache()
    st.rerun()


def leave() -> None:
    """Stop viewing, and rerun back into the admin panel.

    Also clears anything the mode left in session state. `pc_selected_plant` is the
    one that matters: it would otherwise point at one of the *user's* plants, and the
    admin's own plant page would open on a plant they cannot read.
    """
    for key in (ACT_AS_KEY, EMAIL_KEY, "pc_selected_plant", "pc_confirmed"):
        st.session_state.pop(key, None)
    clear_cache()
    st.rerun()


def banner() -> None:
    """Say, on every page, whose account this is.

    Deliberately loud and deliberately unconditional. The mode changes what every
    screen means, and a subtle indicator that an administrator stops noticing after
    ten minutes is the same as no indicator at all.
    """
    if not active():
        return

    who = target_email() or st.session_state.get(ACT_AS_KEY)
    left, right = st.columns([4, 1], vertical_alignment="center")
    with left:
        st.warning(f"צפייה בחשבון של {who} · קריאה בלבד", icon=":material/visibility:")
    with right:
        if st.button("יציאה ממצב צפייה", key="view_as_exit", width="stretch"):
            leave()
