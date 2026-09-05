"""Response envelopes shared by every route (API_CONTRACTS "Standard responses")."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
