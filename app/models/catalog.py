from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TextbookEdition(TimestampMixin, Base):
    __tablename__ = "textbook_edition"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    edition_name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    grade_term: Mapped[str] = mapped_column(String(32), nullable=False)
    version_year: Mapped[int] = mapped_column(Integer, default=2024, nullable=False)
    source_file_id: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class CatalogNode(TimestampMixin, Base):
    __tablename__ = "catalog_node"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_id: Mapped[int] = mapped_column(
        ForeignKey("textbook_edition.id"), nullable=False
    )
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("catalog_node.id"))
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    node_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_path: Mapped[Optional[str]] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (
        UniqueConstraint("edition_id", "source_key"),
        Index("ix_catalog_tree", "edition_id", "parent_id", "sort_order"),
    )


class KnowledgeBase(TimestampMixin, Base):
    __tablename__ = "knowledge_base"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    grade_term: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    textbook_edition_id: Mapped[int] = mapped_column(
        ForeignKey("textbook_edition.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    current_release_id: Mapped[Optional[int]] = mapped_column(Integer)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        Index("ix_knowledge_base_filter", "grade_term", "subject", "status"),
    )


class KnowledgeObject(TimestampMixin, Base):
    __tablename__ = "knowledge_object"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_id: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    latest_revision_id: Mapped[Optional[int]] = mapped_column(Integer)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)


class KnowledgeRevision(TimestampMixin, Base):
    __tablename__ = "knowledge_revision"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    grade_term: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    ocr_signals: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    exercise_signature: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        UniqueConstraint("knowledge_id", "revision_no"),
        Index("ix_knowledge_revision_filter", "grade_term", "type", "scope"),
    )


class KnowledgeBaseMapping(TimestampMixin, Base):
    __tablename__ = "knowledge_base_mapping"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_base.id"), nullable=False
    )
    catalog_node_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_node.id"), nullable=False
    )
    knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "catalog_node_id", "knowledge_id"),
        Index("ix_kb_mapping_node", "knowledge_base_id", "catalog_node_id"),
    )


class KnowledgeRelation(TimestampMixin, Base):
    __tablename__ = "knowledge_relation"

    id: Mapped[int] = mapped_column(primary_key=True)
    relation_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    latest_revision_id: Mapped[Optional[int]] = mapped_column(Integer)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (Index("ix_relation_key", "relation_key"),)


class RelationRevision(TimestampMixin, Base):
    __tablename__ = "relation_revision"

    id: Mapped[int] = mapped_column(primary_key=True)
    relation_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_relation.id"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    to_knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(String(1000))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        UniqueConstraint("relation_id", "revision_no"),
        Index("ix_relation_revision_type", "relation_type"),
    )
