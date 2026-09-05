"""Repository result helpers.

PostgREST returns two shapes: a list for a table query, and a bare dict for an
RPC whose function returns a single composite row. These helpers exist so no call
site has to know which one it is looking at.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.common.errors import NotFoundError, PlantNotFoundError
from app.repositories.base import first_row, require_row, rows


@dataclass
class Result:
    data: Any


def test_a_list_result_is_returned_as_rows():
    assert rows(Result([{"id": 1}, {"id": 2}])) == [{"id": 1}, {"id": 2}]


def test_a_dict_result_is_a_single_row():
    """An RPC returning one composite row. Assuming a list here made every
    upsert_species call fail with KeyError: 0."""
    assert rows(Result({"id": "abc"})) == [{"id": "abc"}]


def test_an_empty_result_is_no_rows():
    assert rows(Result([])) == []
    assert rows(Result(None)) == []


def test_first_row_of_a_dict_result():
    assert first_row(Result({"id": "abc"})) == {"id": "abc"}


def test_first_row_of_nothing_is_none():
    assert first_row(Result([])) is None


def test_require_row_raises_when_empty():
    with pytest.raises(NotFoundError):
        require_row(Result([]))


def test_require_row_uses_the_supplied_error():
    """So a caller can say "plant not found" rather than a generic 404."""
    with pytest.raises(PlantNotFoundError):
        require_row(Result([]), PlantNotFoundError())


def test_require_row_returns_a_dict_result():
    assert require_row(Result({"id": "abc"}))["id"] == "abc"
