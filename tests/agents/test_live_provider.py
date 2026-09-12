"""Live calls against the real provider — Google, and only Google.

Marked `live`, and deselected by default in `pyproject.toml` (TESTING_STRATEGY §12:
live model tests are slower, less deterministic and cost money). It exists because
everything else about the provider is exercised through MockProvider, and a mock
cannot tell us whether structured output, images and the effort setting actually
work together against a real API.

**The vendor is not a free choice here.** A standing instruction says every real
model call made in testing goes through `google` / `gemini-3.5-flash-lite`, with no
exceptions. This file used to be the exception: it was marked `live`, the conftest
guard exempts `live`, and it called `claude-opus-5` — so the one file whose whole
purpose is spending money on a real API was pointed at the wrong vendor, and the
enforcement everywhere else was decoration.

`tests/conftest.py` now refuses any vendor but Google even for a `live` test, so
the two halves agree rather than relying on this docstring being read.

    uv run pytest -m live
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, Field

pytestmark = pytest.mark.live


def _load_env() -> bool:
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    return bool(os.environ.get("GOOGLE_API_KEY"))


#: The one model these tests may use. Named here rather than inline so the two
#: tests cannot drift onto different models, and so the rule is visible in one place.
LIVE_MODEL = "gemini-3.5-flash-lite"


@pytest.fixture(scope="module")
def provider():
    # Keyed on GOOGLE_API_KEY, not the legacy AI_API_KEY: that one is a fallback for
    # the *Anthropic* credential, so a machine with only it set would have skipped
    # for the wrong reason - or worse, not skipped while having no Google key at all.
    if not _load_env() or os.environ.get("GOOGLE_API_KEY", "").endswith("REPLACE-ME"):
        pytest.skip("no usable GOOGLE_API_KEY")
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()
    from app.infrastructure.ai.providers.google import GoogleProvider

    return GoogleProvider()


class Colour(BaseModel):
    name: str = Field(description="the colour, in lowercase English")
    confidence: float = Field(ge=0, le=1)


def test_structured_output_round_trips(provider):
    """The whole chain: schema in, validated model out, usage recorded."""
    result = provider.structured_output(
        model=LIVE_MODEL,
        schema=Colour,
        system="You identify colours. Answer only from what you are told.",
        prompt="The sky on a clear day. What colour is it?",
        max_tokens=512,
        effort="low",
    )

    assert isinstance(result.value, Colour)
    assert "blue" in result.value.name.lower()
    assert 0 <= result.value.confidence <= 1
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
    assert result.usage.model.startswith("gemini")
    assert result.usage.estimated_cost > 0


def test_vision_reaches_the_model(provider):
    """Identification is entirely a vision task, so this is the capability the
    whole of Phase 8 rests on."""
    import io

    from PIL import Image

    from app.infrastructure.ai.provider import ImageInput

    buffer = io.BytesIO()
    Image.new("RGB", (200, 200), (200, 30, 30)).save(buffer, format="JPEG")

    result = provider.structured_output(
        model=LIVE_MODEL,
        schema=Colour,
        system="You identify the dominant colour of an image.",
        prompt="What is the dominant colour of this image?",
        images=[ImageInput(data=buffer.getvalue(), mime_type="image/jpeg")],
        max_tokens=512,
        effort="low",
    )

    assert "red" in result.value.name.lower()
