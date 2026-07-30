from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class GoldTestCase(IdMixin, TimestampMixin, Base):
    __tablename__ = "gold_test_cases"

    package_id: Mapped[str] = mapped_column(ForeignKey("curriculum_packages.id"))
    question_json: Mapped[dict] = mapped_column(JSON)
    scope_context_json: Mapped[Optional[dict]] = mapped_column(JSON)
    expected_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="active")


class RegressionRun(IdMixin, Base):
    __tablename__ = "regression_runs"

    package_version_id: Mapped[str] = mapped_column(ForeignKey("package_versions.id"))
    classifier_version: Mapped[str] = mapped_column(String(64))
    metrics_json: Mapped[Optional[dict]] = mapped_column(JSON)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class ImportJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "import_jobs"

    package_version_id: Mapped[str] = mapped_column(ForeignKey("package_versions.id"))
    source_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[Optional[str]] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="validated")
    preview_json: Mapped[Optional[dict]] = mapped_column(JSON)
    errors_json: Mapped[Optional[list]] = mapped_column(JSON)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128))

    __table_args__ = (UniqueConstraint("package_version_id", "source_hash"),)


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"

    actor_type: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(26))
    before_json: Mapped[Optional[dict]] = mapped_column(JSON)
    after_json: Mapped[Optional[dict]] = mapped_column(JSON)
    request_id: Mapped[Optional[str]] = mapped_column(String(26))
    created_at: Mapped[datetime] = mapped_column(DateTime)
