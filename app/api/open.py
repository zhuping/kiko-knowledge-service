from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import BusinessError
from app.core.response import success
from app.core.security import verify_open_request
from app.modules.catalog.service import list_knowledge_bases
from app.modules.release.document import release_document
from app.modules.release.service import get_release

router = APIRouter(prefix="/api/v1/open", tags=["open"])


def _content(
    db: Session,
    kb_id: int,
    release_version: str | None,
) -> tuple[dict, str]:
    from app.modules.catalog.service import get_knowledge_base

    kb = get_knowledge_base(db, kb_id)
    if kb.status == "offline" and release_version is None:
        raise BusinessError("NOT_FOUND", "当前知识库不可用", 404)
    release = get_release(db, kb_id, release_version)
    return release_document(db, release), release.version_label


@router.get("/knowledge-bases")
def open_knowledge_bases(
    request: Request,
    grade_term_code: str | None = Query(None, alias="gradeTermCode"),
    subject_code: str | None = Query(None, alias="subjectCode"),
    textbook_edition_code: str | None = Query(None, alias="textbookEditionCode"),
    db: Session = Depends(get_db),
    _client=Depends(verify_open_request),
):
    total, rows = list_knowledge_bases(
        db,
        grade_term_code,
        subject_code,
        textbook_edition_code,
        "published",
        1,
        100,
    )
    return success(
        {"total": total, "list": rows},
        request.state.request_id,
    )


@router.get("/knowledge-bases/{kb_id}/content")
def open_content(
    kb_id: int,
    request: Request,
    release_version: str | None = Query(None, alias="releaseVersion"),
    db: Session = Depends(get_db),
    _client=Depends(verify_open_request),
):
    data, version = _content(db, kb_id, release_version)
    return success(data, request.state.request_id, version)


@router.get("/knowledge-bases/{kb_id}/knowledge/{canonical_id}")
def open_knowledge(
    kb_id: int,
    canonical_id: str,
    request: Request,
    release_version: str | None = Query(None, alias="releaseVersion"),
    db: Session = Depends(get_db),
    _client=Depends(verify_open_request),
):
    data, version = _content(db, kb_id, release_version)
    item = next(
        (item for item in data["knowledge"] if item["canonicalId"] == canonical_id),
        None,
    )
    if item is None:
        raise BusinessError("NOT_FOUND", "正式版本中不存在该知识点", 404)
    return success(item, request.state.request_id, version)


@router.get("/knowledge-bases/{kb_id}/relations")
def open_relations(
    kb_id: int,
    request: Request,
    release_version: str | None = Query(None, alias="releaseVersion"),
    db: Session = Depends(get_db),
    _client=Depends(verify_open_request),
):
    data, version = _content(db, kb_id, release_version)
    return success(
        {"list": data["relations"]},
        request.state.request_id,
        version,
    )
