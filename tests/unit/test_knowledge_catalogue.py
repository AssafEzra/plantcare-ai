"""The published knowledge has to be findable (PR 32).

Reported from real use: *"ידע מפורסם tab should also show a list of all plants in
the knowledge base with a link that leads to the knowledge text"*.

The tab was a text box asking for a species UUID. DEV holds 857 species and about
fifty published articles, so unless the administrator already knew an id, none of
it was reachable — and even once found, the screen showed a version number, a
date and a badge, never the text. `GET /v1/species/{id}/knowledge` had returned
both content and sources since PR 15; the admin screen read neither.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

SPECIES_A = str(uuid4())
SPECIES_B = str(uuid4())


class Table:
    def __init__(self, store: dict[str, list[dict]], name: str):
        self.store, self.name = store, name
        self._eq: dict[str, Any] = {}
        self._in: tuple[str, list] | None = None

    def select(self, *_a: Any, **_k: Any) -> Table:
        return self

    def eq(self, column: str, value: Any) -> Table:
        self._eq[column] = value
        return self

    def in_(self, column: str, values: list) -> Table:
        self._in = (column, [str(v) for v in values])
        return self

    def order(self, *_a: Any, **_k: Any) -> Table:
        return self

    def execute(self) -> Any:
        found = [
            row
            for row in self.store.get(self.name, [])
            if all(str(row.get(k)) == str(v) for k, v in self._eq.items())
        ]
        if self._in:
            column, values = self._in
            found = [row for row in found if str(row.get(column)) in values]
        return type("R", (), {"data": found})()


class Client:
    def __init__(self, store: dict[str, list[dict]]):
        self.store = store

    def table(self, name: str) -> Table:
        return Table(self.store, name)


@pytest.fixture
def client(env):
    return Client(
        {
            "knowledge_versions": [
                {
                    "id": "v-a",
                    "species_id": SPECIES_A,
                    "language": "he",
                    "version_number": 2,
                    "is_current": True,
                    "published_at": "2026-09-05T20:00:00Z",
                },
                {
                    "id": "v-b",
                    "species_id": SPECIES_B,
                    "language": "he",
                    "version_number": 1,
                    "is_current": True,
                    "published_at": "2026-09-04T20:00:00Z",
                },
                {
                    "id": "v-a-old",
                    "species_id": SPECIES_A,
                    "language": "he",
                    "version_number": 1,
                    "is_current": False,
                    "published_at": "2026-09-01T20:00:00Z",
                },
            ],
            "species": [
                {
                    "id": SPECIES_A,
                    "scientific_name": "Calathea makoyana",
                    "common_name": "צמח הטווס",
                },
                {"id": SPECIES_B, "scientific_name": "Monstera deliciosa", "common_name": None},
            ],
            "plants": [
                {"species_id": SPECIES_A},
                {"species_id": SPECIES_A},
                {"species_id": SPECIES_B},
            ],
        }
    )


def test_every_published_species_is_listed(client):
    from app.orchestration.workflows import knowledge

    catalogue = knowledge.published_catalogue(client)

    assert {entry["scientific_name"] for entry in catalogue} == {
        "Calathea makoyana",
        "Monstera deliciosa",
    }


def test_only_the_current_version_of_each(client):
    """One row per species. Listing every version turns a catalogue into a log."""
    from app.orchestration.workflows import knowledge

    assert len(knowledge.published_catalogue(client)) == 2


def test_each_entry_carries_the_name_a_person_reads(client):
    """A UUID is not a name. The whole defect was a screen that had only ids."""
    from app.orchestration.workflows import knowledge

    entry = next(e for e in knowledge.published_catalogue(client) if e["species_id"] == SPECIES_A)
    assert entry["common_name"] == "צמח הטווס"
    assert entry["scientific_name"] == "Calathea makoyana"


def test_it_says_how_many_plants_depend_on_each_article(client):
    """The one number that says which entry matters, and the reason an admin
    opens this screen rather than the drafts one."""
    from app.orchestration.workflows import knowledge

    counts = {e["species_id"]: e["plant_count"] for e in knowledge.published_catalogue(client)}
    assert counts[SPECIES_A] == 2
    assert counts[SPECIES_B] == 1


def test_search_matches_either_name(client):
    from app.orchestration.workflows import knowledge

    by_latin = knowledge.published_catalogue(client, query="monstera")
    by_hebrew = knowledge.published_catalogue(client, query="טווס")

    assert [e["scientific_name"] for e in by_latin] == ["Monstera deliciosa"]
    assert [e["scientific_name"] for e in by_hebrew] == ["Calathea makoyana"]


def test_an_empty_catalogue_is_not_an_error(env):
    from app.orchestration.workflows import knowledge

    assert knowledge.published_catalogue(Client({"knowledge_versions": []})) == []
