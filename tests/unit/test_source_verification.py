"""Source verification (FINAL §10, §23).

This is the module that decides whether a claim gets to look like evidence, so
the tests are mostly about the ways a bad citation tries to pass: a real domain
with a fabricated path, a redirect off an approved site, a lookalike domain, a
page that 200s but is about a different plant.

No network. The fetcher is a protocol precisely so these rules can be tested
without depending on a third-party site being up — a test that fetches rhs.org.uk
is a test of rhs.org.uk.
"""

from __future__ import annotations

import pytest

from app.common.enums import KnowledgeSourceClass as Class
from app.domain.services.source_verification import (
    ApprovedDomain,
    FetchedPage,
    SourceClaim,
    host_of,
    is_relevant,
    match_domain,
    verify,
    verify_all,
)

RHS = ApprovedDomain(id="11111111-1111-1111-1111-111111111111", domain="rhs.org.uk", name="RHS")
MOBOT = ApprovedDomain(
    id="22222222-2222-2222-2222-222222222222", domain="missouribotanicalgarden.org"
)

MONSTERA_PAGE = (
    "Monstera deliciosa, the Swiss cheese plant, is a species of flowering plant "
    "native to tropical forests of southern Mexico. Grow in bright indirect light."
)


def page(
    text: str = MONSTERA_PAGE, *, url: str = "https://www.rhs.org.uk/plants/monstera"
) -> FetchedPage:
    return FetchedPage(status_code=200, text=text, final_url=url)


def fetcher_returning(result: FetchedPage | None):
    def _fetch(url: str) -> FetchedPage | None:
        return result

    return _fetch


# --- domain matching ----------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://rhs.org.uk/plants/x", "rhs.org.uk"),
        ("https://www.rhs.org.uk/plants/x", "rhs.org.uk"),
        ("https://apps.rhs.org.uk/plants/x", "rhs.org.uk"),
        ("http://RHS.ORG.UK/x", "rhs.org.uk"),
        ("https://rhs.org.uk:8443/x", "rhs.org.uk"),
    ],
)
def test_a_subdomain_of_an_approved_domain_matches(url: str, expected: str):
    matched = match_domain(url, [RHS])
    assert matched is not None and matched.domain == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://notrhs.org.uk/plants/x",
        "https://rhs.org.uk.example.com/x",
        "https://evil-rhs.org.uk.co/x",
        "https://example.com/?ref=rhs.org.uk",
    ],
)
def test_a_lookalike_domain_does_not_match(url: str):
    """A substring match would approve every one of these.

    `rhs.org.uk.example.com` is a host anybody can register, and an allow-list
    that accepts it is decorative.
    """
    assert match_domain(url, [RHS]) is None


def test_host_of_strips_www_and_port():
    assert host_of("https://WWW.Example.COM:8443/a/b") == "example.com"
    assert host_of("not a url") == ""


# --- relevance ----------------------------------------------------------------


def test_a_page_about_the_species_is_relevant():
    assert is_relevant(MONSTERA_PAGE, "Monstera deliciosa")


def test_a_page_about_a_different_plant_is_not():
    """The failure mode that a 200 alone would miss: the domain is real, the
    article is about something else."""
    other = "Ficus lyrata, the fiddle-leaf fig, prefers bright indirect light."
    assert not is_relevant(other, "Monstera deliciosa")


def test_the_genus_alone_is_not_enough():
    genus_only = "The genus Monstera contains around 50 species of flowering plants."
    assert not is_relevant(genus_only, "Monstera deliciosa")


def test_the_two_words_need_not_be_adjacent():
    """Real pages write "M. deliciosa" or split the name across a table."""
    split = "Monstera. The species deliciosa is the one usually grown indoors."
    assert is_relevant(split, "Monstera deliciosa")


def test_a_distinctive_common_name_is_accepted_as_a_fallback():
    hebrew_page = "מונסטרה היא צמח בית פופולרי הגדל היטב באור עקיף."
    assert is_relevant(hebrew_page, "Unrelated name", "מונסטרה")


def test_a_short_common_name_is_not_a_fallback():
    """ "palm" appearing on a page is not evidence the page is about that palm."""
    assert not is_relevant("A palm in a pot.", "Howea forsteriana", "palm")


def test_an_empty_page_is_never_relevant():
    assert not is_relevant("", "Monstera deliciosa")


# --- classification -----------------------------------------------------------


def test_an_approved_domain_with_a_relevant_page_is_approved():
    result = verify(
        SourceClaim(url="https://www.rhs.org.uk/plants/monstera", title="Monstera"),
        scientific_name="Monstera deliciosa",
        approved_domains=[RHS, MOBOT],
        fetcher=fetcher_returning(page()),
    )
    assert result.source_class is Class.APPROVED
    assert result.approved_domain == RHS.id
    assert result.url == "https://www.rhs.org.uk/plants/monstera"


