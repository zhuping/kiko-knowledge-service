from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class ClassificationTask(IdMixin, TimestampMixin, Base):
    __tablename__ = "classification_tasks"

    client_app_id: Mapped[str] = mapped_column(ForeignKey("client_apps.id"), index=True)
    client_request_id: Mapped[str] = mapped_column(String(128))
    source_question_id: Mapped[Optional[str]] = mapped_column(String(128))
    active_package_version_id: Mapped[str] = mapped_column(
        ForeignKey("package_versions.id")
    )
    request_json: Mapped[dict] = mapped_column(JSON)
    question_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="received")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    failure_code: Mapped[Optional[str]] = mapped_column(String(64))
    failure_message: Mapped[Optional[str]] = mapped_column(String(512))

    __table_args__ = (
        UniqueConstraint("client_app_id", "client_request_id"),
        Index("ix_tasks_status_created", "status", "created_at"),
        Index("ix_tasks_hash_version", "question_hash", "active_package_version_id"),
    )


class ClassificationTaskPackage(Base):
    __tablename__ = "classification_task_packages"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("classification_tasks.id"), primary_key=True
    )
    package_version_id: Mapped[str] = mapped_column(
        ForeignKey("package_versions.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ClassificationCandidate(IdMixin, Base):
    __tablename__ = "classification_candidates"

    task_id: Mapped[str] = mapped_column(ForeignKey("classification_tasks.id"))
    objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"))
    rank_no: Mapped[int] = mapped_column(Integer)
    retrieval_score: Mapped[Decimal] = mapped_column(Numeric(6, 5))
    feature_score_json: Mapped[dict] = mapped_column(JSON)
    matched_exemplar_ids_json: Mapped[list] = mapped_column(JSON)
    conflicts_json: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("task_id", "rank_no", name="uq_candidates_task_rank"),
        UniqueConstraint(
            "task_id", "objective_id", name="uq_candidates_task_objective"
        ),
    )


class ClassificationResult(IdMixin, Base):
    __tablename__ = "classification_results"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("classification_tasks.id"), unique=True
    )
    primary_objective_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("objectives.id")
    )
    match_type: Mapped[str] = mapped_column(String(16))
    scope_status: Mapped[str] = mapped_column(String(20))
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    requires_confirmation: Mapped[bool] = mapped_column(Boolean)
    reason_summary: Mapped[str] = mapped_column(String(1000))
    task_signature_json: Mapped[Optional[dict]] = mapped_column(JSON)
    classifier_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ClassificationResultObjective(Base):
    __tablename__ = "classification_result_objectives"

    result_id: Mapped[str] = mapped_column(
        ForeignKey("classification_results.id"), primary_key=True
    )
    objective_id: Mapped[str] = mapped_column(
        ForeignKey("objectives.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    rank_no: Mapped[int] = mapped_column(Integer)


class ClassificationEvidence(IdMixin, Base):
    __tablename__ = "classification_evidence"

    result_id: Mapped[str] = mapped_column(ForeignKey("classification_results.id"))
    exemplar_id: Mapped[str] = mapped_column(ForeignKey("exemplars.id"))
    objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"))
    reason_summary: Mapped[str] = mapped_column(String(500))
    display_level: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ClassificationFeedback(IdMixin, TimestampMixin, Base):
    __tablename__ = "classification_feedback"

    classification_id: Mapped[str] = mapped_column(
        ForeignKey("classification_tasks.id"), index=True
    )
    client_app_id: Mapped[str] = mapped_column(ForeignKey("client_apps.id"))
    feedback_request_id: Mapped[str] = mapped_column(String(128))
    confirmed: Mapped[bool] = mapped_column(Boolean)
    correction_json: Mapped[Optional[dict]] = mapped_column(JSON)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="submitted")

    __table_args__ = (UniqueConstraint("client_app_id", "feedback_request_id"),)


class FeedbackReview(IdMixin, Base):
    __tablename__ = "feedback_reviews"

    feedback_id: Mapped[str] = mapped_column(
        ForeignKey("classification_feedback.id"), unique=True
    )
    reviewer_subject: Mapped[str] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(16))
    action_type: Mapped[str] = mapped_column(String(24))
    review_note: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime)
