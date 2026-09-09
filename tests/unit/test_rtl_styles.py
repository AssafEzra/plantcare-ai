"""The one stylesheet the application ships, and the promise it makes.

`app/ui/styles/rtl.py` exists because RTL is the single requirement Streamlit's
theming cannot express. Its docstring commits to a rule that nothing enforced:
the selectors stay semantic, because CSS written against Streamlit's internal
class names breaks silently on upgrade.

"Silently" is the operative word, and why these tests are worth having. A
stylesheet that stops matching does not raise, does not fail a test and does not
log; it just renders the Hebrew interface left-to-right one day.
"""

from __future__ import annotations

import re

from app.ui.styles.rtl import _RTL_CSS


def test_no_selector_depends_on_a_streamlit_class_hash() -> None:
    """The rule the module docstring states and nothing checked.

    Streamlit's own markdown styles live on `.st-emotion-cache-ziy5zq`, and that
    hash changes between releases. Targeting it would work perfectly until an
    upgrade, then stop - with no error anywhere.
    """
    assert "st-emotion-cache" not in _RTL_CSS


def test_markdown_lists_are_aligned_to_the_right() -> None:
    """The reported bug.

    Streamlit sets `text-align: left` directly on the `<ul>` inside a markdown
    block. Our `text-align: right` on `.stMarkdown` is inherited, and an inherited
    value loses to a declaration on the element itself whatever its specificity -
    so a bulleted list rendered left-aligned under a right-aligned heading. It was
    reported on the health card's "מה נראה בתמונות" and "מה כדאי לעשות".
    """
    rules = _list_rules()

    assert rules, "no rule targets markdown lists"
    assert any("text-align: right" in rule for rule in rules)


def test_list_items_are_indented_from_the_right() -> None:
    """The second half, and the reason it is not enough to fix the alignment.

    Streamlit indents each item with `margin-left`/`padding-left`. Under RTL that
    is the wrong edge: the text would align correctly and still sit inset from the
    side it is not reading from.
    """
    item_rules = " ".join(
        rule for rule in _RTL_CSS.split("}") if re.search(r"\bli\b", rule.split("{")[0])
    )

    assert "margin-right" in item_rules
    assert "padding-right" in item_rules
    # The physical properties being overridden have to be zeroed explicitly:
    # Streamlit sets them through a `margin` shorthand, which a logical property
    # would not displace.
    assert "margin-left: 0" in item_rules
    assert "padding-left: 0" in item_rules


def _list_rules() -> list[str]:
    """Every rule whose selector mentions a markdown list."""
    found = []
    for block in _RTL_CSS.split("}"):
        if "{" not in block:
            continue
        selector, _, body = block.partition("{")
        if re.search(r"\b(ul|ol)\b", selector):
            found.append(body)
    return found
