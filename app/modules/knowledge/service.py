from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.models import (
    AuditLog,
    KnowledgeBase,
    KnowledgeBaseMapping,
    KnowledgeObject,
    KnowledgeRevision,
    RelationRevision,
    ReleaseKnowledge,
    ReleaseVersion,
    TextbookEdition,
)
from app.models.base import utc_now
from app.schemas.catalog import KnowledgeCreate, KnowledgeSearch, KnowledgeUpdate

CANONICAL_ID_WIDTH = 8
CANONICAL_ID = re.compile(r"^1\d{7}$")
CANONICAL_ID_MIN = 10_000_000
CANONICAL_ID_SPACE = 10_000_000


def _hash(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _audit(
    session: Session, actor: str, action: str, key: str, request_id: str
) -> None:
    session.add(
        AuditLog(
            actor_id=actor,
            action=action,
            entity_type="knowledge_object",
            entity_key=key,
            affected_knowledge_base_ids=[],
            request_id=request_id,
            created_at=utc_now(),
        )
    )


def _check_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise BusinessError("CONFLICT", "数据已被其他管理员修改，请刷新后重试", 409)


def _revision_payload(revision: KnowledgeRevision | None) -> dict[str, Any] | None:
    if revision is None:
        return None
    return {
        "knowledgeName": revision.name,
        "knowledgeType": revision.type,
        "gradeTermCode": revision.grade_term,
        "scope": revision.scope,
        "ocrSignals": revision.ocr_signals or [],
        "exerciseSignature": revision.exercise_signature,
        "revisionNo": revision.revision_no,
    }


def _latest_revision(session: Session, knowledge: KnowledgeObject) -> KnowledgeRevision:
    revision = session.get(KnowledgeRevision, knowledge.latest_revision_id)
    if revision is None:
        raise BusinessError("INTERNAL_ERROR", "知识点当前修订不存在", 500)
    return revision


def _formal_revision(session: Session, knowledge_id: int) -> KnowledgeRevision | None:
    return session.scalar(
        select(KnowledgeRevision)
        .join(ReleaseKnowledge, ReleaseKnowledge.revision_id == KnowledgeRevision.id)
        .join(ReleaseVersion, ReleaseVersion.id == ReleaseKnowledge.release_id)
        .where(ReleaseKnowledge.knowledge_id == knowledge_id)
        .order_by(ReleaseVersion.published_at.desc())
    )


def _formal_versions(session: Session, knowledge_id: int) -> list[dict[str, str]]:
    rows = session.execute(
        select(ReleaseVersion.knowledge_base_id, ReleaseVersion.version_label)
        .join(ReleaseKnowledge, ReleaseKnowledge.release_id == ReleaseVersion.id)
        .where(ReleaseKnowledge.knowledge_id == knowledge_id)
        .order_by(ReleaseVersion.published_at.desc())
    ).all()
    seen_knowledge_bases: set[int] = set()
    result = []
    for kb_id, version in rows:
        if kb_id not in seen_knowledge_bases:
            seen_knowledge_bases.add(kb_id)
            result.append({"knowledgeBaseId": str(kb_id), "releaseVersion": version})
    return result


def _knowledge_base_mappings(
    session: Session, knowledge_ids: set[int]
) -> dict[int, list[dict[str, str]]]:
    if not knowledge_ids:
        return {}
    rows = session.execute(
        select(
            KnowledgeBaseMapping.knowledge_id,
            KnowledgeBase.id,
            KnowledgeBase.name,
            TextbookEdition.edition_code,
            TextbookEdition.edition_name,
        )
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeBaseMapping.knowledge_base_id)
        .join(TextbookEdition, TextbookEdition.id == KnowledgeBase.textbook_edition_id)
        .where(KnowledgeBaseMapping.knowledge_id.in_(knowledge_ids))
        .order_by(KnowledgeBaseMapping.knowledge_id, KnowledgeBase.id)
    ).all()
    result: dict[int, list[dict[str, str]]] = {}
    seen: set[tuple[int, int]] = set()
    for (
        knowledge_id,
        knowledge_base_id,
        knowledge_base_name,
        edition_code,
        edition_name,
    ) in rows:
        key = (knowledge_id, knowledge_base_id)
        if key in seen:
            continue
        seen.add(key)
        result.setdefault(knowledge_id, []).append(
            {
                "knowledgeBaseId": str(knowledge_base_id),
                "knowledgeBaseName": knowledge_base_name,
                "textbookEditionCode": edition_code,
                "textbookEditionName": edition_name,
            }
        )
    return result


