"""One live call against the real provider.

Marked `live` and excluded from CI (TESTING_STRATEGY §12: live model tests are
slower, less deterministic and cost money). It exists because everything else
about the provider is exercised through MockProvider, and a mock cannot tell us
whether messages.parse, adaptive thinking and the effort setting actually work
together against the real API.

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
    return bool(os.environ.get("AI_API_KEY"))


@pytest.fixture(scope="module")
def provider():
    if not _load_env() or os.environ.get("AI_API_KEY", "").endswith("REPLACE-ME"):
        pytest.skip("no usable AI_API_KEY")
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()
    from app.infrastructure.ai.anthropic_provider import AnthropicProvider

    return AnthropicProvider()


class Colour(BaseModel):
    name: str = Field(description="the colour, in lowercase English")
    confidence: float = Field(ge=0, le=1)


def test_structured_output_round_trips(provider):
    """The whole chain: schema in, validated model out, usage recorded."""
    result = provider.structured_output(
        model="claude-opus-5",
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
    assert result.usage.model.startswith("claude")
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
        model="claude-opus-5",
        schema=Colour,
        system="You identify the dominant colour of an image.",
        prompt="What is the dominant colour of this image?",
        images=[ImageInput(data=buffer.getvalue(), mime_type="image/jpeg")],
        max_tokens=512,
        effort="low",
    )

    assert "red" in result.value.name.lower()
