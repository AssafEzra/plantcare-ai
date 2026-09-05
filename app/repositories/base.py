"""Shared repository plumbing.

PostgREST returns loosely-typed JSON, so every call site would otherwise need its
own cast. These helpers put that in one place and give the rest of the codebase
a plain ``dict[str, Any]`` row to work with.

PROJECT_STRUCTURE §8: repositories encapsulate persistence only. Business rules
belong in domain and application services — nothing here decides anything.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, cast

from app.common.errors import AppError, NotFoundError

Row = dict[str, Any]

E = TypeVar("E", bound=AppError)


class _HasData(Protocol):
    """The shape of a supabase-py execute() result."""

    data: Any


def rows(result: _HasData) -> list[Row]:
    """Every returned row, as plain dicts."""
    return cast(list[Row], result.data or [])


def first_row(result: _HasData) -> Row | None:
    """The first row, or ``None`` when the query matched nothing.

    Under RLS, "matched nothing" and "exists but belongs to someone else" are
    indistinguishable here — which is the point. A caller must not be able to
    tell another user's row apart from a non-existent one, so both surface as the
    same 404 rather than a 403 that would confirm existence.
    """
    found = rows(result)
    return found[0] if found else None


def require_row(result: _HasData, error: AppError | None = None) -> Row:
    """The first row, or raise. See :func:`first_row` on why this is a 404."""
    row = first_row(result)
    if row is None:
        raise error or NotFoundError()
    return row