def test_an_unlisted_domain_is_external_unapproved_not_rejected():
    """FINAL §10 permits outside domains, marked, with extra admin attention."""
    result = verify(
        SourceClaim(url="https://houseplantblog.example/monstera"),
        scientific_name="Monstera deliciosa",
        approved_domains=[RHS],
        fetcher=fetcher_returning(page(url="https://houseplantblog.example/monstera")),
    )
    assert result.source_class is Class.EXTERNAL_UNAPPROVED
    assert result.approved_domain is None
    assert result.url is not None
    assert result.publisher == "houseplantblog.example"


def test_a_url_that_does_not_resolve_is_marked_not_dropped():
    """The claim survives; it just stops looking like a citation."""
    result = verify(
        SourceClaim(url="https://rhs.org.uk/invented"),
        scientific_name="Monstera deliciosa",
        approved_domains=[RHS],
        fetcher=fetcher_returning(None),
    )
    assert result.source_class is Class.AI_GENERATED_REQUIRES_VERIFICATION
    assert result.url is None
    assert result.notes and "rhs.org.uk/invented" in result.notes


def test_a_404_on_an_approved_domain_is_not_approved():
    """A real site with a fabricated path is the commonest hallucinated citation,
    and it would sail through a check that only looked at the host."""
    result = verify(
        SourceClaim(url="https://www.rhs.org.uk/plants/does-not-exist"),
        scientific_name="Monstera deliciosa",
        approved_domains=[RHS],
        fetcher=fetcher_returning(
            FetchedPage(404, "", "https://www.rhs.org.uk/plants/does-not-exist")
        ),
    )
    assert result.source_class is Class.AI_GENERATED_REQUIRES_VERIFICATION
    assert result.url is None
    assert result.notes and "404" in result.notes


def test_an_approved_domain_serving_an_irrelevant_page_is_not_approved():
    result = verify(
        SourceClaim(url="https://www.rhs.org.uk/plants/ficus"),
        scientific_name="Monstera deliciosa",
        approved_domains=[RHS],
        fetcher=fetcher_returning(page("Ficus lyrata is a fig from West Africa.")),
    )
    assert result.source_class is Class.AI_GENERATED_REQUIRES_VERIFICATION


def test_classification_follows_the_redirect_not_the_request():
    """A link on an approved domain that redirects elsewhere must not inherit its
    approval — otherwise a shortener on a vetted host launders any URL."""
    result = verify(
        SourceClaim(url="https://www.rhs.org.uk/out?to=blog"),
        scientific_name="Monstera deliciosa",
        approved_domains=[RHS],
        fetcher=fetcher_returning(page(url="https://someblog.example/monstera")),
    )
    assert result.source_class is Class.EXTERNAL_UNAPPROVED
    assert result.url == "https://someblog.example/monstera"


def test_an_unverified_source_never_carries_an_approved_source_id():
    """Mirrors the CHECK constraint in migration 0006: an unverified claim must
    not be able to masquerade as a cited one."""
    result = verify(
        SourceClaim(url="https://www.rhs.org.uk/gone"),
        scientific_name="Monstera deliciosa",
        approved_domains=[RHS],
        fetcher=fetcher_returning(FetchedPage(500, "", "https://www.rhs.org.uk/gone")),
    )
    assert result.source_class is Class.AI_GENERATED_REQUIRES_VERIFICATION
    assert result.approved_domain is None


def test_a_disabled_domain_simply_is_not_in_the_list():
    """Disabling a source is only meaningful if it stops conferring APPROVED.

    The workflow filters on `is_enabled` before calling in; this asserts the
    consequence, so a future caller that forgets the filter fails a test rather
    than quietly re-approving a domain an administrator retired.
    """
    result = verify(
        SourceClaim(url="https://www.rhs.org.uk/plants/monstera"),
        scientific_name="Monstera deliciosa",
        approved_domains=[],
        fetcher=fetcher_returning(page()),
    )
    assert result.source_class is Class.EXTERNAL_UNAPPROVED


def test_verify_all_preserves_order_and_length():
    """The workflow zips these against the proposed sources to keep
    `supports_sections`, so a dropped or reordered entry would mislabel which
    claims a source backs."""
    claims = [
        SourceClaim(url="https://www.rhs.org.uk/a"),
        SourceClaim(url="https://elsewhere.example/b"),
        SourceClaim(url="https://www.rhs.org.uk/gone"),
    ]

    def by_url(url: str) -> FetchedPage | None:
        if url.endswith("/gone"):
            return None
        return page(url=url)

    results = verify_all(
        claims,
        scientific_name="Monstera deliciosa",
        approved_domains=[RHS],
        fetcher=by_url,
    )
    assert len(results) == len(claims)
    assert [r.source_class for r in results] == [
        Class.APPROVED,
        Class.EXTERNAL_UNAPPROVED,
        Class.AI_GENERATED_REQUIRES_VERIFICATION,
    ]
