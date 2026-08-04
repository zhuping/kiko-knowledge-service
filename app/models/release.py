from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ChangeLog(TimestampMixin, Base):
    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(
        ForeignKey("content_space.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    before_hash: Mapped[Optional[str]] = mapped_column(String(64))
    after_hash: Mapped[Optional[str]] = mapped_column(String(64))
    after_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    operator_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="unreleased", nullable=False
    )


class ReleaseBatch(TimestampMixin, Base):
    __tablename__ = "release_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(
        ForeignKey("content_space.id"), nullable=False
    )
    base_release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release_version.id")
    )
    source_release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release_version.id")
    )
    batch_type: Mapped[str] = mapped_column(
        String(20), default="normal", nullable=False
    )
    version_label: Mapped[str] = mapped_column(String(64), nullable=False)
    release_note: Mapped[Optional[str]] = mapped_column(String(1000))
    validation_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_by: Mapped[Optional[str]] = mapped_column(String(128))
    published_at: Mapped[Optional[datetime]] = mapped_column()


class ReleaseBatchItem(Base):
    __tablename__ = "release_batch_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("release_batch.id"), nullable=False
    )
    change_log_id: Mapped[int] = mapped_column(
        ForeignKey("change_log.id"), nullable=False
    )
    selected_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ReleaseVersion(TimestampMixin, Base):
    __tablename__ = "release_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_label: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    base_release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release_version.id")
    )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("release_batch.id"), nullable=False
    )
    release_type: Mapped[str] = mapped_column(
        String(20), default="normal", nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False)


class ReleaseCurrent(Base):
    __tablename__ = "release_current"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release_version.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


class ReleaseSnapshot(Base):
    __tablename__ = "release_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release_version.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
