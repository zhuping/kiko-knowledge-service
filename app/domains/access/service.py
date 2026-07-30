from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import (
    AdminContext,
    digest_secret,
    issue_api_key,
    require_role,
)
from app.domains.audit.service import record
from app.models import ClientApp
from app.repositories import catalog as catalog_repo
from app.schemas.admin import ClientAppCreate


def _validate_packages(db: Session, package_ids: list[str] | None) -> None:
    if package_ids is None:
        return
    found = {item.id for item in catalog_repo.list_packages(db, package_ids)}
    if found != set(package_ids):
        raise ApiError(400, "INVALID_REQUEST", "授权知识包不存在")


def create_client_app(
    db: Session, actor: AdminContext, data: ClientAppCreate
) -> tuple[ClientApp, str]:
    require_role(actor, "admin")
    _validate_packages(db, data.allowed_package_ids)
    key_id, secret, token = issue_api_key()
    client = ClientApp(
        code=data.code,
        name=data.name,
        key_id=key_id,
        secret_digest=digest_secret(secret),
        allowed_package_ids_json=data.allowed_package_ids,
        allowed_media_hosts_json=[
            item.strip().lower() for item in data.allowed_media_hosts or []
        ],
        rate_limit_per_minute=data.rate_limit_per_minute,
    )
    db.add(client)
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action="client_app.create",
        resource_type="client_app",
        resource_id=client.id,
        after={"code": client.code, "key_id": key_id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "RESOURCE_CONFLICT", "调用方编码已存在") from exc
    return client, token


def rotate_key(
    db: Session, actor: AdminContext, client_id: str
) -> tuple[ClientApp, str]:
    require_role(actor, "admin")
    client = db.get(ClientApp, client_id)
    if not client:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "调用方不存在")
    old_key_id = client.key_id
    key_id, secret, token = issue_api_key()
    client.key_id = key_id
    client.secret_digest = digest_secret(secret)
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action="client_app.rotate_key",
        resource_type="client_app",
        resource_id=client.id,
        before={"key_id": old_key_id},
        after={"key_id": key_id},
    )
    db.commit()
    return client, token


def set_status(
    db: Session, actor: AdminContext, client_id: str, status: str
) -> ClientApp:
    require_role(actor, "admin")
    client = db.get(ClientApp, client_id)
    if not client:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "调用方不存在")
    before = client.status
    client.status = status
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action=f"client_app.{status}",
        resource_type="client_app",
        resource_id=client.id,
        before={"status": before},
        after={"status": status},
    )
    db.commit()
    return client
