"""A real browser, the real interface, the real API (`TESTING_STRATEGY §9`).

Why this layer exists, when there were already ~600 passing tests: every one of
them tested a half. `AppTest` renders the Streamlit script with `api_client`
replaced by a stub; the journey suite drives the HTTP API and renders nothing. So
a stub returning `thumbnail_url` proved the card shows an image while the real
endpoint never set the key, and every card in the grid said "אין תמונה" for weeks
with both suites green.

Six defects found by hand in one session had that shape. This is the seam none of
the other layers can see, and A15 — "httpx at API level + AppTest; no browser
driver" — is the decision that left it unwatched. Revised here.

**The model is real.** Unlike the journey suite, this walks the product as it
ships: one live identification, one live research run, one live care plan, one
live health check. That is slow and it costs money, which is exactly why it is
marked `browser` and excluded from CI — but it is the only layer that can catch a
timeout budget or a provider-shaped regression, and both of those reached a user
this week.

**The account is synthetic.** Created here through the admin API with a generated
password, used only by this run, and never a real person's credentials.
"""

from __future__ import annotations

import contextlib
import os
import socket
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

API_URL = "http://127.0.0.1:8000"
UI_URL = "http://127.0.0.1:8501"

# Generous: a real identification takes ~30s and research minutes. A browser test
# of an AI product that timed out at the usual 5 seconds would fail on success.
SLOW_MS = 420_000


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _load_env() -> bool:
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    return bool(os.environ.get("SUPABASE_URL"))


@pytest.fixture(scope="session")
def services() -> None:
    """Both processes, already running.

    Deliberately not started here. Streamlit and uvicorn take seconds to become
    ready and leave orphans behind on Windows when a run is interrupted; a suite
    that manages them turns every failure into a question about the harness. The
    command is in the skip message instead.
    """
    if not _load_env():
        pytest.skip("no .env with DEV credentials")
    missing = [name for name, port in (("API", 8000), ("UI", 8501)) if not _listening(port)]
    if missing:
        pytest.skip(
            f"{' and '.join(missing)} not running. Start them:\n"
            "  .venv/Scripts/uvicorn.exe app.api.main:create_app --factory --port 8000\n"
            "  .venv/Scripts/streamlit.exe run app/ui/streamlit_app.py --server.port 8501"
        )


@pytest.fixture(scope="session")
def admin_sdk(services):
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


@dataclass(frozen=True)
class Account:
    email: str
    password: str
    user_id: str


@pytest.fixture(scope="session")
def account(admin_sdk) -> Iterator[Account]:
    """One confirmed account for the whole run.

    Session-scoped because Supabase rate-limits the Auth admin API and this suite
    signs in through a browser, which is slow enough that per-test accounts would
    spend the run creating users.
    """
    email = f"browser-{uuid.uuid4().hex[:12]}@example.com"
    password = f"Browser-{uuid.uuid4().hex[:10]}!"
    user = admin_sdk.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    ).user

    yield Account(email=email, password=password, user_id=user.id)

    from tests.integration.conftest import delete_accounts

    delete_accounts(admin_sdk, [user.id])


@pytest.fixture(scope="session")
def plant_photo(admin_sdk) -> bytes:
    """A real photograph of a real plant, fetched from DEV at run time.

    The first version of this suite uploaded a flat green rectangle, and
    identification answered "לא הצלחנו לזהות את הצמח מהתמונות האלה" - which is the
    correct answer. A smoke test of an identification product needs something
    identifiable, and a synthetic image will never be.

    Fetched rather than committed: the repository is public, and a photograph
    someone took of their home is not test data to publish. Any image already in
    the DEV bucket will do.
    """
    import httpx

    from app.infrastructure.storage import plant_images as storage

    # By size, not by recency. DEV is full of images this project's own suites
    # uploaded - solid-colour rectangles a few kilobytes wide - and the newest
    # image is almost always one of those. A photograph of an actual plant is an
    # order of magnitude larger, which is a cheap and reliable way to find one.
    rows = (
        admin_sdk.table("plant_images")
        .select("storage_path_processed, storage_path_original, size_bytes, width, height")
        .eq("context_type", "identification")
        .order("size_bytes", desc=True)
        .limit(5)
        .execute()
        .data
    )
    for row in rows:
        path = row.get("storage_path_processed") or row.get("storage_path_original")
        url = storage.admin_signed_url(path) if path else None
        if not url:
            continue
        response = httpx.get(url, timeout=30, follow_redirects=True)
        if response.status_code == 200 and response.content:
            return response.content

    pytest.skip("no identification photograph in the DEV bucket to drive the smoke path")


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    return {
        **browser_context_args,
        "viewport": {"width": 1440, "height": 1000},
        "locale": "he-IL",
        "timezone_id": "Asia/Jerusalem",
    }


@pytest.fixture
def app(services, account: Account, page):
    """A signed-in page, sitting on the home dashboard."""
    page.set_default_timeout(SLOW_MS)
    page.goto(UI_URL)

    # Streamlit renders every tab's content, hidden panels included, so an
    # unscoped lookup finds the register and reset forms too. The sign-in form is
    # the first one on the page.
    form = page.locator('[data-testid="stForm"]').first
    form.get_by_label("אימייל").fill(account.email)
    form.get_by_label("סיסמה").fill(account.password)
    form.get_by_role("button", name="כניסה").click()

    # The shell only renders its navigation once a session exists, so this is the
    # signal that sign-in actually worked rather than that the page repainted.
    page.get_by_role("link", name="הצמחים שלי").wait_for()
    return page


def settle(page) -> None:
    """Wait for Streamlit to finish the rerun a click triggered.

    Streamlit repaints the header first and fills the page when the script
    finishes, so a fixed sleep either flakes or wastes seconds on every step. The
    status widget is present while a script run is in flight.
    """
    running = page.locator('[data-testid="stStatusWidget"]')
    with contextlib.suppress(Exception):
        running.wait_for(state="visible", timeout=2_000)  # often too fast to see
    running.wait_for(state="detached", timeout=SLOW_MS)


def go(page, label: str) -> None:
    """Navigate by the sidebar entry a user would click."""
    page.get_by_role("link", name=label).click()
    settle(page)


def click(page, label: str, **kwargs) -> None:
    page.get_by_role("button", name=label, **kwargs).click()
    settle(page)


def fill(page, label: str, value: str) -> None:
    """Type into a field by its label.

    `get_by_label` is ambiguous on any Streamlit input that has help text: the
    "?" button carries `aria-label="Help for <label>"`, which matches the same
    substring. Asking for the textbox role picks the field.
    """
    page.get_by_role("textbox", name=label, exact=True).fill(value)
    settle(page)


def see(page, needle: str, *, timeout: int = SLOW_MS) -> None:
    """Assert the user can read this, waiting for the work behind it to finish."""
    from playwright.sync_api import expect

    expect(page.locator('[data-testid="stMain"]')).to_contain_text(needle, timeout=timeout)


def text(page) -> str:
    return page.locator('[data-testid="stMain"]').inner_text()
