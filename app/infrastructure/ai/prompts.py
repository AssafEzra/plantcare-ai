"""Versioned prompt loading.

PROJECT_STRUCTURE §9: prompts are versioned files, not anonymous strings
scattered through Python, and the active version is recorded in
`agent_executions`. That last part is why this returns the version alongside the
text — an execution log that says which model ran but not which prompt is only
half a record, and prompt changes are the likelier cause of a behaviour change.

    prompts/<agent>/<name>.v001.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.common.enums import AgentType

PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "prompts"

_FILENAME = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>\d{3})\.md$")


@dataclass(frozen=True)
class Prompt:
    agent: AgentType
    name: str
    version: str
    text: str

    @property
    def version_id(self) -> str:
        """What goes into `agent_executions.prompt_version`."""
        return f"{self.agent.value.lower()}/{self.name}.v{self.version}"


class PromptNotFoundError(RuntimeError):
    pass


@lru_cache(maxsize=64)
def load(agent: AgentType, name: str, version: str | None = None) -> Prompt:
    """Load a prompt, defaulting to the highest version present.

    Defaulting to the newest means adding `foo.v002.md` takes effect without a
    code change, and the version that actually ran is still recorded per
    execution - so a regression can be traced to a specific file.
    """
    directory = PROMPTS_ROOT / agent.value.lower()
    if not directory.is_dir():
        raise PromptNotFoundError(f"no prompt directory for {agent.value}")

    candidates: dict[str, Path] = {}
    for path in directory.glob(f"{name}.v*.md"):
        match = _FILENAME.match(path.name)
        if match and match.group("name") == name:
            candidates[match.group("version")] = path

    if not candidates:
        raise PromptNotFoundError(f"no prompt {agent.value.lower()}/{name}")

    chosen = version or max(candidates)
    if chosen not in candidates:
        raise PromptNotFoundError(f"no prompt {agent.value.lower()}/{name}.v{chosen}")

    return Prompt(
        agent=agent,
        name=name,
        version=chosen,
        text=candidates[chosen].read_text(encoding="utf-8").strip(),
    )


def available(agent: AgentType) -> list[str]:
    directory = PROMPTS_ROOT / agent.value.lower()
    if not directory.is_dir():
        return []
    return sorted(
        {
            match.group("name")
            for path in directory.glob("*.md")
            if (match := _FILENAME.match(path.name))
        }
    )


def clear_cache() -> None:
    load.cache_clear()
