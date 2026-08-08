from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Job(TimestampMixin, Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    error_file: Mapped[Optional[str]] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class ApiClient(TimestampMixin, Base):
    __tablename__ = "api_client"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(String(512), nullable=False)
    allowed_scopes: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer, default=1000, nullable=False
    )


class ApiNonce(Base):
    __tablename__ = "api_nonce"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_key: Mapped[str] = mapped_column(String(128), nullable=False)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    __table_args__ = (UniqueConstraint("app_key", "nonce"),)


class ApiRateBucket(Base):
    __tablename__ = "api_rate_bucket"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_key: Mapped[str] = mapped_column(String(128), nullable=False)
    bucket_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    __table_args__ = (UniqueConstraint("app_key", "bucket_minute"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(40))
    entity_key: Mapped[Optional[str]] = mapped_column(String(128))
    before_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    after_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    affected_knowledge_base_ids: Mapped[list[int]] = mapped_column(
        JSON, default=list, nullable=False
    )
    request_id: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(nullable=False)
