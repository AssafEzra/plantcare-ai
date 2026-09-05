"""Wikipedia page verification.

FINAL §8: a real relevant Wikipedia page may be shown on the confirmation screen,
and **the URL must never be invented**. §23 resolves how: call Wikipedia's own
public REST API against the confirmed scientific name, and show a link only when
that lookup returns a real matching page.

Deliberately not part of `AIProvider`. This is an HTTP call to Wikipedia, not a
model call, and the whole point is that it is the *check* on what the model said
rather than more of what the model said. The agent is never even asked for a URL,
so there is none to discard.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.config.logging import get_logger

log = get_logger(__name__)

# Short: this runs inside a user-facing identification flow, and a missing link is
# a much smaller loss than a slow confirmation screen.
_TIMEOUT = httpx.Timeout(5.0)

_USER_AGENT = "PlantCareAI/0.1 (plant care assistant; contact via repository)"


@dataclass(frozen=True)
class WikipediaPage:
    title: str
    url: str
    extract: str | None = None


def _normalise(value: str) -> str:
    """Fold case, accents and punctuation for comparison only."""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9 ]", " ", stripped).strip()


def _is_the_same_plant(requested: str, returned: str) -> bool:
    """Does the page Wikipedia returned actually describe the species we asked for?

    Wikipedia redirects generously: asking for a misspelling or a synonym can land
    on a page about something else entirely, and a 200 alone is therefore not
    evidence. Requiring the genus and epithet to match is what makes this a
    verification rather than a lookup.
    """
    wanted = _normalise(requested).split()
    got = _normalise(returned).split()
    if len(wanted) < 2 or not got:
        return False

    genus, epithet = wanted[0], wanted[1]

    # A redirect to the genus page is accepted only when that is what was asked
    # for; otherwise "Monstera deliciosa" landing on "Monstera" is a page about
    # the wrong subject.
    if got == [genus]:
        return len(wanted) == 1

    return got[:2] == [genus, epithet]


def verify_page(scientific_name: str, locale: str = "he") -> WikipediaPage | None:
    """Return a verified page, or None.

    Never raises: a link is an enhancement, and no part of identification should
    fail because Wikipedia was slow or unreachable.
    """
    if not scientific_name or len(scientific_name.split()) < 2:
        return None

    for language in _languages(locale):
        page = _lookup(scientific_name, language)
        if page:
            return page
    return None


def _languages(locale: str) -> list[str]:
    """Prefer the user's language, fall back to English.

    Hebrew Wikipedia has far fewer species articles than English, so a
    Hebrew-only lookup would return nothing for most plants - and an English
    article is still useful to a Hebrew-speaking reader who wants the source.
    """
    primary = (locale or "he").split("-")[0].lower()
    return [primary, "en"] if primary != "en" else ["en"]


def _lookup(scientific_name: str, language: str) -> WikipediaPage | None:
    title = scientific_name.strip().replace(" ", "_")
    url = f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}"

    try:
        response = httpx.get(
            url,
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
    except httpx.HTTPError:
        log.info("wikipedia.unreachable", language=language)
        return None

    if response.status_code != 200:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    # A disambiguation page is not an article about the species.
    if payload.get("type") not in (None, "standard"):
        return None

    returned_title = payload.get("title") or ""
    if not _is_the_same_plant(scientific_name, returned_title):
        log.info(
            "wikipedia.title_mismatch",
            requested=scientific_name,
            returned=returned_title,
            language=language,
        )
        return None

    page_url = (payload.get("content_urls", {}).get("desktop", {}) or {}).get("page")
    if not page_url or not page_url.startswith("https://"):
        return None

    return WikipediaPage(
        title=returned_title,
        url=page_url,
        extract=(payload.get("extract") or None),
    )
