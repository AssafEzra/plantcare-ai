"""A plant must be able to have more than one health check (PR 32).

`MAX_IMAGES_PER_CONTEXT` was enforced against every image the plant had ever had
in a context, so the first health check could attach four photographs and the
second could attach none — permanently, with the message "אפשר להעלות עד 4
תמונות". Found while building the upload dialog: the dialog would have been
unusable on any plant that had already been checked once.

The rule now counts only images not yet consumed by an agent. A gallery image is
permanent and always counts; health and identification images are evidence for
one run and stop counting once `ai_used` marks them as used.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.common.enums import ImageContextType


class CountingTable:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.filters: dict[str, Any] = {}

    def select(self, *_a: Any, **_k: Any) -> CountingTable:
        return self

    def eq(self, column: str, value: Any) -> CountingTable:
        self.filters[column] = value
        return self

    def execute(self) -> Any:
        matched = [
            row
            for row in self.rows
            if all(str(row.get(k)) == str(v) for k, v in self.filters.items())
        ]
        return type("Result", (), {"data": matched, "count": len(matched)})()


class Client:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def table(self, _name: str) -> CountingTable:
        return CountingTable(self.rows)


PLANT = str(uuid4())


def image(context: str, *, ai_used: bool) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "plant_id": PLANT,
        "context_type": context,
        "user_visible": True,
        "ai_used": ai_used,
    }


def test_a_second_health_check_has_room_again():
    from app.repositories import plants

    used_up = [image("health", ai_used=True) for _ in range(4)]
    client = Client(used_up)

    assert plants.count_uncommitted_images(client, PLANT, ImageContextType.HEALTH) == 0, (
        "images already used by an assessment still occupy the next check's slots"
    )


def test_images_waiting_for_this_check_still_count():
    """The cap is real; it just applies to the submission rather than to history.
    Four unused health images means the fifth upload is refused, as it should be."""
    from app.repositories import plants

    client = Client([image("health", ai_used=False) for _ in range(4)])

    assert plants.count_uncommitted_images(client, PLANT, ImageContextType.HEALTH) == 4


def test_the_gallery_is_still_capped_for_life():
    """A gallery image is a portrait, not evidence. Four is four, forever."""
    from app.repositories import plants

    client = Client([image("gallery", ai_used=True) for _ in range(4)])

    assert plants.count_uncommitted_images(client, PLANT, ImageContextType.GALLERY) == 4


@pytest.mark.parametrize("context", ["health", "identification"])
def test_consumed_evidence_frees_a_slot(context):
    from app.repositories import plants

    rows = [image(context, ai_used=True), image(context, ai_used=False)]

    assert plants.count_uncommitted_images(Client(rows), PLANT, ImageContextType(context)) == 1
