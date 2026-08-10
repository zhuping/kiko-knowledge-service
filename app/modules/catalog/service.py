from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.models import (
    AuditLog,
    CatalogNode,
    KnowledgeBase,
    KnowledgeBaseMapping,
    KnowledgeObject,
    ReleaseVersion,
    TextbookEdition,
)
from app.models.base import utc_now
from app.schemas.catalog import (
    GRADE_TERM_LABELS,
    SUBJECT_LABELS,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    MappingCreate,
)


def _hash(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _page(session: Session, statement, page_num: int, page_size: int):
    total = (
        session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        or 0
    )
    rows = list(
        session.scalars(statement.offset((page_num - 1) * page_size).limit(page_size))
    )
    return total, rows


def _audit(
    session: Session,
    actor: str,
    action: str,
    entity_type: str,
    entity_key: str,
    request_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    knowledge_base_ids: list[int] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor,
            action=action,
            entity_type=entity_type,
            entity_key=entity_key,
            before_json=before,
            after_json=after,
            affected_knowledge_base_ids=knowledge_base_ids or [],
            request_id=request_id,
            created_at=utc_now(),
        )
    )


def _check_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise BusinessError("CONFLICT", "数据已被其他管理员修改，请刷新后重试", 409)


def _edition(session: Session, edition_code: str) -> TextbookEdition:
    edition = session.scalar(
        select(TextbookEdition).where(TextbookEdition.edition_code == edition_code)
    )
    if edition is None:
        raise BusinessError("NOT_FOUND", "教材版本不存在", 404)
    return edition


def _ensure_edition(session: Session, edition_code: str) -> TextbookEdition:
    edition = session.scalar(
        select(TextbookEdition).where(TextbookEdition.edition_code == edition_code)
    )
    if edition:
        return edition
    match = re.fullmatch(r"pep_math_2024_g([12])_t([12])", edition_code)
    if not match:
        raise BusinessError("NOT_FOUND", "教材版本不存在", 404)
    grade_term = f"g{match.group(1)}_t{match.group(2)}"
    edition = TextbookEdition(
        edition_code=edition_code,
        edition_name=f"人教版2024数学{GRADE_TERM_LABELS[grade_term]}",
        subject="math",
        grade_term=grade_term,
        version_year=2024,
    )
    session.add(edition)
    session.flush()
    return edition


def seed_textbook_editions(session: Session) -> None:
    if session.scalar(select(TextbookEdition.id).limit(1)):
        return
    for grade_term, label in GRADE_TERM_LABELS.items():
        session.add(
            TextbookEdition(
                edition_code=f"pep_math_2024_{grade_term}",
                edition_name=f"人教版2024数学{label}",
                subject="math",
                grade_term=grade_term,
                version_year=2024,
            )
        )
    session.commit()


def _kb_response(session: Session, kb: KnowledgeBase) -> dict[str, Any]:
    edition = session.get(TextbookEdition, kb.textbook_edition_id)
    mapping_count = (
        session.scalar(
            select(func.count())
            .select_from(KnowledgeBaseMapping)
            .where(KnowledgeBaseMapping.knowledge_base_id == kb.id)
        )
        or 0
    )
    release = (
        session.get(ReleaseVersion, kb.current_release_id)
        if kb.current_release_id
        else None
    )
    return {
        "id": str(kb.id),
        "name": kb.name,
        "gradeTermCode": kb.grade_term,
        "gradeTermName": GRADE_TERM_LABELS.get(kb.grade_term, kb.grade_term),
        "subjectCode": kb.subject,
        "subjectName": SUBJECT_LABELS.get(kb.subject, kb.subject),
        "textbookEditionCode": edition.edition_code if edition else None,
        "textbookEditionName": edition.edition_name if edition else None,
        "status": kb.status,
        "currentReleaseVersion": release.version_label if release else None,
        "knowledgeCount": mapping_count,
        "updatedAt": kb.updated_at.isoformat(),
        "rowVersion": kb.row_version,
    }


