from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import BusinessError
from app.core.response import success
from app.core.security import AdminIdentity, admin_identity, require_admin
from app.modules.import_export.service import (
    commit_import_job,
    create_import_job,
    get_job,
    job_response,
    list_job_errors,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _request_id(request: Request) -> str:
    return request.state.request_id


def _page(total: int, page_num: int, page_size: int, rows: list) -> dict:
    return {"total": total, "pageNum": page_num, "pageSize": page_size, "list": rows}


@router.post("/imports")
async def upload_import(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    job = create_import_job(
        db, file.filename or "", await file.read(), actor, _request_id(request)
    )
    return success(job_response(job), _request_id(request))


@router.post("/imports/{job_id}/commit")
def commit_import(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        job_response(commit_import_job(db, job_id, actor, _request_id(request))),
        _request_id(request),
    )


@router.get("/jobs/{job_id}")
def job_status(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(job_response(get_job(db, job_id)), _request_id(request))


@router.get("/jobs/{job_id}/errors")
def job_errors(
    job_id: int,
    request: Request,
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, rows = list_job_errors(db, job_id, page_num, page_size)
    return success(_page(total, page_num, page_size, rows), _request_id(request))


@router.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    get_job(db, job_id)
    raise BusinessError("CONFLICT", "当前导入任务不可重试", 409)


@router.get("/files/{file_id}")
def get_file(
    file_id: str,
    _identity: AdminIdentity = Depends(admin_identity),
):
    raise BusinessError("NOT_FOUND", f"文件不存在：{file_id}", 404)
