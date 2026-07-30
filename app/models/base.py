from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import ulid
from app.core.time import utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __init__(self, **values):
        if hasattr(type(self), "id") and "id" not in values:
            values["id"] = ulid()
        for key, value in values.items():
            if not hasattr(type(self), key):
                raise TypeError(f"{key!r} is not a mapped attribute")
            setattr(self, key, value)


class IdMixin:
    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=ulid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