def knowledge_status(session: Session, knowledge: KnowledgeObject) -> str:
    published = session.scalar(
        select(ReleaseKnowledge.id).where(
            ReleaseKnowledge.knowledge_id == knowledge.id,
            ReleaseKnowledge.revision_id == knowledge.latest_revision_id,
        )
    )
    return "published" if published else "pending"


def knowledge_response(
    session: Session,
    knowledge: KnowledgeObject,
    mapping_context: dict[int, list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    current = _latest_revision(session, knowledge)
    formal = _formal_revision(session, knowledge.id)
    knowledge_base_mappings = (
        mapping_context.get(knowledge.id, [])
        if mapping_context is not None
        else _knowledge_base_mappings(session, {knowledge.id}).get(knowledge.id, [])
    )
    return {
        "canonicalId": knowledge.canonical_id,
        **(_revision_payload(current) or {}),
        "knowledgeBaseMappings": knowledge_base_mappings,
        "currentFormalVersions": _formal_versions(session, knowledge.id),
        "status": knowledge_status(session, knowledge),
        "rowVersion": knowledge.row_version,
        "latestFormal": _revision_payload(formal),
    }


def _knowledge_statement(data: KnowledgeSearch):
    statement = select(KnowledgeObject)
    if data.canonical_id:
        statement = statement.where(KnowledgeObject.canonical_id == data.canonical_id)
    if data.keyword:
        pattern = f"%{data.keyword}%"
        statement = statement.join(
            KnowledgeRevision,
            KnowledgeRevision.id == KnowledgeObject.latest_revision_id,
        ).where(
            or_(
                KnowledgeObject.canonical_id.ilike(pattern),
                KnowledgeRevision.name.ilike(pattern),
            )
        )
    elif any((data.grade_term_code, data.knowledge_type, data.scope)):
        statement = statement.join(
            KnowledgeRevision,
            KnowledgeRevision.id == KnowledgeObject.latest_revision_id,
        )
    if data.grade_term_code:
        statement = statement.where(
            KnowledgeRevision.grade_term == data.grade_term_code
        )
    if data.knowledge_type:
        statement = statement.where(KnowledgeRevision.type == data.knowledge_type)
    if data.scope:
        statement = statement.where(KnowledgeRevision.scope == data.scope)
    if data.subject_code:
        statement = statement.where(
            select(KnowledgeBaseMapping.id)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == KnowledgeBaseMapping.knowledge_base_id,
            )
            .join(
                TextbookEdition, TextbookEdition.id == KnowledgeBase.textbook_edition_id
            )
            .where(
                TextbookEdition.subject == data.subject_code,
                KnowledgeBaseMapping.knowledge_id == KnowledgeObject.id,
            )
            .exists()
        )
    if data.textbook_edition_code:
        statement = statement.where(
            select(KnowledgeBaseMapping.id)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == KnowledgeBaseMapping.knowledge_base_id,
            )
            .join(
                TextbookEdition, TextbookEdition.id == KnowledgeBase.textbook_edition_id
            )
            .where(
                TextbookEdition.edition_code == data.textbook_edition_code,
                KnowledgeBaseMapping.knowledge_id == KnowledgeObject.id,
            )
            .exists()
        )
    if data.knowledge_base_id:
        statement = statement.where(
            select(KnowledgeBaseMapping.id)
            .where(
                KnowledgeBaseMapping.knowledge_base_id == data.knowledge_base_id,
                KnowledgeBaseMapping.knowledge_id == KnowledgeObject.id,
            )
            .exists()
        )
    return statement


