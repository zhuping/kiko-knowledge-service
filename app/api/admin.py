from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.response import success
from app.core.security import (
    AdminIdentity,
    admin_identity,
    require_admin,
    require_roles,
)
from app.modules.catalog.service import (
    apply_relation_batch,
    attach_knowledge,
    create_knowledge,
    create_mapping,
    create_node,
    create_policy_mapping,
    get_knowledge,
    knowledge_response,
    list_knowledge,
    move_knowledge_node,
    move_node,
    page_mappings,
    page_policy_mappings,
    page_relation_group,
    relation_groups,
    tree_payload,
    update_knowledge,
    update_node,
    update_status_batch,
)
from app.modules.import_export.service import (
    commit_import_job,
    create_import_job,
    get_job,
    job_response,
    list_job_errors,
)
from app.modules.release.service import (
    create_batch,
    list_audit_logs,
    list_release_changes,
    list_releases,
    publish_batch,
    validate_batch,
)
from app.schemas.catalog import (
    CatalogKnowledgeAttach,
    CatalogNodeCreate,
    CatalogNodeMove,
    CatalogNodeUpdate,
    GradeTerm,
    KnowledgeCreate,
    KnowledgeNodeMove,
    KnowledgeScope,
    KnowledgeStatus,
    KnowledgeStatusBatch,
    KnowledgeType,
    KnowledgeUpdate,
    PolicyMappingCreate,
    RelationBatch,
    TextbookMappingCreate,
)
from app.schemas.release import ReleaseBatchCreate

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def request_id(request: Request) -> str:
    return request.state.request_id


def page_response(total: int, page_num: int, page_size: int, items: list):
    return {"total": total, "pageNum": page_num, "pageSize": page_size, "list": items}


@router.get("/me")
def current_user(request: Request, identity: AdminIdentity = Depends(admin_identity)):
    permissions = sorted(
        {permission for role in identity.roles for permission in _permissions(role)}
    )
    return success(
        {
            "userId": identity.user_id,
            "displayName": identity.display_name,
            "roles": list(identity.roles),
            "permissions": permissions,
        },
        request_id(request),
    )


