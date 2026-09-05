"""Waiting for a 202 to finish, with the user told what is happening.

`FINAL §24` makes every agent call asynchronous: the API returns 202 with an
`agent_request_id` and the client polls `/v1/agent-requests/{id}` through the five
stages. The Add Plant wizard did that from the beginning. Nothing else did.

The health check and the care-plan proposal fired their 202, said "the results
will appear here in a moment", and never looked again — so a run that failed said
nothing at all, and a run that succeeded appeared only if the user happened to
reload. A user reported it exactly as it behaves: *"did a health check and nothing
happened. didnt get result or status update."*

`FINAL §25` asks for graceful, *visible* failure. A page that cannot see the
failure cannot show it, so the polling belongs here, once, rather than in whichever
page remembers to write it.
"""

from __future__ import annotations

import time

import streamlit as st

from app.ui.state.api_client import ApiError, get

POLL_INTERVAL_SECONDS = 1.5

# The five stages of `FINAL §24`. COMPLETE is not listed: it is the end of the
# run rather than a step the user waits through.
STAGES: list[tuple[str, str]] = [
    ("IMAGES_RECEIVED", "התמונות התקבלו"),
    ("CONTEXT_LOADED", "ההקשר נטען"),
    ("ANALYZING", "מנתחים"),
    ("PREPARING_RESULT", "מכינים את התוצאה"),
]

DONE = ("SUCCEEDED", "FAILED")


def await_request(
    request_id: str,
    *,
    labels: list[tuple[str, str]] | None = None,
    timeout_seconds: int = 600,
) -> dict | None:
    """Poll one agent request to completion, rendering its progress.

    Returns the final state, or `None` if the wait ran out — which is not the same
    as a failure and must not be reported as one: the run is still going, and its
    result will be there on the next visit.

    The timeout is generous on purpose. Knowledge research takes minutes and Care
    took 105 seconds on its first live run; a waiter that gave up at ninety
    seconds would teach users that the product is broken when it is merely
    thinking.
    """
    steps = labels or STAGES
    placeholder = st.empty()
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        try:
            state = get(f"/v1/agent-requests/{request_id}")
        except ApiError:
            # A failed poll is not a failed run. Stopping here would report a
            # network hiccup as a failed analysis.
            return None

        _render(placeholder, steps, state)

        if state["status"] in DONE:
            return state

        time.sleep(POLL_INTERVAL_SECONDS)

    return None


def _render(placeholder, steps: list[tuple[str, str]], state: dict) -> None:
    stage = state.get("stage")
    names = [name for name, _ in steps]
    reached = names.index(stage) if stage in names else -1
    finished = state["status"] in DONE

    with placeholder.container():
        for index, (_, label) in enumerate(steps):
            if finished or index < reached:
                st.markdown(f":green[✓] {label}")
            elif index == reached:
                st.markdown(f"**● {label}**")
            else:
                st.markdown(f":gray[○ {label}]")
