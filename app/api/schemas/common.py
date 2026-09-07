"""Envelopes and validators shared by every route (API_CONTRACTS "Standard responses")."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field


def _reject_duplicates(value: list[UUID]) -> list[UUID]:
    """Refuse a list of image ids that names the same image twice.

    Added after three health checks failed in a row on 2026-09-07, each about a
    minute after a billed model call. The client had sent one image id three
    times; nothing rejected it until `save_health_assessment` inserted one row per
    element and the primary key on `health_assessment_images` refused the second.

    Both workflows counted `len(owned) != len(set(image_ids))`, which answers "do
    you own everything you named" correctly and is blind to duplication by
    construction. So the only component that objected was the one that runs last,
    after the money is spent.

    The rule belongs here, at the edge, where it costs microseconds: the agent
    would only ever have seen one image anyway, since `_load_images` fetches with
    SQL `IN`.
    """
    if len(set(value)) != len(value):
        raise ValueError("image_ids must not contain the same image twice")
    return value


# Applied with `Field(min_length=..., max_length=...)`, which differs per route.
UniqueImageIds = Annotated[list[UUID], AfterValidator(_reject_duplicates)]


class DataEnvelope[T](BaseModel):
    """Success envelope: {"data": {...}, "request_id": "uuid"}."""

    data: T
    request_id: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody
    request_id: str
