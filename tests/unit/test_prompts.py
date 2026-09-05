"""Versioned prompt loading (PROJECT_STRUCTURE §9)."""

from __future__ import annotations

import pytest

from app.common.enums import AgentType
from app.infrastructure.ai import prompts


@pytest.fixture(autouse=True)
def _clear():
    prompts.clear_cache()
    yield
    prompts.clear_cache()


def test_a_prompt_loads():
    prompt = prompts.load(AgentType.IDENTIFICATION, "identify")

    assert prompt.text
    assert prompt.version == "001"


def test_the_version_id_is_what_gets_logged():
    """agent_executions.prompt_version has to identify the exact file, or a
    behaviour change cannot be traced to the prompt that caused it."""
    prompt = prompts.load(AgentType.IDENTIFICATION, "identify")

    assert prompt.version_id == "identification/identify.v001"


def test_a_missing_prompt_is_an_explicit_error():
    with pytest.raises(prompts.PromptNotFoundError):
        prompts.load(AgentType.IDENTIFICATION, "does_not_exist")


def test_a_missing_version_is_an_explicit_error():
    with pytest.raises(prompts.PromptNotFoundError):
        prompts.load(AgentType.IDENTIFICATION, "identify", version="999")


def test_the_newest_version_is_chosen(tmp_path, monkeypatch):
    """Adding foo.v002.md takes effect without a code change, and the version that
    actually ran is still recorded per execution."""
    directory = tmp_path / "identification"
    directory.mkdir()
    (directory / "sample.v001.md").write_text("old", encoding="utf-8")
    (directory / "sample.v002.md").write_text("new", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS_ROOT", tmp_path)
    prompts.clear_cache()

    prompt = prompts.load(AgentType.IDENTIFICATION, "sample")

    assert prompt.version == "002"
    assert prompt.text == "new"


def test_an_older_version_can_still_be_pinned(tmp_path, monkeypatch):
    directory = tmp_path / "care"
    directory.mkdir()
    (directory / "plan.v001.md").write_text("first", encoding="utf-8")
    (directory / "plan.v002.md").write_text("second", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS_ROOT", tmp_path)
    prompts.clear_cache()

    assert prompts.load(AgentType.CARE, "plan", version="001").text == "first"


def test_the_identification_prompt_forbids_inventing_links():
    """FINAL §8: the Wikipedia URL must never be invented, so the prompt has to say
    so - the deterministic check that follows is the guarantee, but a model that
    is not asked for URLs will not produce ones to discard."""
    text = prompts.load(AgentType.IDENTIFICATION, "identify").text.lower()

    assert "url" in text
    assert "hebrew" in text or "עברית" in text