def list_knowledge(
    session: Session, data: KnowledgeSearch
) -> tuple[int, list[dict[str, Any]]]:
    if data.candidate_for_knowledge_base_id:
        knowledge_base = session.get(
            KnowledgeBase, data.candidate_for_knowledge_base_id
        )
        if knowledge_base is None:
            raise BusinessError("NOT_FOUND", "知识库不存在", 404)
        edition = session.get(TextbookEdition, knowledge_base.textbook_edition_id)
        if edition is None:
            raise BusinessError("INTERNAL_ERROR", "知识库教材版本不存在", 500)
        if data.subject_code and data.subject_code != knowledge_base.subject:
            raise BusinessError("VALIDATION_FAILED", "学科与知识库不一致", 422)
        if (
            data.textbook_edition_code
            and data.textbook_edition_code != edition.edition_code
        ):
            raise BusinessError("VALIDATION_FAILED", "教材版本与知识库不一致", 422)
        if data.grade_term_code and data.grade_term_code != knowledge_base.grade_term:
            raise BusinessError("VALIDATION_FAILED", "年级/学期与知识库不一致", 422)
        data = data.model_copy(
            update={
                "grade_term_code": knowledge_base.grade_term,
                "subject_code": None,
                "textbook_edition_code": None,
                "knowledge_base_id": None,
            }
        )
    statement = _knowledge_statement(data).order_by(KnowledgeObject.id)
    if data.status:
        # ponytail: V1 datasets are small; normalize status in application code
        # until indexing matters.
        all_rows = list(session.scalars(statement))
        rows = [
            row for row in all_rows if knowledge_status(session, row) == data.status
        ]
        total = len(rows)
        start = (data.page_num - 1) * data.page_size
        rows = rows[start : start + data.page_size]
    else:
        total = (
            session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = list(
            session.scalars(
                statement.offset((data.page_num - 1) * data.page_size).limit(
                    data.page_size
                )
            )
        )
    mapping_context = _knowledge_base_mappings(session, {row.id for row in rows})
    return total, [knowledge_response(session, row, mapping_context) for row in rows]


def _next_revision(session: Session, knowledge_id: int) -> int:
    return (
        session.scalar(
            select(func.max(KnowledgeRevision.revision_no)).where(
                KnowledgeRevision.knowledge_id == knowledge_id
            )
        )
        or 0
    ) + 1


def _new_canonical_id(session: Session) -> str:
    for _ in range(32):
        value = CANONICAL_ID_MIN + secrets.randbelow(CANONICAL_ID_SPACE)
        candidate = f"{value:0{CANONICAL_ID_WIDTH}d}"
        if not session.scalar(
            select(KnowledgeObject.id).where(KnowledgeObject.canonical_id == candidate)
        ):
            return candidate
    raise BusinessError("ID_EXHAUSTED", "暂时无法生成唯一知识点 ID", 409)


def _create_revision(
    session: Session, knowledge: KnowledgeObject, data: dict[str, Any], actor: str
) -> KnowledgeRevision:
    normalized = {
        "name": data["name"],
        "type": data["type"],
        "grade_term": data["grade_term"],
        "scope": data["scope"],
        "ocr_signals": data.get("ocr_signals") or [],
        "exercise_signature": data.get("exercise_signature"),
    }
    revision = KnowledgeRevision(
        knowledge_id=knowledge.id,
        revision_no=_next_revision(session, knowledge.id),
        **normalized,
        content_hash=_hash(normalized),
        created_by=actor,
    )
    session.add(revision)
    session.flush()
    knowledge.latest_revision_id = revision.id
    return revision


def create_knowledge(
    session: Session, data: KnowledgeCreate, actor: str, request_id: str
) -> dict[str, Any]:
    canonical_id = data.canonical_id or _new_canonical_id(session)
    if not CANONICAL_ID.fullmatch(canonical_id):
        raise BusinessError("PARAM_INVALID", "canonicalId 格式无效", 400)
    if session.scalar(
        select(KnowledgeObject).where(KnowledgeObject.canonical_id == canonical_id)
    ):
        raise BusinessError("CONFLICT", "canonicalId 已存在", 409)
    knowledge = KnowledgeObject(
        canonical_id=canonical_id, created_by=actor, updated_by=actor
    )
    session.add(knowledge)
    session.flush()
    _create_revision(
        session,
        knowledge,
        {
            "name": data.knowledge_name,
            "type": data.knowledge_type,
            "grade_term": data.grade_term_code,
            "scope": data.scope,
            "ocr_signals": data.ocr_signals,
            "exercise_signature": data.exercise_signature,
        },
        actor,
    )
    _audit(session, actor, "knowledge.create", canonical_id, request_id)
    session.commit()
    return knowledge_response(session, knowledge)


def get_knowledge(session: Session, canonical_id: str) -> KnowledgeObject:
    knowledge = session.scalar(
        select(KnowledgeObject).where(KnowledgeObject.canonical_id == canonical_id)
    )
    if knowledge is None:
        raise BusinessError("NOT_FOUND", "知识点不存在", 404)
    return knowledge


def update_knowledge(
    session: Session,
    canonical_id: str,
    data: KnowledgeUpdate,
    actor: str,
    request_id: str,
) -> dict[str, Any]:
    knowledge = get_knowledge(session, canonical_id)
    _check_version(knowledge.row_version, data.row_version)
    current = _latest_revision(session, knowledge)
    values = {
        "name": data.knowledge_name
        if data.knowledge_name is not None
        else current.name,
        "type": data.knowledge_type or current.type,
        "grade_term": data.grade_term_code or current.grade_term,
        "scope": data.scope or current.scope,
        "ocr_signals": data.ocr_signals
        if data.ocr_signals is not None
        else current.ocr_signals,
        "exercise_signature": data.exercise_signature
        if data.exercise_signature is not None
        else current.exercise_signature,
    }
    if values != {
        "name": current.name,
        "type": current.type,
        "grade_term": current.grade_term,
        "scope": current.scope,
        "ocr_signals": current.ocr_signals or [],
        "exercise_signature": current.exercise_signature,
    }:
        _create_revision(session, knowledge, values, actor)
    knowledge.row_version += 1
    knowledge.updated_by = actor
    _audit(session, actor, "knowledge.update", canonical_id, request_id)
    session.commit()
    return knowledge_response(session, knowledge)


def revert_knowledge(
    session: Session, canonical_id: str, actor: str, request_id: str
) -> dict[str, Any]:
    knowledge = get_knowledge(session, canonical_id)
    formal = _formal_revision(session, knowledge.id)
    if formal is None or formal.id == knowledge.latest_revision_id:
        raise BusinessError("CONFLICT", "当前没有可撤销的草稿修改", 409)
    knowledge.latest_revision_id = formal.id
    knowledge.row_version += 1
    knowledge.updated_by = actor
    _audit(session, actor, "knowledge.draft_revert", canonical_id, request_id)
    session.commit()
    return knowledge_response(session, knowledge)


def delete_knowledge(
    session: Session, canonical_id: str, row_version: int, actor: str, request_id: str
) -> None:
    knowledge = get_knowledge(session, canonical_id)
    _check_version(knowledge.row_version, row_version)
    if session.scalar(
        select(ReleaseKnowledge.id).where(ReleaseKnowledge.knowledge_id == knowledge.id)
    ):
        raise BusinessError("CONFLICT", "已正式发布的知识点不能删除", 409)
    if session.scalar(
        select(KnowledgeBaseMapping.id).where(
            KnowledgeBaseMapping.knowledge_id == knowledge.id
        )
    ):
        raise BusinessError("CONFLICT", "已被知识库引用的知识点不能删除", 409)
    if session.scalar(
        select(RelationRevision.id).where(
            (RelationRevision.from_knowledge_id == knowledge.id)
            | (RelationRevision.to_knowledge_id == knowledge.id)
        )
    ):
        raise BusinessError("CONFLICT", "已存在知识关联，不能删除", 409)
    session.query(KnowledgeRevision).filter(
        KnowledgeRevision.knowledge_id == knowledge.id
    ).delete(synchronize_session=False)
    session.delete(knowledge)
    _audit(session, actor, "knowledge.delete", canonical_id, request_id)
    session.commit()
