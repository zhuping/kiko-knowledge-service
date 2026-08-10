from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.models import (
    AuditLog,
    KnowledgeObject,
    KnowledgeRelation,
    RelationRevision,
    ReleaseRelation,
    ReleaseVersion,
)
from app.models.base import utc_now
from app.schemas.catalog import RelationCreate, RelationUpdate


def _hash(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _audit(
    session: Session,
    actor: str,
    action: str,
    entity_type: str,
    entity_key: str,
    request_id: str,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor,
            action=action,
            entity_type=entity_type,
            entity_key=entity_key,
            affected_knowledge_base_ids=[],
            request_id=request_id,
            created_at=utc_now(),
        )
    )


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


def _knowledge(session: Session, canonical_id: str) -> KnowledgeObject:
    row = session.scalar(
        select(KnowledgeObject).where(KnowledgeObject.canonical_id == canonical_id)
    )
    if row is None:
        raise BusinessError("NOT_FOUND", "关系引用的知识点不存在", 404)
    return row


def _relation_key(relation_type: str, source_id: int, target_id: int) -> str:
    if relation_type in {"parallel", "cross"}:
        source_id, target_id = sorted((source_id, target_id))
    return f"{relation_type}:{source_id}:{target_id}"


def _revision(session: Session, relation: KnowledgeRelation) -> RelationRevision:
    row = session.get(RelationRevision, relation.latest_revision_id)
    if row is None:
        raise BusinessError("INTERNAL_ERROR", "关系当前修订不存在", 500)
    return row


def _status(session: Session, relation: KnowledgeRelation) -> str:
    if relation.latest_revision_id is None:
        return "pending"
    found = session.scalar(
        select(ReleaseRelation.id).where(
            ReleaseRelation.relation_id == relation.id,
            ReleaseRelation.relation_revision_id == relation.latest_revision_id,
        )
    )
    return "published" if found else "pending"


def _formal_versions(session: Session, relation_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        select(ReleaseVersion.knowledge_base_id, ReleaseVersion.version_label)
        .join(ReleaseRelation, ReleaseRelation.release_id == ReleaseVersion.id)
        .where(ReleaseRelation.relation_id == relation_id)
        .order_by(ReleaseVersion.published_at.desc())
    ).all()
    result = []
    seen_knowledge_bases: set[int] = set()
    for kb_id, version in rows:
        if kb_id not in seen_knowledge_bases:
            seen_knowledge_bases.add(kb_id)
            result.append({"knowledgeBaseId": str(kb_id), "releaseVersion": version})
    return result


def _latest_revisions(session: Session) -> list[RelationRevision]:
    relations = list(session.scalars(select(KnowledgeRelation)))
    return [_revision(session, relation) for relation in relations]


def _active_revisions(session: Session) -> list[RelationRevision]:
    result = []
    for revision in _latest_revisions(session):
        if revision.operation == "upsert":
            result.append(revision)
    return result


def _has_cycle(session: Session, extra: RelationRevision | None = None) -> bool:
    rows = _active_revisions(session)
    if extra and extra.operation == "upsert":
        rows.append(extra)
    graph: dict[int, list[int]] = defaultdict(list)
    for row in rows:
        if row.relation_type == "prerequisite":
            graph[row.from_knowledge_id].append(row.to_knowledge_id)
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: int) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(next_node) for next_node in graph.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _relation_payload(session: Session, relation: KnowledgeRelation) -> dict[str, Any]:
    row = _revision(session, relation)
    source = session.get(KnowledgeObject, row.from_knowledge_id)
    target = session.get(KnowledgeObject, row.to_knowledge_id)
    return {
        "relationId": str(relation.id),
        "relationType": row.relation_type,
        "fromCanonicalId": source.canonical_id if source else None,
        "toCanonicalId": target.canonical_id if target else None,
        "operation": row.operation,
        "note": row.note,
        "currentFormalVersions": _formal_versions(session, relation.id),
        "status": _status(session, relation),
        "rowVersion": relation.row_version,
    }


