from typing import Any, Optional

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ContentSpace(TimestampMixin, Base):
    __tablename__ = "content_space"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class TextbookEdition(TimestampMixin, Base):
    __tablename__ = "textbook_edition"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    edition_name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), default="数学", nullable=False)
    school_system: Mapped[str] = mapped_column(
        String(20), default="六三制", nullable=False
    )
    version_year: Mapped[int] = mapped_column(Integer, default=2024, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class KnowledgeObject(TimestampMixin, Base):
    __tablename__ = "knowledge_object"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    grade_term: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    cognitive_level: Mapped[str] = mapped_column(String(20), nullable=False)
    importance: Mapped[str] = mapped_column(String(20), nullable=False)
    exercise_signature: Mapped[Optional[str]] = mapped_column(Text)
    solution_feature: Mapped[Optional[str]] = mapped_column(String(1000))
    scene_feature: Mapped[Optional[str]] = mapped_column(String(1000))
    numeric_feature: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    updated_by: Mapped[Optional[str]] = mapped_column(String(128))


class KnowledgeTerm(TimestampMixin, Base):
    __tablename__ = "knowledge_term"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    term_type: Mapped[str] = mapped_column(String(20), nullable=False)
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    __table_args__ = (
        UniqueConstraint("knowledge_id", "term_type", "term"),
        Index("ix_knowledge_term_search", "term", "term_type", "knowledge_id"),
    )


class CatalogNode(TimestampMixin, Base):
    __tablename__ = "catalog_node"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(
        ForeignKey("content_space.id"), nullable=False
    )
    edition_id: Mapped[int] = mapped_column(
        ForeignKey("textbook_edition.id"), nullable=False
    )
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("catalog_node.id"))
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    node_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (
        Index("ix_catalog_tree", "space_id", "edition_id", "parent_id", "sort_order"),
    )


class CatalogKnowledgeNode(TimestampMixin, Base):
    __tablename__ = "catalog_knowledge_node"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(
        ForeignKey("content_space.id"), nullable=False
    )
    group_node_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_node.id"), nullable=False
    )
    knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (UniqueConstraint("space_id", "group_node_id", "knowledge_id"),)


class TextbookMapping(TimestampMixin, Base):
    __tablename__ = "textbook_mapping"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(
        ForeignKey("content_space.id"), nullable=False
    )
    edition_id: Mapped[int] = mapped_column(
        ForeignKey("textbook_edition.id"), nullable=False
    )
    knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    catalog_node_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("catalog_node.id")
    )
    textbook_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mapping_type: Mapped[str] = mapped_column(String(20), nullable=False)
    alignment_type: Mapped[str] = mapped_column(
        String(20), default="equivalent", nullable=False
    )
    edition_label: Mapped[Optional[str]] = mapped_column(String(200))
    edition_keywords: Mapped[list[Any]] = mapped_column(
        JSON, default=list, nullable=False
    )
    page_start: Mapped[Optional[int]] = mapped_column(Integer)
    page_end: Mapped[Optional[int]] = mapped_column(Integer)
    evidence: Mapped[Optional[str]] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "space_id", "edition_id", "knowledge_id", "textbook_path", "mapping_type"
        ),
    )


class KnowledgeRelation(TimestampMixin, Base):
    __tablename__ = "knowledge_relation"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(
        ForeignKey("content_space.id"), nullable=False
    )
    from_knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    to_knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    edition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("textbook_edition.id"))
    basis: Mapped[Optional[str]] = mapped_column(String(1000))
    note: Mapped[Optional[str]] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class PolicyRule(TimestampMixin, Base):
    __tablename__ = "policy_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(500))
    applicable_grade: Mapped[Optional[str]] = mapped_column(String(100))
    condition_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    __table_args__ = (UniqueConstraint("rule_code", "rule_version"),)


class KnowledgePolicyMapping(TimestampMixin, Base):
    __tablename__ = "knowledge_policy_mapping"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(
        ForeignKey("content_space.id"), nullable=False
    )
    knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_object.id"), nullable=False
    )
    policy_rule_id: Mapped[int] = mapped_column(
        ForeignKey("policy_rule.id"), nullable=False
    )
    applicable_condition: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    basis: Mapped[Optional[str]] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    __table_args__ = (UniqueConstraint("space_id", "knowledge_id", "policy_rule_id"),)
