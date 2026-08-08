from __future__ import annotations

from pydantic import Field

from app.schemas.common import CamelModel


class PublishRequest(CamelModel):
    reason: str | None = Field(default=None, max_length=1000)


class RollbackRequest(CamelModel):
    reason: str = Field(min_length=1, max_length=1000)


class ReleaseValidateRequest(CamelModel):
    reason: str | None = Field(default=None, max_length=1000)