def _new_revision(
    session: Session,
    relation: KnowledgeRelation,
    operation: str,
    relation_type: str,
    source_id: int,
    target_id: int,
    note: str | None,
    actor: str,
) -> RelationRevision:
    latest = (
        session.scalar(
            select(func.max(RelationRevision.revision_no)).where(
                RelationRevision.relation_id == relation.id
            )
        )
        or 0
    )
    value = {
        "operation": operation,
        "relation_type": relation_type,
        "from_knowledge_id": source_id,
        "to_knowledge_id": target_id,
        "note": note,
    }
    revision = RelationRevision(
        relation_id=relation.id,
        revision_no=latest + 1,
        **value,
        content_hash=_hash(value),
        created_by=actor,
    )
    had_revision = relation.latest_revision_id is not None
    session.add(revision)
    session.flush()
    relation.latest_revision_id = revision.id
    relation.row_version = relation.row_version + 1 if had_revision else 1
    return revision


def _create_edge(
    session: Session,
    source: KnowledgeObject,
    target: KnowledgeObject,
    relation_type: str,
    note: str | None,
    actor: str,
) -> KnowledgeRelation:
    if source.id == target.id:
        raise BusinessError("VALIDATION_FAILED", "知识关系不能自关联", 422)
    key = _relation_key(relation_type, source.id, target.id)
    relation = session.scalar(
        select(KnowledgeRelation).where(KnowledgeRelation.relation_key == key)
    )
    if relation is not None:
        revision = _revision(session, relation)
        if revision.operation == "delete":
            _new_revision(
                session,
                relation,
                "upsert",
                relation_type,
                source.id,
                target.id,
                note,
                actor,
            )
            return relation
        raise BusinessError("CONFLICT", "关系已存在", 409)
    relation = KnowledgeRelation(relation_key=key)
    session.add(relation)
    session.flush()
    revision = _new_revision(
        session, relation, "upsert", relation_type, source.id, target.id, note, actor
    )
    if relation_type == "prerequisite" and _has_cycle(session, revision):
        raise BusinessError("VALIDATION_FAILED", "前置关系存在循环", 422)
    return relation


def create_relation_group(
    session: Session, data: RelationCreate, actor: str, request_id: str
) -> list[dict[str, Any]]:
    source = _knowledge(session, data.canonical_id)
    created = []
    for relation_type, target_ids in (
        ("prerequisite", data.prerequisite_canonical_ids),
        ("parallel", data.parallel_canonical_ids),
        ("cross", data.cross_canonical_ids),
    ):
        for target_id in dict.fromkeys(target_ids):
            target = _knowledge(session, target_id)
            relation = _create_edge(
                session,
                target if relation_type == "prerequisite" else source,
                source if relation_type == "prerequisite" else target,
                relation_type,
                data.note,
                actor,
            )
            created.append(_relation_payload(session, relation))
    if not created:
        raise BusinessError("VALIDATION_FAILED", "至少创建一条知识关联", 422)
    for item in created:
        _audit(
            session,
            actor,
            "relation.create",
            "knowledge_relation",
            item["relationId"],
            request_id,
        )
    session.commit()
    return created


def get_relation(session: Session, relation_id: int) -> KnowledgeRelation:
    relation = session.get(KnowledgeRelation, relation_id)
    if relation is None:
        raise BusinessError("NOT_FOUND", "知识关联不存在", 404)
    return relation


def patch_relation(
    session: Session,
    relation_id: int,
    data: RelationUpdate,
    actor: str,
    request_id: str,
) -> dict[str, Any]:
    relation = get_relation(session, relation_id)
    if relation.row_version != data.row_version:
        raise BusinessError("CONFLICT", "关系已被其他管理员修改，请刷新后重试", 409)
    current = _revision(session, relation)
    if data.operation == "delete":
        _new_revision(
            session,
            relation,
            "delete",
            current.relation_type,
            current.from_knowledge_id,
            current.to_knowledge_id,
            current.note,
            actor,
        )
    else:
        relation_type = data.relation_type or current.relation_type
        source_id = (
            _knowledge(session, data.from_canonical_id).id
            if data.from_canonical_id
            else current.from_knowledge_id
        )
        target_id = (
            _knowledge(session, data.to_canonical_id).id
            if data.to_canonical_id
            else current.to_knowledge_id
        )
        if source_id == target_id:
            raise BusinessError("VALIDATION_FAILED", "知识关系不能自关联", 422)
        new_key = _relation_key(relation_type, source_id, target_id)
        duplicate = session.scalar(
            select(KnowledgeRelation).where(
                KnowledgeRelation.relation_key == new_key,
                KnowledgeRelation.id != relation.id,
            )
        )
        if duplicate and _revision(session, duplicate).operation == "upsert":
            raise BusinessError("CONFLICT", "关系已存在", 409)
        relation.relation_key = new_key
        revision = _new_revision(
            session,
            relation,
            "upsert",
            relation_type,
            source_id,
            target_id,
            data.note if data.note is not None else current.note,
            actor,
        )
        if relation_type == "prerequisite" and _has_cycle(session, revision):
            raise BusinessError("VALIDATION_FAILED", "前置关系存在循环", 422)
    _audit(
        session,
        actor,
        "relation.update",
        "knowledge_relation",
        str(relation_id),
        request_id,
    )
    session.commit()
    return _relation_payload(session, relation)


