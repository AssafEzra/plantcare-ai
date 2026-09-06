"""The FINAL §34 smoke path, walked in a browser against the live product.

One test, in order, because it *is* one journey: what a new user does from an
empty account to a plant with a care plan, a health record and growing conditions.
Split into independent tests it would need a fresh identification per case, and
each of those is a real model call against a real bill.

Every assertion is on what the user can read or press. That is the whole point of
this layer: `thumbnail_url` being present in a response is not the same claim as
"the photograph is on the card", and for six weeks those two claims disagreed.
"""

from __future__ import annotations

import pytest

from tests.browser.conftest import click, fill, go, see, settle, text

pytestmark = pytest.mark.browser


def as_upload(data: bytes) -> dict:
    return {"name": "leaf.jpg", "mimeType": "image/jpeg", "buffer": data}


def upload(page, file: dict) -> None:
    page.locator('[data-testid="stFileUploaderDropzoneInput"]').first.set_input_files(files=[file])
    settle(page)


def test_the_whole_path(app, admin_sdk, plant_photo):
    page = app

    # --- an empty account is honest about being empty ---------------------------
    go(page, "הצמחים שלי")
    see(page, "עדיין אין לך צמחים")

    # --- add a plant ------------------------------------------------------------
    go(page, "הוספת צמח")
    see(page, "שלב 1 מתוך 3")
    upload(page, as_upload(plant_photo))
    click(page, "המשך לזיהוי")

    # A real identification. This is the step that proves the timeout budget, and
    # nothing below it can run until it lands.
    see(page, "שלב 3 מתוך 3")
    assert "רמת ביטחון" in text(page), "the identification finished with no confidence shown"

    # --- name it and confirm ----------------------------------------------------
    fill(page, "איך לקרוא לצמח?", "הצמח של הבדיקה")
    click(page, "זה הצמח שלי")

    # Either it had published knowledge (ACTIVE) or it did not (KNOWLEDGE_PENDING).
    # Both are correct outcomes and the screen says which.
    landed = text(page)
    assert "הצמח נוסף" in landed or "כמעט סיימנו" in landed, (
        f"confirmation led nowhere recognisable: {landed[:400]}"
    )

    # --- the grid shows it, with its photograph ---------------------------------
    go(page, "הצמחים שלי")
    see(page, "הצמח של הבדיקה")
    assert page.locator('[data-testid="stMain"] img').count() >= 1, (
        "the plant has a photograph and the grid shows none - the PR 25/27 regression"
    )
    assert "אין תמונה" not in text(page)

    # --- into the plant ---------------------------------------------------------
    click(page, "פתיחה")
    see(page, "הצמח של הבדיקה")

    # --- the first care plan is offered without being asked for (A3) -------------
    # Nothing queued this until PR 31: a plant confirmed onto a species that
    # already had published knowledge went ACTIVE with no plan at all.
    assert "ממתין לאישור שלך" in text(page) or "אין עדיין תוכנית טיפול" in text(page), (
        "an active plant showed neither a proposal nor the empty state that offers one"
    )

    # --- growing conditions can be entered (PR 30) ------------------------------
    page.get_by_text("תנאי הגידול", exact=True).click()
    settle(page)
    fill(page, "חדר", "הסלון")
    click(page, "שמירת תנאי הגידול")
    see(page, "הסלון")

    # --- a health check returns something ---------------------------------------
    click(page, "בדיקת בריאות")
    # Streamlit's multiselect opens its list on focus and commits with Enter.
    # Clicking the popover's option is unreliable: it renders in a portal that is
    # only attached while the widget has focus, so a click on the box followed by
    # a click on the option races the portal.
    combo = page.get_by_role("combobox", name="תמונות לבדיקה")
    combo.click()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    settle(page)
    click(page, "שליחה לבדיקה")

    body = text(page)
    assert "הבדיקה הושלמה" in body or "לא הושלמה" in body or "נמשכת" in body, (
        "a health check ended and the page said nothing - the PR 30 regression"
    )
