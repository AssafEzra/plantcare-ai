"""An in-memory stand-in for the slice of the Supabase client the scheduler uses.

Enough of PostgREST's query builder - `select`, `eq`, `neq`, `in_`, `order`,
`limit`, `insert`, `update` - to run the real scheduler code against rows a test writes
by hand. It applies filters exactly and nothing else: no RLS, no constraints, no
joins. Tests that need those belong in the integration suite.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


class FakeQuery:
    def __init__(
        self,
        store: dict[str, list[dict[str, Any]]],
        table: str,
        unique: dict[str, str] | None = None,
    ):
        self.store = store
        self.table = table
        self.unique = unique or {}
        self.pending_delete = False
        self.filters: list[tuple[str, str, Any]] = []
        #: Every `.order()` call, in the order they were made. A list rather than one
        #: pair because PostgREST composes them - `.order("display_order")
        #: .order("created_at", desc=True)` means "by position, newest first within a
        #: tie" - and keeping only the last one made the fake silently disagree with
        #: the database about exactly the tie-breaking the callers rely on.
        self.ordering: list[tuple[str, bool]] = []
        self.max_rows: int | None = None
        self.pending_update: dict[str, Any] | None = None
        self.pending_insert: dict[str, Any] | None = None

    # --- building ---------------------------------------------------------------

    def select(self, *_args: Any, **_kwargs: Any) -> FakeQuery:
        return self

    def eq(self, column: str, value: Any) -> FakeQuery:
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column: str, value: Any) -> FakeQuery:
        self.filters.append(("neq", column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> FakeQuery:
        self.filters.append(("in", column, [str(v) for v in values]))
        return self

    def order(self, column: str, desc: bool = False) -> FakeQuery:
        self.ordering.append((column, desc))
        return self

    def limit(self, count: int) -> FakeQuery:
        self.max_rows = count
        return self

    def update(self, values: dict[str, Any]) -> FakeQuery:
        self.pending_update = values
        return self

    def insert(self, values: dict[str, Any]) -> FakeQuery:
        self.pending_insert = values
        return self

    def delete(self) -> FakeQuery:
        self.pending_delete = True
        return self

    # --- running ----------------------------------------------------------------

    def _matches(self, row: dict[str, Any]) -> bool:
        for kind, column, value in self.filters:
            if kind == "eq" and str(row.get(column)) != str(value):
                return False
            if kind == "neq" and str(row.get(column)) == str(value):
                return False
            if kind == "in" and str(row.get(column)) not in value:
                return False
        return True

    def execute(self) -> Any:
        table = self.store.setdefault(self.table, [])

        if self.pending_insert is not None:
            column = self.unique.get(self.table)
            if column and any(r.get(column) == self.pending_insert.get(column) for r in table):
                # What the unique index does: the second insert fails.
                raise RuntimeError(f"duplicate key value violates unique constraint on {column}")
            row = {"id": str(uuid4()), **self.pending_insert}
            table.append(row)
            return _Result([row])

        found = [row for row in table if self._matches(row)]

        if self.pending_delete:
            self.store[self.table] = [row for row in table if row not in found]
            return _Result(found)

        if self.pending_update is not None:
            for row in found:
                row.update(self.pending_update)
            return _Result(found)

        # Applied least significant first, which is how a stable sort composes
        # several keys into the one PostgREST would have produced.
        for column, desc in reversed(self.ordering):
            found = sorted(found, key=lambda r, c=column: str(r.get(c)), reverse=desc)
        if self.max_rows is not None:
            found = found[: self.max_rows]
        return _Result([dict(row) for row in found])


class _Result:
    def __init__(self, data: list[dict[str, Any]]):
        self.data = data


class FakeDB:
    """`unique` maps a table to one column the fake enforces like a unique index."""

    def __init__(
        self,
        store: dict[str, list[dict[str, Any]]] | None = None,
        *,
        unique: dict[str, str] | None = None,
    ):
        self.store: dict[str, list[dict[str, Any]]] = store or {}
        self.unique = unique or {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self.store, name, self.unique)
