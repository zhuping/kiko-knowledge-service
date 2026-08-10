from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ReleaseBatch(TimestampMixin, Base):
    __tablename__ = "release_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_base.id"), nullable=False
    )
    base_release_id: Mapped[Optional[int]] = mapped_column(Integer)
    source_release_id: Mapped[Optional[int]] = mapped_column(Integer)
    release_type: Mapped[str] = mapped_column(
        String(20), default="normal", nullable=False
    )
    release_note: Mapped[Optional[str]] = mapped_column(String(1000))
    validation_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_by: Mapped[Optional[str]] = mapped_column(String(128))
    published_at: Mapped[Optional[datetime]] = mapped_column()


class ReleaseVersion(TimestampMixin, Base):
    __tablename__ = "release_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_base.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    version_label: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_release_id: Mapped[Optional[int]] = mapped_column(Integer)
    batch_id: Mapped[Optional[int]] = mapped_column(Integer)
    release_type: Mapped[str] = mapped_column(
        String(20), default="normal", nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime] = mapped_column(nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(1000))
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "version_no"),
        Index("ix_release_kb_time", "knowledge_base_id", "published_at"),
    )


class ReleaseCurrent(Base):
    __tablename__ = "release_current"

    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_base.id"), primary_key=True
    )
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release_version.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


class ReleaseCatalogNode(Base):
    __tablename__ = "release_catalog_node"

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release_version.id"), nullable=False
    )
    catalog_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    node_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_path: Mapped[Optional[str]] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class ReleaseMapping(Base):
    __tablename__ = "release_mapping"

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release_version.id"), nullable=False
    )
    catalog_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    knowledge_id: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_id: Mapped[str] = mapped_column(String(8), nullable=False)
    __table_args__ = (
        UniqueConstraint("release_id", "catalog_node_id", "knowledge_id"),
    )


class ReleaseKnowledge(Base):
    __tablename__ = "release_knowledge"

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release_version.id"), nullable=False
    )
    knowledge_id: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_id: Mapped[str] = mapped_column(String(8), nullable=False)
    revision_id: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("release_id", "knowledge_id"),
        Index("ix_release_knowledge_revision", "knowledge_id", "revision_id"),
    )


class ReleaseRelation(Base):
    __tablename__ = "release_relation"

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release_version.id"), nullable=False
    )
    relation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    relation_revision_id: Mapped[int] = mapped_column(Integer, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_canonical_id: Mapped[str] = mapped_column(String(8), nullable=False)
    to_canonical_id: Mapped[str] = mapped_column(String(8), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("release_id", "relation_id"),
        Index(
            "ix_release_relation_relation_revision",
            "relation_id",
            "relation_revision_id",
        ),
    )
