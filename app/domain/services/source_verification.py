"""Deterministic source verification.

FINAL §10 and §23. Every external claim must have a real source, and what makes
it real is that **Python fetched it**, not that a model said so. A model asked to
cite its sources will produce plausible URLs at a rate that has nothing to do
with whether those pages exist.

So this module is the authority on `knowledge_sources.source_class`:

* `APPROVED` — the URL was fetched, returned 200, its host matches an enabled
  `approved_sources` domain, and the page is about the species in question.
* `EXTERNAL_UNAPPROVED` — fetched and relevant, but from a domain nobody has
  vetted. FINAL §10 permits these "when necessary" and requires them to be marked
  and to receive extra admin attention before publication.
* `AI_GENERATED_REQUIRES_VERIFICATION` — everything else: the URL did not
  resolve, returned an error, or is about a different plant. The claim is kept —
  a draft is not thrown away because a citation was bad — but it is labelled for
  exactly what it is.

The third case is the one worth being careful about. It would be tempting to drop
a source that fails verification, which would leave a draft looking better
sourced than it is. Marking it is the honest outcome and the one FINAL §10 asks
for, and the database CHECK constraints already refuse to let such a row carry an
`approved_source_id`.

No I/O policy lives here beyond the fetch itself: this module classifies, and the
orchestration layer decides what to do with the classification.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from app.common.enums import KnowledgeSourceClass
from app.config.logging import get_logger

log = get_logger(__name__)

# A source check is background work, not user-facing, so it can afford to wait
# longer than the Wikipedia lookup on the confirmation screen. It still has a
# ceiling: a draft with twenty sources must not hang on one slow host.
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_USER_AGENT = "PlantCareAI/0.1 (plant care assistant; contact via repository)"

# Enough of the page to judge relevance without downloading a whole media-heavy
# article. Botanical pages put the binomial in the title and the first paragraph.
_MAX_BYTES = 200_000

_TAG = re.compile(r"<[^>]+>")
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class SourceClaim:
    """A source an agent said it used.

    Deliberately not the agent's own model. This module is the domain's, and PR 21
    verifies health-assessment sources through it with a different agent contract
    on the other side; depending on one agent's Pydantic class would make the
    second caller import the first agent's package to cite a web page.
    """

    url: str
    title: str | None = None
    publisher: str | None = None


@dataclass(frozen=True)
class VerifiedSource:
    """One source after verification.

    `source_class` is set here and only here — by Python, having fetched the URL,
    never by the model.
    """

    source_class: KnowledgeSourceClass
    url: str | None
    title: str | None = None
    publisher: str | None = None
    approved_domain: str | None = None
    citation_text: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ApprovedDomain:
    """One row of `approved_sources`, reduced to what classification needs."""

    id: str
    domain: str
    name: str | None = None


@dataclass(frozen=True)
class FetchedPage:
    """What came back from a URL. `text` is already stripped of markup."""

    status_code: int
    text: str
    final_url: str


class PageFetcher(Protocol):
    """How a URL is retrieved.

    A protocol rather than a direct `httpx` call so tests can verify the
    classification rules without a network — the rules are the interesting part,
    and a test that depends on a third-party site being up tests that site.
    """

    def __call__(self, url: str) -> FetchedPage | None: ...


def fetch_page(url: str) -> FetchedPage | None:
    """Retrieve a page, or None if it could not be retrieved.

    Never raises. A source that cannot be fetched is a classification outcome
    (`AI_GENERATED_REQUIRES_VERIFICATION`), not an error that should abandon a
    research run that may have thirteen good sections in it.
    """
    try:
        with (
            httpx.Client(
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT, "Accept": "text/html,*/*"},
            ) as http,
            http.stream("GET", url) as response,
        ):
            if response.status_code != 200:
                return FetchedPage(response.status_code, "", str(response.url))

            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) >= _MAX_BYTES:
                    break

            return FetchedPage(200, _to_text(body), str(response.url))
    except Exception as exc:
        log.info("source.fetch_failed", url=url[:200], error_type=type(exc).__name__)
        return None


def _to_text(body: bytes) -> str:
    """Markup to plain text, well enough to look for a species name in it."""
    raw = body.decode("utf-8", errors="replace")
    without_code = _SCRIPT_OR_STYLE.sub(" ", raw)
    return " ".join(_TAG.sub(" ", without_code).split())


def host_of(url: str) -> str:
    """The bare lowercase host, without `www.` or a port."""
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def match_domain(url: str, domains: Iterable[ApprovedDomain]) -> ApprovedDomain | None:
    """Find the approved domain a URL belongs to.

    A suffix match on a **label boundary**, not a substring match: `rhs.org.uk`
    must match `www.rhs.org.uk` but must not match `notrhs.org.uk`, which is a
    different organisation that anyone could register. Getting this wrong is how
    an allow-list becomes decorative.
    """
    host = host_of(url)
    if not host:
        return None

    for candidate in domains:
        domain = candidate.domain.lower().removeprefix("www.")
        if host == domain or host.endswith("." + domain):
            return candidate
    return None


def _normalise(value: str) -> str:
    """Fold case, accents and punctuation, for comparison only.

    Keeps every *alphanumeric* character rather than only `a-z0-9`. An ASCII-only
    filter deletes Hebrew outright, which would have made the common-name fallback
    below dead code in the one language this application actually writes - the
    kind of bug that passes every English test.
    """
    decomposed = unicodedata.normalize("NFKD", value.lower())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return "".join(char if char.isalnum() else " " for char in stripped)


def is_relevant(page_text: str, scientific_name: str, common_name: str | None = None) -> bool:
    """Is this page actually about the species?

    Requires the genus and the epithet to appear, though not necessarily adjacent
    — a page may write "M. deliciosa" after introducing the genus, or separate the
    two across a table. A common name alone is accepted as a fallback only when it
    is distinctive enough to mean something: "monstera" is, "palm" is not.

    A page reached through a valid URL that does not mention the plant is the
    common failure mode of a hallucinated citation — the domain is real, the
    article is not — and it is precisely what a 200 alone would miss.
    """
    if not page_text:
        return False

    haystack = _normalise(page_text)
    parts = _normalise(scientific_name).split()

    if len(parts) >= 2:
        genus, epithet = parts[0], parts[1]
        if genus in haystack and epithet in haystack:
            return True

    if common_name:
        name = _normalise(common_name).strip()
        if len(name) >= 6 and name in haystack:
            return True

    return False


def verify(
    source: SourceClaim,
    *,
    scientific_name: str,
    common_name: str | None = None,
    approved_domains: Iterable[ApprovedDomain] = (),
    fetcher: PageFetcher = fetch_page,
) -> VerifiedSource:
    """Classify one proposed source. Never raises."""
    domains = list(approved_domains)
    page = fetcher(source.url)

    if page is None:
        return _unverified(source, "המקור לא נטען.")
    if page.status_code != 200:
        return _unverified(source, f"המקור החזיר סטטוס {page.status_code}.")
    if not is_relevant(page.text, scientific_name, common_name):
        # The most important branch. A real page about a different plant is worse
        # than a dead link, because it looks like evidence.
        return _unverified(source, "הדף אינו עוסק במין הזה.")

    # Classified on the URL that was actually fetched, so a redirect off an
    # approved domain onto an unvetted one does not inherit its approval.
    matched = match_domain(page.final_url, domains)

    if matched is not None:
        return VerifiedSource(
            source_class=KnowledgeSourceClass.APPROVED,
            url=page.final_url,
            title=source.title,
            publisher=source.publisher or matched.name or matched.domain,
            approved_domain=matched.id,
        )

    return VerifiedSource(
        source_class=KnowledgeSourceClass.EXTERNAL_UNAPPROVED,
        url=page.final_url,
        title=source.title,
        publisher=source.publisher or host_of(page.final_url),
        notes="דומיין שאינו ברשימת המקורות המאושרים; נדרשת בדיקה נוספת לפני פרסום.",
    )


def verify_all(
    sources: Iterable[SourceClaim],
    *,
    scientific_name: str,
    common_name: str | None = None,
    approved_domains: Iterable[ApprovedDomain] = (),
    fetcher: PageFetcher = fetch_page,
) -> list[VerifiedSource]:
    domains = list(approved_domains)
    return [
        verify(
            source,
            scientific_name=scientific_name,
            common_name=common_name,
            approved_domains=domains,
            fetcher=fetcher,
        )
        for source in sources
    ]


def _unverified(source: SourceClaim, reason: str) -> VerifiedSource:
    """A claim that did not survive verification.

    The URL is dropped rather than stored. A CHECK constraint requires a URL on
    every external class and permits its absence only here, and keeping an
    unverified link would invite someone to render it as a citation later — which
    is the whole thing this module exists to prevent.
    """
    return VerifiedSource(
        source_class=KnowledgeSourceClass.AI_GENERATED_REQUIRES_VERIFICATION,
        url=None,
        title=source.title,
        publisher=source.publisher,
        notes=f"{reason} הכתובת שהוצעה: {source.url[:300]}",
    )
