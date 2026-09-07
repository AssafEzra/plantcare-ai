"""Shared state the UI suite must not carry between tests.

`st.cache_data` is process-wide and outlives an `AppTest`, so a page cached under
one test's stub would be served to the next - the tests would pass or fail
depending on their order, which is the worst kind of green.
"""

from __future__ import annotations

import pytest

from app.ui.state import api_client


@pytest.fixture(autouse=True)
def _clear_api_cache() -> None:
    api_client.clear_cache()