def delete_relation(
    session: Session, relation_id: int, row_version: int, actor: str, request_id: str
) -> None:
    relation = get_relation(session, relation_id)
    if relation.row_version != row_version:
        raise BusinessError("CONFLICT", "关系已被其他管理员修改，请刷新后重试", 409)
    if session.scalar(
        select(ReleaseRelation.id).where(ReleaseRelation.relation_id == relation_id)
    ):
        current = _revision(session, relation)
        _new_revision(
            session,
            relation,
            "delete",
            current.relation_type,
            current.from_knowledge_id,
            current.to_knowledge_id,
            current.note,
            actor,
        )
    else:
        session.query(RelationRevision).filter(
            RelationRevision.relation_id == relation_id
        ).delete(synchronize_session=False)
        session.delete(relation)
    _audit(
        session,
        actor,
        "relation.delete",
        "knowledge_relation",
        str(relation_id),
        request_id,
    )
    session.commit()


def revert_relation(
    session: Session, relation_id: int, actor: str, request_id: str
) -> dict[str, Any]:
    relation = get_relation(session, relation_id)
    current = _revision(session, relation)
    formal = session.scalar(
        select(RelationRevision)
        .join(
            ReleaseRelation, ReleaseRelation.relation_revision_id == RelationRevision.id
        )
        .join(ReleaseVersion, ReleaseVersion.id == ReleaseRelation.release_id)
        .where(ReleaseRelation.relation_id == relation_id)
        .order_by(ReleaseVersion.published_at.desc())
    )
    if formal is None or formal.id == current.id:
        raise BusinessError("CONFLICT", "当前没有可撤销的草稿修改", 409)
    relation.latest_revision_id = formal.id
    relation.row_version += 1
    _audit(
        session,
        actor,
        "relation.draft_revert",
        "knowledge_relation",
        str(relation_id),
        request_id,
    )
    session.commit()
    return _relation_payload(session, relation)


def _group_for_knowledge(session: Session, knowledge_id: int) -> dict[str, list[str]]:
    rows = _active_revisions(session)
    by_id = {
        row.id: row.canonical_id for row in session.scalars(select(KnowledgeObject))
    }
    groups = {"prerequisites": [], "successors": [], "parallel": [], "cross": []}
    for row in rows:
        if row.relation_type == "prerequisite":
            if row.to_knowledge_id == knowledge_id:
                groups["prerequisites"].append(by_id[row.from_knowledge_id])
            elif row.from_knowledge_id == knowledge_id:
                groups["successors"].append(by_id[row.to_knowledge_id])
        elif row.relation_type in {"parallel", "cross"}:
            if row.from_knowledge_id == knowledge_id:
                groups[row.relation_type].append(by_id[row.to_knowledge_id])
            elif row.to_knowledge_id == knowledge_id:
                groups[row.relation_type].append(by_id[row.from_knowledge_id])
    return groups


def relation_group_response(
    session: Session, knowledge: KnowledgeObject
) -> dict[str, Any]:
    from app.modules.knowledge.service import knowledge_response

    groups = _group_for_knowledge(session, knowledge.id)
    details = knowledge_response(session, knowledge)
    relation_rows = [
        row
        for row in _latest_revisions(session)
        if knowledge.id in {row.from_knowledge_id, row.to_knowledge_id}
    ]
    versions = [
        version
        for row in relation_rows
        for version in _formal_versions(session, row.relation_id)
    ]
    pending = any(
        knowledge.id in {row.from_knowledge_id, row.to_knowledge_id}
        and _status(session, session.get(KnowledgeRelation, row.relation_id))
        == "pending"
        for row in _latest_revisions(session)
    )
    return {
        "canonicalId": knowledge.canonical_id,
        "knowledgeName": details["knowledgeName"],
        "gradeTermCode": details["gradeTermCode"],
        **groups,
        "currentFormalVersions": versions,
        "status": "pending" if pending else "published",
        "rowVersion": knowledge.row_version,
    }
