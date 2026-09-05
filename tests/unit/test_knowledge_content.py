"""Reading knowledge content in either shape (A16, and the PR 6 seed).

A16 defined a section as `{"text": ..., "confidence": ...}`. The seed written in
PR 6 stores plain strings, and `knowledge_versions` is content-immutable — those
rows can never be rewritten. Both shapes therefore exist permanently.

The reason this module exists rather than an `isinstance` check at each call
site: the Care Agent's context builder had exactly that check, required a dict,
and so contributed **no knowledge at all** to a care plan for any seeded species.
Silently, because an empty section list looks the same as thin knowledge.
"""

from __future__ import annotations

import pytest

from app.domain.services.knowledge_content import (
    as_sections,
    section_confidence,
    section_text,
)

NEW_SHAPE = {
    "watering": {"text": "להשקות כשהמצע יבש.", "confidence": 0.9},
    "light": {"text": "אור עקיף בהיר.", "confidence": 0.8},
}

SEEDED_SHAPE = {
    "watering": "להשקות כשהמצע יבש.",
    "light": "אור עקיף בהיר.",
    "sources": ["https://example.org"],
}


def test_the_a16_shape_reads():
    assert section_text({"text": "טקסט", "confidence": 0.9}) == "טקסט"


def test_a_plain_string_reads():
    """The seed's shape. The version rows are immutable, so this is permanent."""
    assert section_text("טקסט") == "טקסט"


@pytest.mark.parametrize("empty", ["", "   ", None, {}, {"text": ""}, {"text": "  "}, 42, []])
def test_nothing_readable_is_none(empty):
    """None rather than an empty string, so a caller can tell "no such section"
    from "a section that happens to be blank"."""
    assert section_text(empty) is None


def test_confidence_comes_only_from_the_richer_shape():
    """A string section has no confidence, and inventing a default would let an
    old row look as reviewed as a new one."""
    assert section_confidence({"text": "x", "confidence": 0.4}) == 0.4
    assert section_confidence("x") is None
    assert section_confidence({"text": "x"}) is None


def test_both_shapes_yield_the_same_sections():
    """The property the Care Agent depends on."""
    assert as_sections(NEW_SHAPE) == as_sections(
        {k: v for k, v in SEEDED_SHAPE.items() if k != "sources"}
    )


def test_a_seeded_version_is_not_empty():
    """The regression. `isinstance(section, dict)` returned {} here, so a plan for
    a Monstera was built with no knowledge at all and said so nowhere."""
    assert as_sections(SEEDED_SHAPE)
    assert "watering" in as_sections(SEEDED_SHAPE)


def test_sources_are_not_a_section():
    """Provenance, not prose. Feeding a source list to an agent as though it were
    horticultural advice is worse than omitting it."""
    assert "sources" not in as_sections(SEEDED_SHAPE)


def test_an_older_section_name_is_mapped_to_its_current_one():
    assert "toxicity_safety" in as_sections({"toxicity": "רעיל לחתולים."})


def test_a_draft_blob_nests_its_sections():
    """A draft stores `{"sections": {...}, "sources": [...]}`; a published version
    does not. Both arrive here."""
    assert as_sections({"sections": NEW_SHAPE, "sources": []}) == as_sections(NEW_SHAPE)


@pytest.mark.parametrize("junk", [None, "a string", 42, []])
def test_unreadable_content_yields_nothing_rather_than_raising(junk):
    assert as_sections(junk) == {}
