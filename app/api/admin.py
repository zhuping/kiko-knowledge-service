from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.response import success
from app.core.security import AdminIdentity, admin_identity, require_admin
from app.models import KnowledgeObject, RelationRevision
from app.modules.catalog.service import (
    catalog_tree,
    create_knowledge_base,
    create_mapping,
    delete_knowledge_base,
    delete_mapping,
    get_knowledge_base,
    get_textbook_edition,
    list_knowledge_bases,
    list_mappings,
    list_textbook_editions,
    update_knowledge_base,
)
from app.modules.knowledge.service import (
    create_knowledge,
    delete_knowledge,
    get_knowledge,
    knowledge_response,
    list_knowledge,
    revert_knowledge,
    update_knowledge,
)
from app.modules.relation.query import list_relations
from app.modules.relation.service import (
    create_relation_group,
    delete_relation,
    get_relation,
    patch_relation,
    relation_group_response,
    revert_relation,
)
from app.schemas.catalog import (
    KnowledgeBaseCreate,
    KnowledgeBaseStatus,
    KnowledgeBaseUpdate,
    KnowledgeCreate,
    KnowledgeSearch,
    KnowledgeUpdate,
    MappingCreate,
    RelationCreate,
    RelationSearch,
    RelationUpdate,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _request_id(request: Request) -> str:
    return request.state.request_id


def _page(total: int, page_num: int, page_size: int, rows: list) -> dict:
    return {
        "total": total,
        "pageNum": page_num,
        "pageSize": page_size,
        "list": rows,
    }


@router.get("/me")
def current_user(request: Request, identity: AdminIdentity = Depends(admin_identity)):
    return success(
        {
            "userId": identity.user_id,
            "displayName": identity.display_name,
            "roles": ["admin"],
            "permissions": [
                "knowledge:read",
                "knowledge:write",
                "mapping:write",
                "relation:write",
                "release:write",
                "audit:read",
            ],
        },
        _request_id(request),
    )


@router.get("/knowledge-bases")
def knowledge_bases(
    request: Request,
    grade_term_code: str | None = Query(None, alias="gradeTermCode"),
    subject_code: str | None = Query(None, alias="subjectCode"),
    textbook_edition_code: str | None = Query(None, alias="textbookEditionCode"),
    status: KnowledgeBaseStatus | None = None,
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, rows = list_knowledge_bases(
        db,
        grade_term_code,
        subject_code,
        textbook_edition_code,
        status,
        page_num,
        page_size,
    )
    return success(_page(total, page_num, page_size, rows), _request_id(request))


@router.post("/knowledge-bases")
def create_kb(
    payload: KnowledgeBaseCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        create_knowledge_base(db, payload, actor, _request_id(request)),
        _request_id(request),
    )


@router.get("/knowledge-bases/{kb_id}")
def get_kb(
    kb_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    from app.modules.catalog.service import _kb_response

    return success(
        _kb_response(db, get_knowledge_base(db, kb_id)), _request_id(request)
    )


@router.patch("/knowledge-bases/{kb_id}")
def patch_kb(
    kb_id: int,
    payload: KnowledgeBaseUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        update_knowledge_base(db, kb_id, payload, actor, _request_id(request)),
        _request_id(request),
    )


@router.delete("/knowledge-bases/{kb_id}")
def remove_kb(
    kb_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    delete_knowledge_base(db, kb_id, actor, _request_id(request))
    return success({"deleted": True}, _request_id(request))


@router.get("/textbook-editions")
def textbook_editions(
    request: Request,
    subject_code: str | None = Query(None, alias="subjectCode"),
    grade_term_code: str | None = Query(None, alias="gradeTermCode"),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(100, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    total, rows = list_textbook_editions(
        db, subject_code, grade_term_code, page_num, page_size
    )
    return success(_page(total, page_num, page_size, rows), _request_id(request))


@router.get("/textbook-editions/{edition_code}/catalog")
def textbook_catalog(
    edition_code: str,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(catalog_tree(db, edition_code), _request_id(request))


@router.get("/textbook-editions/{edition_code}")
def textbook_edition_detail(
    edition_code: str,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(get_textbook_edition(db, edition_code), _request_id(request))


@router.get("/knowledge-bases/{kb_id}/mappings")
def mappings(
    kb_id: int,
    request: Request,
    catalog_node_id: int | None = Query(None, alias="catalogNodeId"),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    get_knowledge_base(db, kb_id)
    return success(list_mappings(db, kb_id, catalog_node_id), _request_id(request))


@router.post("/knowledge-bases/{kb_id}/mappings")
def add_mapping(
    kb_id: int,
    payload: MappingCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        create_mapping(db, kb_id, payload, actor, _request_id(request)),
        _request_id(request),
    )


@router.delete("/knowledge-bases/{kb_id}/mappings/{mapping_id}")
def remove_mapping(
    kb_id: int,
    mapping_id: int,
    request: Request,
    row_version: int = Query(..., alias="rowVersion"),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    delete_mapping(db, kb_id, mapping_id, row_version, actor, _request_id(request))
    return success({"deleted": True}, _request_id(request))


@router.get("/knowledge")
def knowledge_list(
    request: Request,
    keyword: str | None = None,
    canonical_id: str | None = Query(None, alias="canonicalId"),
    grade_term_code: str | None = Query(None, alias="gradeTermCode"),
    textbook_edition_code: str | None = Query(None, alias="textbookEditionCode"),
    knowledge_type: str | None = Query(None, alias="knowledgeType"),
    scope: str | None = None,
    knowledge_base_id: int | None = Query(None, alias="knowledgeBaseId"),
    status: str | None = None,
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    data = KnowledgeSearch(
        keyword=keyword,
        canonical_id=canonical_id,
        grade_term_code=grade_term_code,
        textbook_edition_code=textbook_edition_code,
        knowledge_type=knowledge_type,
        scope=scope,
        knowledge_base_id=knowledge_base_id,
        status=status,
        page_num=page_num,
        page_size=page_size,
    )
    total, rows = list_knowledge(db, data)
    return success(_page(total, page_num, page_size, rows), _request_id(request))


@router.post("/knowledge")
def add_knowledge(
    payload: KnowledgeCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        create_knowledge(db, payload, actor, _request_id(request)),
        _request_id(request),
    )


@router.get("/knowledge/{canonical_id}")
def knowledge_detail(
    canonical_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(
        knowledge_response(db, get_knowledge(db, canonical_id)), _request_id(request)
    )


@router.patch("/knowledge/{canonical_id}")
def edit_knowledge(
    canonical_id: str,
    payload: KnowledgeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        update_knowledge(db, canonical_id, payload, actor, _request_id(request)),
        _request_id(request),
    )


@router.delete("/knowledge/{canonical_id}")
def remove_knowledge(
    canonical_id: str,
    request: Request,
    row_version: int = Query(..., alias="rowVersion"),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    delete_knowledge(db, canonical_id, row_version, actor, _request_id(request))
    return success({"deleted": True}, _request_id(request))


@router.post("/knowledge/{canonical_id}/draft:revert")
def restore_knowledge(
    canonical_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        revert_knowledge(db, canonical_id, actor, _request_id(request)),
        _request_id(request),
    )


@router.get("/relations")
def relation_list(
    request: Request,
    canonical_id: str | None = Query(None, alias="canonicalId"),
    knowledge_name: str | None = Query(None, alias="knowledgeName"),
    grade_term_code: str | None = Query(None, alias="gradeTermCode"),
    knowledge_type: str | None = Query(None, alias="knowledgeType"),
    knowledge_base_id: int | None = Query(None, alias="knowledgeBaseId"),
    status: str | None = None,
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    data = RelationSearch(
        canonical_id=canonical_id,
        knowledge_name=knowledge_name,
        grade_term_code=grade_term_code,
        knowledge_type=knowledge_type,
        knowledge_base_id=knowledge_base_id,
        status=status,
        page_num=page_num,
        page_size=page_size,
    )
    total, rows = list_relations(db, data)
    return success(_page(total, page_num, page_size, rows), _request_id(request))


@router.post("/relations")
def add_relation(
    payload: RelationCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        create_relation_group(db, payload, actor, _request_id(request)),
        _request_id(request),
    )


@router.get("/relations/{relation_id}")
def relation_detail(
    relation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _identity: AdminIdentity = Depends(admin_identity),
):
    return success(
        relation_group_response(
            db, get_knowledge(db, _relation_main_canonical(db, relation_id))
        ),
        _request_id(request),
    )


def _relation_main_canonical(db: Session, relation_id: int) -> str:
    relation = get_relation(db, relation_id)
    revision = db.get(RelationRevision, relation.latest_revision_id)
    source = db.get(KnowledgeObject, revision.from_knowledge_id)
    return source.canonical_id


@router.patch("/relations/{relation_id}")
def edit_relation(
    relation_id: int,
    payload: RelationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        patch_relation(db, relation_id, payload, actor, _request_id(request)),
        _request_id(request),
    )


@router.delete("/relations/{relation_id}")
def remove_relation(
    relation_id: int,
    request: Request,
    row_version: int = Query(..., alias="rowVersion"),
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    delete_relation(db, relation_id, row_version, actor, _request_id(request))
    return success({"deleted": True}, _request_id(request))


@router.post("/relations/{relation_id}/draft:revert")
def restore_relation(
    relation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
):
    return success(
        revert_relation(db, relation_id, actor, _request_id(request)),
        _request_id(request),
    )
