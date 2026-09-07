"""Run the FastAPI application inside the Streamlit process.

DEPLOYMENT §3 puts the UI and the API in separate services, and that is still the
target shape. It cannot be expressed on a host that runs exactly one process from
one repository - Streamlit Community Cloud - where the UI would otherwise come up
with nothing behind it and every click would fail.

So on that host only, and only when `EMBEDDED_API` is set, the entry point starts
uvicorn on a daemon thread bound to loopback. Nothing else changes: the UI still
speaks HTTP to the API, the routers are untouched, and the seam PROJECT_STRUCTURE
§7 draws between them is exactly where it was. What is lost is the ability to
restart or scale either half alone, and the isolation of one crashing without the
other.

The recorded deviation is in DEPLOYMENT_AND_OPERATIONS §3, per FINAL §37.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import streamlit as st
import uvicorn

from app.config.settings import get_settings

# How long to wait for the server to bind before giving up and letting the page
# render. Generous because this happens once per process, on a cold container
# that may also be waking a paused database - and a page that renders half a
# second early would only show an error the user cannot act on.
_STARTUP_TIMEOUT_SECONDS = 60


@st.cache_resource(show_spinner="מפעיל את השרת…")
def _serve() -> uvicorn.Server:
    """Start the API once per process and return once it is accepting requests.

    `st.cache_resource` is what makes "once" true. Streamlit re-runs the entire
    script on every interaction, so a plain function call here would try to bind
    port 8000 again on the first click and raise.

    The thread is a daemon: when Streamlit exits, the API must not keep the
    process alive behind it.

    uvicorn is safe to run off the main thread - `Server.capture_signals` returns
    early when it is not the main thread, rather than failing to install handlers.
    """
    settings = get_settings()
    port = urlparse(settings.api_base_url).port or 8000

    server = uvicorn.Server(
        uvicorn.Config(
            "app.api.main:app",
            host="127.0.0.1",
            port=port,
            # Loopback only. Nothing outside the process can reach the API, which
            # is the property the two-service topology was buying.
            log_level="info",
            access_log=False,
        )
    )
    threading.Thread(target=server.run, name="plantcare-api", daemon=True).start()

    # Wait for the bind rather than hoping. The first thing the entry point does
    # after this is call `/v1/me`, and a race here would show every visitor an
    # error on the first page load of a cold start.
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.1)

    return server


def start_if_configured() -> None:
    """Start the embedded API when the deployment asks for one. Otherwise nothing."""
    if get_settings().embedded_api:
        _serve()
