"""The app's entire custom CSS surface: right-to-left layout.

Everything else in UI_DESIGN_TOKENS — colours, fonts, radii, the heading scale —
is expressed in `.streamlit/config.toml`, because CSS written against Streamlit's
internal class names breaks silently on upgrade. RTL is the one requirement
Streamlit's theming cannot express, so it is the one thing here.

The selectors below are deliberately semantic (`html`, `body`, `[data-testid]`
containers) rather than hashed class names, which keeps them as upgrade-resilient
as this can be.
"""

from __future__ import annotations

import streamlit as st

_RTL_CSS = """
<style>
  /* FINAL §32/§33: the MVP interface is Hebrew and right-to-left. */
  html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
    direction: rtl;
  }

  /* Content aligns to the start edge, which RTL puts on the right. */
  [data-testid="stAppViewContainer"] .stMarkdown,
  [data-testid="stAppViewContainer"] .stHeading,
  [data-testid="stSidebar"] .stMarkdown {
    text-align: right;
  }

  /* Code, identifiers and URLs stay left-to-right: a UUID or a path reads as
     nonsense when the browser reorders it bidirectionally. */
  code, pre, kbd, samp, [data-testid="stCode"], .stCodeBlock {
    direction: ltr;
    text-align: left;
    unicode-bidi: isolate;
  }

  /* Numeric input stays LTR so digits and any minus sign keep their order. */
  input[type="number"] {
    direction: ltr;
    text-align: right;
  }

  /* UI_DESIGN_TOKENS: max content width 1280px. */
  .stMainBlockContainer {
    max-width: 1280px;
  }

  /* Give a focused control a clearly visible ring. UI_DESIGN_TOKENS'
     accessibility section asks for visible focus, and the default outline is
     easy to lose against the warm background. */
  :focus-visible {
    outline: 2px solid #2F6B4F;
    outline-offset: 2px;
  }
</style>
"""


def apply_rtl() -> None:
    """Inject the RTL rules. Call once, immediately after set_page_config."""
    st.html(_RTL_CSS)
