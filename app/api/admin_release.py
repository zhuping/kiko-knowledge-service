from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.response import success
from app.core.security import AdminIdentity, admin_identity, require_admin
from app.modules.release.document import release_diff, release_document
from app.modules.release.service import (
    get_release,
    list_audit_logs,
    list_releases,
    offline_knowledge_base,
    publish_knowledge_base,
    release_response,
    rollback_knowledge_base,
    validate_knowledge_base,
)
from app.schemas.release import PublishRequest, RollbackRequest

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _request_id(request: Request) -> str:
    return request.state.request_id


def _page(total: int, page_num: int, page_size: int, rows: list) -> dict:
    return {"total": total, "pageNum": page_num, "pageSize": page_size, "list": rows}


@router.post("/knowledge-bases/{kb_id}/publish:validate")
def validate_publish(
    kb_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    errors = validate_knowledge_base(db, kb_id)
    return success({"passed": not errors, "errors": errors}, _request_id(request))


@router.post("/knowledge-bases/{kb_id}/publish")
def publish(
    kb_id: int,
    request: Request,
    payload: PublishRequest | None = None,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    reason = payload.reason if payload else None
    release = publish_knowledge_base(db, kb_id, actor, _request_id(request), reason)
    return success(release, _request_id(request), release["releaseVersion"])


@router.get("/knowledge-bases/{kb_id}/releases")
def release_list(
    kb_id: int,
    request: Request,
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, rows = list_releases(db, kb_id, page_num, page_size)
    return success(_page(total, page_num, page_size, rows), _request_id(request))


@router.get("/knowledge-bases/{kb_id}/releases/{version}")
def release_detail(
    kb_id: int,
    version: str,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    release = get_release(db, kb_id, version)
    return success(
        {
            "release": release_response(release),
            "content": release_document(db, release),
        },
        _request_id(request),
        version,
    )


@router.get("/knowledge-bases/{kb_id}/releases/{version}/diff")
def release_difference(
    kb_id: int,
    version: str,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(release_diff(db, kb_id, version), _request_id(request), version)


@router.post("/knowledge-bases/{kb_id}/releases/{version}:rollback")
def rollback(
    kb_id: int,
    version: str,
    request: Request,
    payload: RollbackRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    release = rollback_knowledge_base(
        db, kb_id, version, actor, _request_id(request), payload.reason
    )
    return success(release, _request_id(request), release["releaseVersion"])


@router.post("/knowledge-bases/{kb_id}/offline")
def offline(
    kb_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        offline_knowledge_base(db, kb_id, actor, _request_id(request)),
        _request_id(request),
    )


@router.get("/audit-logs")
def audit_logs(
    request: Request,
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, rows = list_audit_logs(db, page_num, page_size)
    return success(_page(total, page_num, page_size, rows), _request_id(request))
