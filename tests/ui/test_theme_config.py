"""Guards on `.streamlit/config.toml`.

These exist because of a failure that was invisible where it mattered. A Google
Fonts URL requesting two families made Streamlit reject the **entire** `[theme]`
block: the app rendered perfectly happily in default styling, and the reason
appeared only in the server log. Nothing in the browser said anything was wrong,
and no test caught it.

So: assert the rules that make Streamlit throw the theme away, and assert the
palette still matches UI_DESIGN_TOKENS so the approved direction cannot drift
without someone noticing.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml"

# UI_DESIGN_TOKENS_AND_WIREFRAMES, "Design tokens · Color".
TOKENS = {
    "primaryColor": "#2F6B4F",  # --pc-primary
    "backgroundColor": "#F7F5EF",  # --pc-bg
    "secondaryBackgroundColor": "#FFFFFF",  # --pc-surface
    "textColor": "#243027",  # --pc-text
    "borderColor": "#E1E3DC",  # --pc-border
    "greenColor": "#3F7D55",  # --pc-success
    "orangeColor": "#A96F24",  # --pc-warning
    "redColor": "#A94A43",  # --pc-danger
    "grayColor": "#66706A",  # --pc-neutral
}


@pytest.fixture(scope="module")
def config() -> dict:
    assert CONFIG.exists(), "the app has no theme configuration"
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def test_the_config_is_valid_toml(config: dict):
    assert "theme" in config


@pytest.mark.parametrize(("key", "value"), sorted(TOKENS.items()))
def test_the_palette_matches_the_design_tokens(config: dict, key: str, value: str):
    assert config["theme"][key].upper() == value.upper(), (
        f"{key} has drifted from the approved visual direction"
    )


def test_each_font_url_requests_exactly_one_family(config: dict):
    """The regression this file exists for.

    Streamlit raises StreamlitInvalidThemeOptionError when a font source URL
    contains more than one family, and discards the whole theme - silently, as far
    as the browser is concerned.
    """
    theme = config["theme"]
    for key in ("font", "headingFont", "codeFont"):
        value = theme.get(key)
        if not value or "://" not in value:
            continue
        assert value.count("family=") == 1, (
            f"{key} requests multiple families in one URL; Streamlit will reject "
            f"the entire theme and fall back to default styling"
        )


def test_the_font_is_the_specified_family(config: dict):
    """Noto Sans Hebrew is named in UI_DESIGN_TOKENS and carries Hebrew coverage."""
    assert "Noto Sans Hebrew" in config["theme"]["font"]


def test_the_upload_limit_matches_the_image_rule(config: dict):
    """FINAL §20 caps an image at 10 MB. Streamlit's own limit is the first gate,
    ahead of the API's validation."""
    assert config["server"]["maxUploadSize"] == 10


def test_a_single_committed_theme(config: dict):
    """No [theme.dark]: the approved direction is one warm, light palette, and a
    Streamlit-derived dark mode would introduce a second look nobody designed."""
    assert "dark" not in config["theme"]


def test_the_heading_scale_matches_the_tokens(config: dict):
    """Display 32/H1 28/H2 22/H3 18 in the design tokens; h1-h3 are what the app
    actually uses."""
    sizes = config["theme"]["headingFontSizes"]
    assert sizes[:3] == ["28px", "22px", "18px"]