@router.post("/imports")
async def create_import(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    job = create_import_job(
        db,
        file.filename or "",
        await file.read(),
        actor,
        request_id(request),
    )
    return success(job_response(job), request_id(request))


@router.get("/jobs/{job_id}")
def job_status(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(job_response(get_job(db, job_id)), request_id(request))


@router.get("/jobs/{job_id}/errors")
def job_errors(
    job_id: int,
    request: Request,
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, items = list_job_errors(db, job_id, page_num, page_size)
    return success(
        page_response(total, page_num, page_size, items), request_id(request)
    )


@router.post("/imports/{job_id}/commit")
def commit_import(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    job = commit_import_job(db, job_id, actor, request_id(request))
    return success(job_response(job), request_id(request))


def _permissions(role: str) -> tuple[str, ...]:
    from app.core.security import ROLE_PERMISSIONS

    return ROLE_PERMISSIONS[role]


@router.get("/catalog/tree")
def catalog_tree(
    request: Request,
    edition_code: str = Query("pep_math_2024_63", alias="editionCode"),
    space_code: str = Query("default", alias="spaceCode"),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(tree_payload(db, space_code, edition_code), request_id(request))


@router.post("/catalog/nodes")
def create_catalog_node(
    payload: CatalogNodeCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    node = create_node(db, payload, actor)
    return success(
        {
            "id": node.id,
            "parentId": node.parent_id,
            "level": node.level,
            "nodeType": node.node_type,
            "title": node.title,
            "sortOrder": node.sort_order,
            "status": node.status,
            "rowVersion": node.row_version,
        },
        request_id(request),
    )


@router.patch("/catalog/nodes/{node_id}")
def patch_catalog_node(
    node_id: int,
    payload: CatalogNodeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    node = update_node(db, node_id, payload, actor)
    return success(
        {
            "id": node.id,
            "title": node.title,
            "status": node.status,
            "rowVersion": node.row_version,
        },
        request_id(request),
    )


@router.post("/catalog/nodes/{node_id}/move")
def move_catalog_node(
    node_id: int,
    payload: CatalogNodeMove,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    node = move_node(db, node_id, payload, actor)
    return success(
        {"id": node.id, "sortOrder": node.sort_order, "rowVersion": node.row_version},
        request_id(request),
    )


@router.post("/catalog/knowledge-nodes")
def attach_catalog_knowledge(
    payload: CatalogKnowledgeAttach,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    item = attach_knowledge(db, payload, actor)
    return success(
        {
            "id": item.id,
            "groupNodeId": item.group_node_id,
            "rowVersion": item.row_version,
        },
        request_id(request),
    )


@router.post("/catalog/knowledge-nodes/{node_id}/move")
def move_catalog_knowledge(
    node_id: int,
    payload: KnowledgeNodeMove,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    item = move_knowledge_node(db, node_id, payload, actor)
    return success(
        {"id": item.id, "sortOrder": item.sort_order, "rowVersion": item.row_version},
        request_id(request),
    )


@router.get("/knowledge")
def knowledge_list(
    request: Request,
    keyword: str | None = Query(None),
    canonical_id: str | None = Query(None, alias="canonicalId"),
    grade_term: GradeTerm | None = Query(None, alias="gradeTerm"),
    knowledge_type: KnowledgeType | None = Query(None, alias="knowledgeType"),
    scope: KnowledgeScope | None = Query(None),
    status: KnowledgeStatus | None = Query(None),
    group_node_id: int | None = Query(None, alias="groupNodeId"),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, items = list_knowledge(
        db,
        keyword=keyword,
        canonical_id=canonical_id,
        grade_term=grade_term,
        knowledge_type=knowledge_type,
        scope=scope,
        status=status,
        group_node_id=group_node_id,
        page_num=page_num,
        page_size=page_size,
    )
    return success(
        page_response(total, page_num, page_size, items),
        request_id(request),
    )


@router.post("/knowledge")
def create_knowledge_object(
    payload: KnowledgeCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        knowledge_response(db, create_knowledge(db, payload, actor)),
        request_id(request),
    )


@router.get("/knowledge/{canonical_id}")
def get_knowledge_object(
    canonical_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(
        knowledge_response(db, get_knowledge(db, canonical_id)), request_id(request)
    )


@router.patch("/knowledge/{canonical_id}")
def patch_knowledge_object(
    canonical_id: str,
    payload: KnowledgeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        knowledge_response(db, update_knowledge(db, canonical_id, payload, actor)),
        request_id(request),
    )


@router.post("/knowledge/status:batch")
def patch_knowledge_status(
    payload: KnowledgeStatusBatch,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        [
            knowledge_response(db, item)
            for item in update_status_batch(db, payload, actor)
        ],
        request_id(request),
    )


@router.get("/relations/{canonical_id}")
def get_relations(
    canonical_id: str,
    request: Request,
    group: Literal["prerequisites", "successors", "parallel", "cross"] | None = Query(
        None
    ),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    if group is None:
        return success(
            {"canonicalId": canonical_id, **relation_groups(db, canonical_id)},
            request_id(request),
        )
    total, items = page_relation_group(db, canonical_id, group, page_num, page_size)
    return success(
        page_response(total, page_num, page_size, items), request_id(request)
    )


@router.post("/relations/batch")
def create_knowledge_relations(
    payload: RelationBatch,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    relations = apply_relation_batch(db, payload, actor)
    return success(
        {"created": len(relations), "ids": [item.id for item in relations]},
        request_id(request),
    )


@router.get("/textbook-mappings")
def textbook_mappings(
    request: Request,
    edition_code: str | None = Query(None, alias="editionCode"),
    canonical_id: str | None = Query(None, alias="canonicalId"),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, items = page_mappings(db, edition_code, canonical_id, page_num, page_size)
    return success(
        page_response(total, page_num, page_size, items), request_id(request)
    )


@router.post("/textbook-mappings/batch")
def create_textbook_mappings(
    payload: list[TextbookMappingCreate],
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    mappings = [create_mapping(db, item, actor) for item in payload]
    return success(
        {"created": len(mappings), "ids": [item.id for item in mappings]},
        request_id(request),
    )


@router.get("/policy-mappings")
def policy_mappings(
    request: Request,
    canonical_id: str | None = Query(None, alias="canonicalId"),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, items = page_policy_mappings(db, canonical_id, page_num, page_size)
    return success(
        page_response(total, page_num, page_size, items), request_id(request)
    )


@router.post("/policy-mappings/batch")
def create_policy_mappings(
    payload: list[PolicyMappingCreate],
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    mappings = [create_policy_mapping(db, item, actor) for item in payload]
    return success(
        {"created": len(mappings), "ids": [item.id for item in mappings]},
        request_id(request),
    )


@router.post("/release-batches")
def create_release_batch(
    payload: ReleaseBatchCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    batch = create_batch(
        db,
        payload.space_code,
        payload.version_label,
        payload.release_note,
        payload.change_log_ids,
        actor,
    )
    return success(
        {
            "id": batch.id,
            "versionLabel": batch.version_label,
            "validationStatus": batch.validation_status,
            "status": batch.status,
        },
        request_id(request),
    )


@router.post("/release-batches/{batch_id}/validate")
def validate_release_batch(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(require_roles("editor", "publisher", "admin")),
):
    errors = validate_batch(db, batch_id)
    return success({"passed": not errors, "errors": errors}, request_id(request))


@router.post("/release-batches/{batch_id}/publish")
def publish_release_batch(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_roles("publisher", "admin")),
):
    version = publish_batch(db, batch_id, actor.user_id)
    return success(
        {
            "versionLabel": version.version_label,
            "contentHash": version.content_hash,
            "publishedAt": version.published_at.isoformat(),
        },
        request_id(request),
        version.version_label,
    )


@router.get("/releases")
def releases(
    request: Request,
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, rows = list_releases(db, page_num, page_size)
    return success(
        page_response(
            total,
            page_num,
            page_size,
            [
                {
                    "versionLabel": item.version_label,
                    "releaseType": item.release_type,
                    "contentHash": item.content_hash,
                    "publishedBy": item.published_by,
                    "publishedAt": item.published_at.isoformat(),
                }
                for item in rows
            ],
        ),
        request_id(request),
    )


@router.get("/release-changes")
def release_changes(
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(list_release_changes(db), request_id(request))


@router.get("/audit-logs")
def audit_logs(
    request: Request,
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, items = list_audit_logs(db, page_num, page_size)
    return success(
        page_response(total, page_num, page_size, items), request_id(request)
    )
