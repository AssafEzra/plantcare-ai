"""The same image may not be submitted twice to an agent.

Regression for three health checks that failed in a row on 2026-09-07, each about
a minute after a billed Opus call. The client sent one image id three times.
Nothing objected until `save_health_assessment` inserted a row per element and the
primary key on `health_assessment_images` refused the second, by which point the
model had already run and been paid for.

Both workflows had counted `len(owned) != len(set(image_ids))`, which answers "do
you own everything you named" correctly and cannot see duplication at all. These
tests pin the gate at the *front*: the request never reaches the model.

Identification had the identical hole and did not crash, because it has no join
table to violate — it quietly analysed one photograph while the user believed it
had used four. That is the case the second half of this file covers.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.routers.health import HealthCheckRequest
from app.api.routers.identification import IdentificationRunRequest


def test_a_health_check_refuses_the_same_image_twice() -> None:
    image = uuid4()

    with pytest.raises(ValidationError) as raised:
        HealthCheckRequest(image_ids=[image, image])

    assert "twice" in str(raised.value)


def test_a_health_check_accepts_distinct_images() -> None:
    request = HealthCheckRequest(image_ids=[uuid4(), uuid4(), uuid4()])

    assert len(request.image_ids) == 3


def test_an_identification_refuses_the_same_image_twice() -> None:
    image = uuid4()

    with pytest.raises(ValidationError) as raised:
        IdentificationRunRequest(image_ids=[image, image])

    assert "twice" in str(raised.value)


def test_an_identification_accepts_distinct_images() -> None:
    request = IdentificationRunRequest(image_ids=[uuid4(), uuid4()])

    assert len(request.image_ids) == 2


def test_the_duplicate_is_rejected_even_when_the_count_is_legal() -> None:
    """The length check passes and the request is still invalid.

    The original bug sent three ids, which is within the 1-4 range every existing
    check enforced. Length was never the problem, so a test that relied on it
    would pass while the defect remained.
    """
    image = uuid4()

    with pytest.raises(ValidationError):
        HealthCheckRequest(image_ids=[image, image, image])


def test_gallery_labels_are_unique_even_for_images_from_the_same_minute() -> None:
    """The root cause, pinned.

    `st.multiselect` maps a selection back to its option by formatted label —
    `self.options[self.formatted_options.index(v)]` — and `.index()` returns the
    *first* match. Labels were the date alone, so three images from one afternoon
    formatted identically and every one of the user's three selections resolved to
    the first option: one id, three times, which is what reached the API.

    The three that caused it were uploaded at 17:08:05, :11 and :15 — the same
    minute — so seconds would not have separated them either.
    """
    from app.ui.components.health_check_dialog import _gallery_choices

    same_minute = [
        {"id": "aaa", "created_at": "2026-09-07T17:08:05+00:00"},
        {"id": "bbb", "created_at": "2026-09-07T17:08:11+00:00"},
        {"id": "ccc", "created_at": "2026-09-07T17:08:15+00:00"},
    ]

    labels = list(_gallery_choices(same_minute).values())

    assert len(set(labels)) == len(labels), labels
