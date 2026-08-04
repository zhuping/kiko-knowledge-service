from typing import Optional

from pydantic import Field

from app.schemas.common import CamelModel


class ReleaseBatchCreate(CamelModel):
    space_code: str = "default"
    version_label: Optional[str] = None
    release_note: Optional[str] = None
    change_log_ids: list[int] = Field(default_factory=list)