def create_knowledge_base(
    session: Session,
    data: KnowledgeBaseCreate,
    actor: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    edition = _ensure_edition(session, data.textbook_edition_code)
    if (
        edition.subject != data.subject_code
        or edition.grade_term != data.grade_term_code
    ):
        raise BusinessError("VALIDATION_FAILED", "学科、年级与教材版本不匹配", 422)
    kb = KnowledgeBase(
        name=data.name,
        grade_term=data.grade_term_code,
        subject=data.subject_code,
        textbook_edition_id=edition.id,
        created_by=actor,
        updated_by=actor,
    )
    session.add(kb)
    session.flush()
    _audit(
        session,
        actor,
        "knowledge_base.create",
        "knowledge_base",
        str(kb.id),
        request_id,
    )
    session.commit()
    return _kb_response(session, kb)


def get_knowledge_base(session: Session, kb_id: int) -> KnowledgeBase:
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise BusinessError("NOT_FOUND", "知识库不存在", 404)
    return kb


def list_knowledge_bases(
    session: Session,
    grade_term: str | None = None,
    subject: str | None = None,
    edition_code: str | None = None,
    status: str | None = None,
    page_num: int = 1,
    page_size: int = 10,
    name: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    statement = select(KnowledgeBase)
    if name:
        statement = statement.where(KnowledgeBase.name.ilike(f"%{name}%"))
    if grade_term:
        statement = statement.where(KnowledgeBase.grade_term == grade_term)
    if subject:
        statement = statement.where(KnowledgeBase.subject == subject)
    if status:
        statement = statement.where(KnowledgeBase.status == status)
    if edition_code:
        statement = statement.join(TextbookEdition).where(
            TextbookEdition.edition_code == edition_code
        )
    total, rows = _page(
        session, statement.order_by(KnowledgeBase.id.desc()), page_num, page_size
    )
    return total, [_kb_response(session, row) for row in rows]


def update_knowledge_base(
    session: Session, kb_id: int, data: KnowledgeBaseUpdate, actor: str, request_id: str
) -> dict[str, Any]:
    kb = get_knowledge_base(session, kb_id)
    _check_version(kb.row_version, data.row_version)
    before = _kb_response(session, kb)
    if data.name is not None:
        kb.name = data.name
    kb.row_version += 1
    kb.updated_by = actor
    _audit(
        session,
        actor,
        "knowledge_base.update",
        "knowledge_base",
        str(kb.id),
        request_id,
        before,
        _kb_response(session, kb),
        [kb.id],
    )
    session.commit()
    return _kb_response(session, kb)


def delete_knowledge_base(
    session: Session, kb_id: int, actor: str, request_id: str
) -> None:
    kb = get_knowledge_base(session, kb_id)
    if kb.current_release_id or kb.status != "pending":
        raise BusinessError("CONFLICT", "已发布或已下线知识库不能删除", 409)
    if session.scalar(
        select(KnowledgeBaseMapping.id).where(
            KnowledgeBaseMapping.knowledge_base_id == kb_id
        )
    ):
        raise BusinessError("CONFLICT", "知识库存在目录映射，不能删除", 409)
    _audit(
        session,
        actor,
        "knowledge_base.delete",
        "knowledge_base",
        str(kb_id),
        request_id,
    )
    session.delete(kb)
    session.commit()


def list_textbook_editions(
    session: Session,
    subject: str | None = None,
    grade_term: str | None = None,
    page_num: int = 1,
    page_size: int = 100,
) -> tuple[int, list[dict[str, Any]]]:
    statement = select(TextbookEdition).where(TextbookEdition.status == "active")
    if subject:
        statement = statement.where(TextbookEdition.subject == subject)
    if grade_term:
        statement = statement.where(TextbookEdition.grade_term == grade_term)
    total, rows = _page(
        session, statement.order_by(TextbookEdition.edition_code), page_num, page_size
    )
    return total, [_edition_response(row) for row in rows]


def _edition_response(edition: TextbookEdition) -> dict[str, Any]:
    return {
        "key": edition.edition_code,
        "value": edition.edition_name,
        "subjectCode": edition.subject,
        "subjectName": SUBJECT_LABELS.get(edition.subject, edition.subject),
        "gradeTermCode": edition.grade_term,
        "gradeTermName": GRADE_TERM_LABELS.get(edition.grade_term, edition.grade_term),
        "versionYear": edition.version_year,
        "status": edition.status,
    }


def get_textbook_edition(session: Session, edition_code: str) -> dict[str, Any]:
    return _edition_response(_edition(session, edition_code))


def catalog_tree(session: Session, edition_code: str) -> list[dict[str, Any]]:
    edition = _edition(session, edition_code)
    rows = list(
        session.scalars(
            select(CatalogNode)
            .where(CatalogNode.edition_id == edition.id)
            .order_by(CatalogNode.sort_order, CatalogNode.id)
        )
    )
    children: dict[int | None, list[CatalogNode]] = {}
    for row in rows:
        children.setdefault(row.parent_id, []).append(row)

    def build(row: CatalogNode) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "key": row.source_key,
            "sourceKey": row.source_key,
            "title": row.title,
            "level": row.level,
            "nodeType": row.node_type,
            "sourcePath": row.source_path,
            "sortOrder": row.sort_order,
            "children": [build(child) for child in children.get(row.id, [])],
        }

    return [build(row) for row in children.get(None, [])]


def _mapping_response(
    session: Session, mapping: KnowledgeBaseMapping
) -> dict[str, Any]:
    from app.modules.knowledge.service import knowledge_response

    knowledge = session.get(KnowledgeObject, mapping.knowledge_id)
    node = session.get(CatalogNode, mapping.catalog_node_id)
    if knowledge is None or node is None:
        raise BusinessError("INTERNAL_ERROR", "目录映射数据不完整", 500)
    kb = session.get(KnowledgeBase, mapping.knowledge_base_id)
    item = knowledge_response(session, knowledge)
    return {
        "mappingId": str(mapping.id),
        "catalogNodeId": str(node.id),
        "catalogNodeTitle": node.title,
        **{
            key: item[key]
            for key in (
                "canonicalId",
                "knowledgeName",
                "knowledgeType",
                "gradeTermCode",
                "scope",
                "ocrSignals",
                "exerciseSignature",
                "currentFormalVersions",
                "status",
            )
        },
        "rowVersion": kb.row_version if kb else None,
    }


def list_mappings(
    session: Session, kb_id: int, catalog_node_id: int | None = None
) -> list[dict[str, Any]]:
    statement = select(KnowledgeBaseMapping).where(
        KnowledgeBaseMapping.knowledge_base_id == kb_id
    )
    if catalog_node_id:
        statement = statement.where(
            KnowledgeBaseMapping.catalog_node_id == catalog_node_id
        )
    return [
        _mapping_response(session, row)
        for row in session.scalars(statement.order_by(KnowledgeBaseMapping.id))
    ]


def create_mapping(
    session: Session, kb_id: int, data: MappingCreate, actor: str, request_id: str
) -> dict[str, Any]:
    kb = get_knowledge_base(session, kb_id)
    _check_version(kb.row_version, data.row_version)
    node = session.get(CatalogNode, data.catalog_node_id)
    from app.modules.knowledge.service import get_knowledge

    knowledge = get_knowledge(session, data.canonical_id)
    if node is None or node.edition_id != kb.textbook_edition_id:
        raise BusinessError("VALIDATION_FAILED", "目录节点不属于当前教材", 422)
    if session.scalar(
        select(KnowledgeBaseMapping.id).where(
            KnowledgeBaseMapping.knowledge_base_id == kb_id,
            KnowledgeBaseMapping.catalog_node_id == node.id,
            KnowledgeBaseMapping.knowledge_id == knowledge.id,
        )
    ):
        raise BusinessError("CONFLICT", "该知识点已经关联到当前目录", 409)
    mapping = KnowledgeBaseMapping(
        knowledge_base_id=kb_id,
        catalog_node_id=node.id,
        knowledge_id=knowledge.id,
        created_by=actor,
    )
    session.add(mapping)
    kb.row_version += 1
    kb.updated_by = actor
    session.flush()
    _audit(
        session,
        actor,
        "knowledge_base.mapping_create",
        "knowledge_base_mapping",
        str(mapping.id),
        request_id,
        knowledge_base_ids=[kb_id],
    )
    session.commit()
    return _mapping_response(session, mapping)


def delete_mapping(
    session: Session,
    kb_id: int,
    mapping_id: int,
    row_version: int,
    actor: str,
    request_id: str,
) -> None:
    kb = get_knowledge_base(session, kb_id)
    _check_version(kb.row_version, row_version)
    mapping = session.get(KnowledgeBaseMapping, mapping_id)
    if mapping is None or mapping.knowledge_base_id != kb_id:
        raise BusinessError("NOT_FOUND", "知识库映射不存在", 404)
    session.delete(mapping)
    kb.row_version += 1
    kb.updated_by = actor
    _audit(
        session,
        actor,
        "knowledge_base.mapping_delete",
        "knowledge_base_mapping",
        str(mapping_id),
        request_id,
        knowledge_base_ids=[kb_id],
    )
    session.commit()
