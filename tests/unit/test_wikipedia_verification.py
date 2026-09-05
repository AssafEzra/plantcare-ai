"""Wikipedia page verification.

FINAL §8: the URL must never be invented, and §23 resolves how — call Wikipedia's
own REST API and show a link only when it returns a real matching page.

The interesting cases are the ones where a naive implementation would *succeed*
wrongly: Wikipedia redirects generously, so a 200 alone is not evidence that the
page describes the species we asked about.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.infrastructure.wikipedia import verify_page

SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
HE_SUMMARY = "https://he.wikipedia.org/api/rest_v1/page/summary/"


def page_payload(title: str, *, page_type: str = "standard", url: str | None = None) -> dict:
    return {
        "type": page_type,
        "title": title,
        "extract": "A species of flowering plant.",
        "content_urls": {
            "desktop": {"page": url or f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"}
        },
    }


@respx.mock
def test_a_real_page_is_returned():
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(json=page_payload("Monstera deliciosa"))

    page = verify_page("Monstera deliciosa")

    assert page is not None
    assert page.url == "https://en.wikipedia.org/wiki/Monstera_deliciosa"


@respx.mock
def test_a_missing_page_yields_no_link():
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(404)

    assert verify_page("Fakus inventus") is None


@respx.mock
def test_a_redirect_to_a_different_subject_is_rejected():
    """The case a status-code check would get wrong.

    Wikipedia redirects freely, so asking for one species can land on a page about
    another. Accepting it would show the user authoritative-looking information
    about the wrong plant, which is worse than showing no link at all.
    """
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(json=page_payload("Philodendron"))

    assert verify_page("Monstera deliciosa") is None


@respx.mock
def test_a_redirect_to_the_genus_page_is_rejected():
    """ "Monstera" is not an article about "Monstera deliciosa"."""
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(json=page_payload("Monstera"))

    assert verify_page("Monstera deliciosa") is None


@respx.mock
def test_a_disambiguation_page_is_rejected():
    """A disambiguation page is a list of possibilities, not a species article."""
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(
        json=page_payload("Monstera deliciosa", page_type="disambiguation")
    )

    assert verify_page("Monstera deliciosa") is None


@respx.mock
def test_authorship_in_the_requested_name_still_matches():
    """A model may return "Monstera deliciosa Liebm."; the article is the same."""
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(json=page_payload("Monstera deliciosa"))

    assert verify_page("Monstera deliciosa Liebm.") is not None


@respx.mock
def test_the_users_language_is_preferred():
    """Hebrew first, English as the fallback: Hebrew Wikipedia has far fewer
    species articles, so a Hebrew-only lookup would return nothing for most
    plants."""
    respx.get(url__startswith=HE_SUMMARY).respond(
        json=page_payload("Monstera deliciosa", url="https://he.wikipedia.org/wiki/מונסטרה")
    )

    page = verify_page("Monstera deliciosa", locale="he")

    assert page is not None
    assert "he.wikipedia.org" in page.url


@respx.mock
def test_english_is_used_when_the_local_article_is_missing():
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(json=page_payload("Monstera deliciosa"))

    page = verify_page("Monstera deliciosa", locale="he")

    assert page is not None
    assert "en.wikipedia.org" in page.url


@respx.mock
def test_a_network_failure_costs_the_link_and_nothing_else():
    """A link is an enhancement. Identification must not fail because Wikipedia
    was slow."""
    respx.get(url__startswith=HE_SUMMARY).mock(side_effect=httpx.ConnectError("down"))
    respx.get(url__startswith=SUMMARY).mock(side_effect=httpx.ConnectError("down"))

    assert verify_page("Monstera deliciosa") is None


@respx.mock
def test_a_non_https_url_is_rejected():
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(
        json=page_payload("Monstera deliciosa", url="http://en.wikipedia.org/wiki/Monstera")
    )

    assert verify_page("Monstera deliciosa") is None


@respx.mock
def test_malformed_json_is_rejected():
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(content=b"not json")

    assert verify_page("Monstera deliciosa") is None


@pytest.mark.parametrize("name", ["", "Monstera", "   ", "x"])
def test_a_name_that_is_not_a_binomial_is_never_looked_up(name: str):
    """No request is made at all, so respx is not even needed: there is nothing a
    single word could be verified against."""
    assert verify_page(name) is None


@respx.mock
def test_a_name_needing_url_encoding_is_handled():
    respx.get(url__startswith=HE_SUMMARY).respond(404)
    respx.get(url__startswith=SUMMARY).respond(json=page_payload("Aloe barbadensis"))

    assert verify_page("Aloe  barbadensis") is not None
