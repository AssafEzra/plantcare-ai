"""Reading knowledge content whatever shape it was written in.

A16 (PR 14) defined a section as `{"text": ..., "confidence": ...}`. The seed data
written in PR 6 predates that decision and stores each section as a plain string,
and `knowledge_versions` is **content-immutable** — those rows can never be
rewritten into the newer shape. So both shapes exist permanently, and every
consumer has to cope with that rather than assume.

This module is the single place that knows. It matters more than it looks: the
Care Agent's context builder filtered on `isinstance(section, dict)`, which meant
a seeded species contributed **no knowledge at all** to its care plan — silently,
because an empty section list is indistinguishable from a species whose knowledge
simply says little.
"""

from __future__ import annotations

from typing import Any

# Sections that are prose about the plant. `sources` is provenance and `toxicity`
# is the seed's older name for `toxicity_safety`; both are handled rather than
# guessed at by the callers.
_ALIASES: dict[str, str] = {"toxicity": "toxicity_safety"}

_NOT_A_SECTION = {"sources"}


def section_text(value: Any) -> str | None:
    """The prose of a section, from either shape.

    Returns None when there is nothing to read, so a caller can tell "no such
    section" from "a section that happens to be empty".
    """
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def section_confidence(value: Any) -> float | None:
    """The confidence, when the shape carries one.

    A string section has none, and inventing a default would let an old row look
    as reviewed as a new one.
    """
    if isinstance(value, dict):
        confidence = value.get("confidence")
        if isinstance(confidence, int | float):
            return float(confidence)
    return None


def as_sections(content: Any) -> dict[str, str]:
    """Every readable section of a knowledge version, keyed by name.

    Older names are mapped onto their current ones, and `sources` is excluded —
    it is provenance, not prose, and feeding a source list to an agent as though
    it were horticultural advice would be worse than omitting it.
    """
    if not isinstance(content, dict):
        return {}

    # A draft blob nests its sections; a published version does not.
    nested = content.get("sections")
    sections: dict[Any, Any] = nested if isinstance(nested, dict) else content

    extracted: dict[str, str] = {}
    for raw_name, value in sections.items():
        name = _ALIASES.get(raw_name, raw_name)
        if name in _NOT_A_SECTION:
            continue
        text = section_text(value)
        if text:
            extracted[name] = text
    return extracted
