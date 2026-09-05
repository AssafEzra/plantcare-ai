"""Architectural boundaries, enforced by walking the import graph.

Every rule here is one the specification states plainly and that nothing else can
check. A reviewer will not notice the first time an agent imports a repository,
and once one has, the second is easy to justify. These fail the build instead.

The rules come from PROJECT_STRUCTURE §3, §5 and §7, and FINAL §23.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"


def modules_under(*relative: str) -> list[Path]:
    found: list[Path] = []
    for part in relative:
        found.extend(sorted((APP / part).rglob("*.py")))
    return [path for path in found if path.name != "__init__.py"]


def imports_of(path: Path) -> set[str]:
    """Every module this file imports, as dotted names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def label(path: Path) -> str:
    return str(path.relative_to(APP.parent)).replace("\\", "/")


# --- agents -------------------------------------------------------------------

AGENT_MODULES = modules_under("agents")


@pytest.mark.parametrize("path", AGENT_MODULES, ids=label)
def test_an_agent_never_imports_another_agent(path: Path):
    """FINAL §23: agents do not call each other; orchestration coordinates them.

    Chaining agents directly would put a workflow inside an agent, where the user
    approval steps between them - confirmation, care plan approval - have nowhere
    to happen.
    """
    own_package = path.relative_to(APP / "agents").parts[0]

    for imported in imports_of(path):
        if not imported.startswith("app.agents."):
            continue
        other = imported.removeprefix("app.agents.").split(".")[0]
        if other in {"base", own_package}:
            continue
        pytest.fail(f"{label(path)} imports another agent: {imported}")


@pytest.mark.parametrize("path", AGENT_MODULES, ids=label)
def test_an_agent_never_reaches_persistence(path: Path):
    """An agent receives an assembled context and returns a result.

    If it could query, it could also write - and FINAL §25 ("AI failure never
    creates an authoritative record") would become something every agent has to
    remember rather than something the structure guarantees.
    """
    forbidden = ("app.repositories", "app.infrastructure.supabase", "supabase", "psycopg")

    for imported in imports_of(path):
        assert not imported.startswith(forbidden), (
            f"{label(path)} reaches persistence via {imported}"
        )


@pytest.mark.parametrize("path", AGENT_MODULES, ids=label)
def test_an_agent_never_imports_the_provider_sdk(path: Path):
    """Agents go through the gateway. FINAL §23: agent implementations must not
    contain provider-specific SDK assumptions."""
    for imported in imports_of(path):
        assert not imported.startswith(("anthropic", "openai")), (
            f"{label(path)} imports a provider SDK directly: {imported}"
        )


# --- the domain ---------------------------------------------------------------

DOMAIN_MODULES = modules_under("domain")


@pytest.mark.parametrize("path", DOMAIN_MODULES, ids=label)
def test_the_domain_never_imports_streamlit(path: Path):
    """PROJECT_STRUCTURE §3: the domain layer must not depend on Streamlit."""
    for imported in imports_of(path):
        assert not imported.startswith("streamlit"), f"{label(path)} imports Streamlit"


@pytest.mark.parametrize("path", DOMAIN_MODULES, ids=label)
def test_the_domain_never_imports_fastapi(path: Path):
    """Domain rules are called by the API, not the other way round."""
    for imported in imports_of(path):
        assert not imported.startswith(("fastapi", "starlette")), (
            f"{label(path)} imports the web framework"
        )


@pytest.mark.parametrize("path", modules_under("domain/rules"), ids=label)
def test_domain_rules_are_pure(path: Path):
    """FINAL §1.4: use deterministic software where AI adds no value.

    The rules modules - lifecycle today, recurrence when the scheduler lands -
    must not reach a model or a database. Scheduling in particular is required to
    be deterministic Python, and the cheapest way to keep it that way is to make
    an LLM import fail the build.
    """
    forbidden = (
        "app.agents",
        "app.infrastructure.ai",
        "app.repositories",
        "anthropic",
        "supabase",
    )

    for imported in imports_of(path):
        assert not imported.startswith(forbidden), (
            f"{label(path)} is a domain rule and must stay pure, but imports {imported}"
        )


# --- the UI -------------------------------------------------------------------

UI_MODULES = modules_under("ui")


@pytest.mark.parametrize("path", UI_MODULES, ids=label)
def test_the_ui_never_talks_to_the_database(path: Path):
    """PROJECT_STRUCTURE §7: pages must not contain SQL or call Supabase for
    business operations.

    `app/ui/state/session.py` is the single exception and is excluded below:
    obtaining a credential is not a business operation, and the alternative is
    proxying auth through the API for no benefit.
    """
    if path.name == "session.py":
        return

    forbidden = ("app.repositories", "app.infrastructure.supabase", "supabase", "psycopg")

    for imported in imports_of(path):
        assert not imported.startswith(forbidden), (
            f"{label(path)} reaches the database directly via {imported}"
        )


@pytest.mark.parametrize("path", UI_MODULES, ids=label)
def test_the_ui_never_calls_an_agent(path: Path):
    """A page that invokes an agent has business logic in it by definition."""
    for imported in imports_of(path):
        assert not imported.startswith(("app.agents", "app.infrastructure.ai")), (
            f"{label(path)} invokes AI directly: {imported}"
        )


# --- configuration ------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    modules_under("agents", "api", "domain", "orchestration", "repositories", "ui"),
    ids=label,
)
def test_configuration_is_read_in_one_place(path: Path):
    """PROJECT_STRUCTURE §6. Ruff's banned-api rule catches `os.environ` at the
    call site; this catches the import-level dodge of `from os import environ`."""
    for imported in imports_of(path):
        assert imported not in {"os.environ", "os.getenv"}, (
            f"{label(path)} reads configuration directly; use app.config.settings"
        )


# --- the provider SDK ---------------------------------------------------------


def test_only_the_provider_adapter_imports_the_anthropic_sdk():
    """One module owns the SDK, so swapping providers means writing a sibling
    rather than hunting through the codebase."""
    offenders = [
        label(path)
        for path in modules_under(
            "agents", "api", "domain", "orchestration", "repositories", "ui", "notifications"
        )
        if any(i.startswith("anthropic") for i in imports_of(path))
    ]

    assert not offenders, f"the Anthropic SDK leaked outside the adapter: {offenders}"
