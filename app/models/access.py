from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class AdminUser(IdMixin, TimestampMixin, Base):
    __tablename__ = "admin_users"

    subject: Mapped[str] = mapped_column(String(128), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="active")


class AdminUserRole(IdMixin, Base):
    __tablename__ = "admin_user_roles"

    admin_user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"))
    role: Mapped[str] = mapped_column(String(24))
    package_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("curriculum_packages.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (UniqueConstraint("admin_user_id", "role", "package_id"),)


class ClientApp(IdMixin, TimestampMixin, Base):
    __tablename__ = "client_apps"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    key_id: Mapped[str] = mapped_column(String(64), unique=True)
    secret_digest: Mapped[str] = mapped_column(String(64))
    allowed_package_ids_json: Mapped[Optional[list]] = mapped_column(JSON)
    allowed_media_hosts_json: Mapped[Optional[list]] = mapped_column(JSON)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[str] = mapped_column(String(16), default="active")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
