from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import DbSession
from app.core.errors import ApiError
from app.core.time import utcnow
from app.models import AdminUser, AdminUserRole, ClientApp

ALL_ROLES = {"viewer", "editor", "reviewer", "publisher", "admin"}


@dataclass(frozen=True)
class AdminContext:
    subject: str
    grants: frozenset[tuple[str, str | None]]

    @property
    def roles(self) -> set[str]:
        return {role for role, _package_id in self.grants}


def digest_secret(secret: str) -> str:
    return hmac.new(
        settings.api_key_pepper.encode(), secret.encode(), hashlib.sha256
    ).hexdigest()


def issue_api_key() -> tuple[str, str, str]:
    key_id = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
    secret = secrets.token_urlsafe(32)
    return key_id, secret, f"kh_live_{key_id}.{secret}"


def _parse_api_key(value: str) -> tuple[str, str]:
    if not value.startswith("kh_live_") or "." not in value:
        raise ApiError(401, "INVALID_API_KEY", "调用凭证无效")
    public, secret = value.removeprefix("kh_live_").split(".", 1)
    if not public or len(secret) < 32:
        raise ApiError(401, "INVALID_API_KEY", "调用凭证无效")
    return public, secret


def get_client_app(
    db: Session = DbSession, authorization: str | None = Header(default=None)
) -> ClientApp:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "INVALID_API_KEY", "缺少调用凭证")
    key_id, secret = _parse_api_key(authorization[7:])
    app = db.scalar(select(ClientApp).where(ClientApp.key_id == key_id))
    valid = app and hmac.compare_digest(app.secret_digest, digest_secret(secret))
    if not valid or app.status != "active":
        raise ApiError(401, "INVALID_API_KEY", "调用凭证无效")
    if app.expires_at and app.expires_at <= utcnow():
        raise ApiError(401, "INVALID_API_KEY", "调用凭证已过期")
    return app


def get_admin_context(
    db: Session = DbSession,
    x_admin_subject: str | None = Header(default=None),
    x_admin_roles: str | None = Header(default=None),
    x_authenticated_subject: str | None = Header(default=None),
) -> AdminContext:
    if settings.environment in {"development", "test"} and settings.local_admin_enabled:
        subject = x_admin_subject or "local-admin"
        roles = {
            item.strip().lower()
            for item in (x_admin_roles or ",".join(ALL_ROLES)).split(",")
            if item.strip().lower() in ALL_ROLES
        }
        return AdminContext(subject, frozenset((role, None) for role in roles))
    if not x_authenticated_subject:
        raise ApiError(401, "ACCESS_DENIED", "缺少可信管理身份")
    user = db.scalar(
        select(AdminUser).where(
            AdminUser.subject == x_authenticated_subject, AdminUser.status == "active"
        )
    )
    if not user:
        raise ApiError(403, "ACCESS_DENIED", "管理身份未授权")
    grants = db.execute(
        select(AdminUserRole.role, AdminUserRole.package_id).where(
            AdminUserRole.admin_user_id == user.id
        )
    ).all()
    return AdminContext(user.subject, frozenset(grants))


ClientAppDependency = Depends(get_client_app)
AdminDependency = Depends(get_admin_context)


def require_role(
    actor: AdminContext, *roles: str, package_id: str | None = None
) -> None:
    if not any(
        (role, None) in actor.grants or (role, package_id) in actor.grants
        for role in roles
    ):
        raise ApiError(403, "ACCESS_DENIED", "当前角色无权执行此操作")


def key_expired(expires_at: datetime | None) -> bool:
    return bool(expires_at and expires_at <= utcnow())
