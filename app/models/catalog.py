from __future__ import annotations

from datetime import datetime
from typing import Optional, Union

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class CurriculumPackage(IdMixin, TimestampMixin, Base):
    __tablename__ = "curriculum_packages"

    code: Mapped[str] = mapped_column(String(96), unique=True)
    subject_code: Mapped[str] = mapped_column(String(32))
    grade: Mapped[int] = mapped_column(SmallInteger)
    semester: Mapped[str] = mapped_column(String(16))
    edition: Mapped[str] = mapped_column(String(128))
    publisher: Mapped[Optional[str]] = mapped_column(String(128))
    curriculum_standard: Mapped[Optional[str]] = mapped_column(String(128))
    region_json: Mapped[Optional[list]] = mapped_column(JSON)
    current_release_id: Mapped[Optional[str]] = mapped_column(String(26))
    status: Mapped[str] = mapped_column(String(20), default="active")

    __table_args__ = (
        Index(
            "ix_packages_subject_grade_semester_status",
            "subject_code",
            "grade",
            "semester",
            "status",
        ),
    )


class PackageVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_versions"

    package_id: Mapped[str] = mapped_column(
        ForeignKey("curriculum_packages.id"), index=True
    )
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    based_on_version_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("package_versions.id")
    )
    release_notes: Mapped[Optional[str]] = mapped_column(Text)
    benchmark_result_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128))
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(128))
    published_by: Mapped[Optional[str]] = mapped_column(String(128))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (UniqueConstraint("package_id", "version"),)


class CurriculumNode(IdMixin, TimestampMixin, Base):
    __tablename__ = "curriculum_nodes"

    logical_id: Mapped[str] = mapped_column(String(26))
    package_version_id: Mapped[str] = mapped_column(
        ForeignKey("package_versions.id"), index=True
    )
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("curriculum_nodes.id"))
    node_type: Mapped[str] = mapped_column(String(24))
    code: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(128))
    order_no: Mapped[int] = mapped_column(Integer)
    source_json: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="active")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        UniqueConstraint(
            "package_version_id", "logical_id", name="uq_nodes_version_logical"
        ),
        UniqueConstraint(
            "package_version_id",
            "parent_id",
            "order_no",
            name="uq_nodes_version_parent_order",
        ),
    )


class Objective(IdMixin, TimestampMixin, Base):
    __tablename__ = "objectives"

    logical_id: Mapped[str] = mapped_column(String(26))
    package_version_id: Mapped[str] = mapped_column(
        ForeignKey("package_versions.id"), index=True
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("curriculum_nodes.id"))
    code: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(128))
    definition: Mapped[str] = mapped_column(Text)
    attainment: Mapped[str] = mapped_column(Text)
    required_concepts_json: Mapped[list] = mapped_column(JSON, default=list)
    required_actions_json: Mapped[list] = mapped_column(JSON, default=list)
    allowed_variations_json: Mapped[list] = mapped_column(JSON, default=list)
    exclusions_json: Mapped[list] = mapped_column(JSON, default=list)
    match_hints_json: Mapped[Optional[list]] = mapped_column(JSON)
    source_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="active")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        UniqueConstraint(
            "package_version_id",
            "logical_id",
            name="uq_objectives_version_logical",
        ),
        UniqueConstraint(
            "package_version_id", "code", name="uq_objectives_version_code"
        ),
        Index(
            "ix_objectives_version_node_status",
            "package_version_id",
            "node_id",
            "status",
        ),
    )


class ObjectiveRelation(IdMixin, Base):
    __tablename__ = "objective_relations"

    package_version_id: Mapped[str] = mapped_column(
        ForeignKey("package_versions.id"), index=True
    )
    source_objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"))
    target_objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"))
    relation_type: Mapped[str] = mapped_column(String(24))
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "package_version_id",
            "source_objective_id",
            "target_objective_id",
            "relation_type",
        ),
    )


class Exemplar(IdMixin, TimestampMixin, Base):
    __tablename__ = "exemplars"

    logical_id: Mapped[str] = mapped_column(String(26))
    package_version_id: Mapped[str] = mapped_column(
        ForeignKey("package_versions.id"), index=True
    )
    exemplar_type: Mapped[str] = mapped_column(String(24))
    source_type: Mapped[str] = mapped_column(String(24))
    source_json: Mapped[dict] = mapped_column(JSON)
    question_text: Mapped[str] = mapped_column(Text)
    options_json: Mapped[Optional[list]] = mapped_column(JSON)
    answer_json: Mapped[Optional[Union[dict, list, str]]] = mapped_column(JSON)
    solution_text: Mapped[Optional[str]] = mapped_column(Text)
    task_signature_json: Mapped[dict] = mapped_column(JSON)
    media_json: Mapped[Optional[list]] = mapped_column(JSON)
    display_level: Mapped[str] = mapped_column(String(16), default="reference")
    status: Mapped[str] = mapped_column(String(16), default="active")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        UniqueConstraint("package_version_id", "logical_id"),
        Index(
            "ix_exemplars_version_type_status",
            "package_version_id",
            "exemplar_type",
            "status",
        ),
    )


class ExemplarObjective(IdMixin, Base):
    __tablename__ = "exemplar_objectives"

    exemplar_id: Mapped[str] = mapped_column(ForeignKey("exemplars.id"), index=True)
    objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (UniqueConstraint("exemplar_id", "objective_id", "role"),)


class ObjectiveExternalMapping(IdMixin, Base):
    __tablename__ = "objective_external_mappings"

    package_version_id: Mapped[str] = mapped_column(
        ForeignKey("package_versions.id"), index=True
    )
    objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"), index=True)
    namespace: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(128))
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("package_version_id", "namespace", "external_id"),
    )
