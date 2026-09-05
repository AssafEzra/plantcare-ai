"""The RLS matrix borrows the integration harness's direct Postgres connection.

Re-exported rather than duplicated: these fixtures drop from the `postgres`
superuser to `authenticated` before any policy is exercised, and a second copy of
that logic is a second place for it to be forgotten. A superuser bypasses RLS
entirely, which would make every assertion in this package pass while proving
nothing.
"""

from __future__ import annotations

from tests.integration.conftest import db, dsn, make_user

__all__ = ["db", "dsn", "make_user"]
