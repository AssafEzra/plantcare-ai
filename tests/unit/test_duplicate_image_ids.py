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
