"""One module per AI vendor, and the lookup that chooses between them.

FINAL §23 asks that agents not be tied to a provider and that model selection be
configuration rather than code. The Protocol in `..provider` delivered the first
half from the start; this package is the second half, which was missing until
somebody asked why. `settings.ai_provider` existed and nothing read it, while
five call sites constructed `AnthropicProvider()` directly - a configuration value
advertising a capability the code did not have, with no test to fail. Recorded in
FINAL §23 per §37.

**Provider is per agent**, from `<AGENT>_PROVIDER`, because the reason to want two
vendors is to compare them on the same work. **The model string is passed
through unvalidated**, from `<AGENT>_MODEL`, so a model released after this code
was written needs no code change - which is the whole point, since a vendor's
product line is their data and not ours to catalogue.

The two halves fail differently, deliberately:

- a bad **provider** name refuses to start, naming the value, because the set of
  vendors is ours and finite;
- a bad **model** name reaches the vendor and comes back as a 404 before any
  generation, so it costs nothing and fails once - `ProviderError` is not in the
  gateway's retry path. Validating it here would mean a network call on every
  cold start, and Community Cloud cold-starts often.

Adding a vendor is one module here plus one line in `PROVIDERS`. The line is
deliberate rather than auto-discovery: an explicit mapping is one mypy can check
and a reader can see, and a filename typo that registers nothing silently is the
same class of invisible drift this package exists to end.
"""

from __future__ import annotations

from collections.abc import Callable

from app.common.errors import ConfigurationError
from app.infrastructure.ai.provider import AIProvider
from app.infrastructure.ai.providers.anthropic import AnthropicProvider
from app.infrastructure.ai.providers.google import GoogleProvider
from app.infrastructure.ai.providers.openai import OpenAIProvider

# Every SDK is a hard dependency and every module is imported here, so mypy
# checks this mapping and a misconfiguration cannot surface as an ImportError in
# the middle of somebody's request.
PROVIDERS: dict[str, Callable[[], AIProvider]] = {
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "openai": OpenAIProvider,
}


def provider_for(name: str) -> AIProvider:
    """The provider registered under `name`, constructed.

    Raises `ConfigurationError` for an unknown name. The settings validator
    normally catches that at startup; this is the backstop for a caller that
    bypassed configuration.
    """
    factory = PROVIDERS.get(name.strip().lower())
    if factory is None:
        known = ", ".join(sorted(PROVIDERS))
        raise ConfigurationError(f"unknown AI provider {name!r}. Known providers: {known}")
    return factory()


def is_known(name: str) -> bool:
    """Whether `name` is a registered provider. Used by the settings validator."""
    return name.strip().lower() in PROVIDERS


__all__ = [
    "PROVIDERS",
    "AnthropicProvider",
    "GoogleProvider",
    "OpenAIProvider",
    "is_known",
    "provider_for",
]
