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
    CatalogNode,
    KnowledgeBase,
    KnowledgeBaseMapping,
    KnowledgeObject,
    KnowledgeRelation,
    KnowledgeRevision,
    RelationRevision,
    ReleaseBatch,
    ReleaseCatalogNode,
    ReleaseCurrent,
    ReleaseKnowledge,
    ReleaseMapping,
    ReleaseRelation,
    ReleaseVersion,
)
from app.models.base import utc_isoformat, utc_now


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _audit(
    session: Session, actor: str, action: str, key: str, request_id: str, kb_id: int
):
    session.add(
        AuditLog(
            actor_id=actor,
            action=action,
            entity_type="release_version",
            entity_key=key,
            affected_knowledge_base_ids=[kb_id],
            request_id=request_id,
            created_at=utc_now(),
        )
    )


def _kb(session: Session, kb_id: int) -> KnowledgeBase:
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise BusinessError("NOT_FOUND", "知识库不存在", 404)
    return kb


def _current_revision(
    session: Session, knowledge: KnowledgeObject
) -> KnowledgeRevision:
    revision = session.get(KnowledgeRevision, knowledge.latest_revision_id)
    if revision is None:
        raise BusinessError("VALIDATION_FAILED", "知识点缺少有效当前修订", 422)
    return revision


def _relation_revision(
    session: Session, relation: KnowledgeRelation
) -> RelationRevision:
    revision = session.get(RelationRevision, relation.latest_revision_id)
    if revision is None:
        raise BusinessError("VALIDATION_FAILED", "关系缺少有效当前修订", 422)
    return revision


def _cycle(revisions: list[RelationRevision]) -> bool:
    graph: dict[int, list[int]] = defaultdict(list)
    for row in revisions:
        if row.operation == "upsert" and row.relation_type == "prerequisite":
            graph[row.from_knowledge_id].append(row.to_knowledge_id)
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: int) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _candidate(session: Session, kb_id: int):
    kb = _kb(session, kb_id)
    nodes = list(
        session.scalars(
            select(CatalogNode)
            .where(
                CatalogNode.edition_id == kb.textbook_edition_id,
                CatalogNode.node_type.in_(("book", "unit")),
            )
            .order_by(CatalogNode.sort_order, CatalogNode.id)
        )
    )
    mappings = list(
        session.scalars(
            select(KnowledgeBaseMapping)
            .where(KnowledgeBaseMapping.knowledge_base_id == kb_id)
            .order_by(KnowledgeBaseMapping.id)
        )
    )
    knowledge_ids = {row.knowledge_id for row in mappings}
    knowledge = (
        list(
            session.scalars(
                select(KnowledgeObject).where(KnowledgeObject.id.in_(knowledge_ids))
            )
        )
        if knowledge_ids
        else []
    )
    errors = []
    by_id = {row.id: row for row in knowledge}
    node_ids = {row.id for row in nodes}
    for mapping in mappings:
        item = by_id.get(mapping.knowledge_id)
        if item is None:
            errors.append({"entity": mapping.id, "reason": "映射引用的知识点不存在"})
        else:
            _current_revision(session, item)
        if mapping.catalog_node_id not in node_ids:
            errors.append({"entity": mapping.id, "reason": "映射目录不属于当前教材"})
    if errors:
        raise BusinessError("VALIDATION_FAILED", "发布校验未通过", 422, errors)
    relations = []
    for relation in session.scalars(select(KnowledgeRelation)):
        revision = _relation_revision(session, relation)
        if (
            revision.operation == "upsert"
            and revision.from_knowledge_id in knowledge_ids
            and revision.to_knowledge_id in knowledge_ids
        ):
            relations.append(revision)
    return kb, nodes, mappings, knowledge, relations


def validate_knowledge_base(session: Session, kb_id: int) -> list[dict[str, Any]]:
    try:
        kb, _nodes, mappings, _knowledge, relations = _candidate(session, kb_id)
    except BusinessError as exc:
        details = exc.details
        return details if isinstance(details, list) else [{"reason": exc.message}]
    errors = []
    if not mappings:
        errors.append({"entity": str(kb.id), "reason": "知识库至少关联一个知识点"})
    if _cycle(relations):
        errors.append({"entity": "knowledge_relation", "reason": "前置关系存在循环"})
    return errors


def _next_version(session: Session, kb_id: int) -> int:
    return (
        session.scalar(
            select(func.max(ReleaseVersion.version_no)).where(
                ReleaseVersion.knowledge_base_id == kb_id
            )
        )
        or 0
    ) + 1


def _copy_snapshots(
    session: Session, release: ReleaseVersion, nodes, mappings, knowledge, relations
):
    for node in nodes:
        session.add(
            ReleaseCatalogNode(
                release_id=release.id,
                catalog_node_id=node.id,
                parent_id=node.parent_id,
                level=node.level,
                node_type=node.node_type,
                source_key=node.source_key,
                title=node.title,
                source_path=node.source_path,
                sort_order=node.sort_order,
            )
        )
    by_id = {row.id: row for row in knowledge}
    for mapping in mappings:
        item = by_id[mapping.knowledge_id]
        session.add(
            ReleaseMapping(
                release_id=release.id,
                catalog_node_id=mapping.catalog_node_id,
                knowledge_id=item.id,
                canonical_id=item.canonical_id,
            )
        )
    for item in knowledge:
        session.add(
            ReleaseKnowledge(
                release_id=release.id,
                knowledge_id=item.id,
                canonical_id=item.canonical_id,
                revision_id=_current_revision(session, item).id,
            )
        )
    for revision in relations:
        source = session.get(KnowledgeObject, revision.from_knowledge_id)
        target = session.get(KnowledgeObject, revision.to_knowledge_id)
        if source and target:
            session.add(
                ReleaseRelation(
                    release_id=release.id,
                    relation_id=revision.relation_id,
                    relation_revision_id=revision.id,
                    relation_type=revision.relation_type,
                    from_canonical_id=source.canonical_id,
                    to_canonical_id=target.canonical_id,
                    note=revision.note,
                )
            )


def release_response(release: ReleaseVersion) -> dict[str, Any]:
    return {
        "id": str(release.id),
        "knowledgeBaseId": str(release.knowledge_base_id),
        "releaseVersion": release.version_label,
        "versionNo": release.version_no,
        "releaseType": release.release_type,
        "contentHash": release.content_hash,
        "publishedBy": release.published_by,
        "publishedAt": utc_isoformat(release.published_at),
        "reason": release.reason,
    }


def publish_knowledge_base(
    session: Session, kb_id: int, actor: str, request_id: str, reason: str | None = None
) -> dict[str, Any]:
    errors = validate_knowledge_base(session, kb_id)
    if errors:
        raise BusinessError("VALIDATION_FAILED", "发布校验未通过", 422, errors)
    kb, nodes, mappings, knowledge, relations = _candidate(session, kb_id)
    base = (
        session.get(ReleaseVersion, kb.current_release_id)
        if kb.current_release_id
        else None
    )
    version_no = _next_version(session, kb_id)
    label = f"kb_{kb_id}.v{version_no}"
    now = utc_now()
    batch = ReleaseBatch(
        knowledge_base_id=kb_id,
        base_release_id=base.id if base else None,
        release_type="normal",
        release_note=reason,
        validation_status="passed",
        status="published",
        created_by=actor,
        published_by=actor,
        published_at=now,
    )
    session.add(batch)
    session.flush()
    release = ReleaseVersion(
        knowledge_base_id=kb_id,
        version_no=version_no,
        version_label=label,
        base_release_id=base.id if base else None,
        batch_id=batch.id,
        release_type="normal",
        content_hash="pending",
        published_by=actor,
        published_at=now,
        reason=reason,
    )
    session.add(release)
    session.flush()
    _copy_snapshots(session, release, nodes, mappings, knowledge, relations)
    release.content_hash = _hash(
        {
            "nodes": [row.id for row in nodes],
            "mappings": [(row.catalog_node_id, row.knowledge_id) for row in mappings],
            "knowledge": [row.id for row in knowledge],
            "relations": [row.relation_id for row in relations],
        }
    )
    current = session.get(ReleaseCurrent, kb_id)
    if current:
        current.release_id = release.id
        current.updated_at = now
    else:
        session.add(
            ReleaseCurrent(
                knowledge_base_id=kb_id, release_id=release.id, updated_at=now
            )
        )
    kb.current_release_id = release.id
    kb.status = "published"
    kb.row_version += 1
    kb.updated_by = actor
    _audit(session, actor, "release.publish", label, request_id, kb_id)
    session.commit()
    return release_response(release)


def list_releases(session: Session, kb_id: int, page_num: int = 1, page_size: int = 10):
    statement = select(ReleaseVersion).where(ReleaseVersion.knowledge_base_id == kb_id)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        session.scalars(
            statement.order_by(ReleaseVersion.version_no.desc())
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
    )
    return total, [release_response(row) for row in rows]


def get_release(
    session: Session, kb_id: int, version_label: str | None = None
) -> ReleaseVersion:
    if version_label:
        release = session.scalar(
            select(ReleaseVersion).where(
                ReleaseVersion.knowledge_base_id == kb_id,
                ReleaseVersion.version_label == version_label,
            )
        )
    else:
        current_id = _kb(session, kb_id).current_release_id
        release = session.get(ReleaseVersion, current_id) if current_id else None
    if release is None:
        raise BusinessError("NOT_FOUND", "正式版本不存在", 404)
    return release


def offline_knowledge_base(session: Session, kb_id: int, actor: str, request_id: str):
    kb = _kb(session, kb_id)
    if kb.status != "published":
        raise BusinessError("CONFLICT", "只有已发布知识库可以下线", 409)
    kb.status = "offline"
    kb.row_version += 1
    kb.updated_by = actor
    _audit(session, actor, "knowledge_base.offline", str(kb_id), request_id, kb_id)
    session.commit()
    from app.modules.catalog.service import _kb_response

    return _kb_response(session, kb)


def _copy_release_rows(
    session: Session, source: ReleaseVersion, target: ReleaseVersion
) -> None:
    for row in session.scalars(
        select(ReleaseCatalogNode).where(ReleaseCatalogNode.release_id == source.id)
    ):
        session.add(
            ReleaseCatalogNode(
                release_id=target.id,
                catalog_node_id=row.catalog_node_id,
                parent_id=row.parent_id,
                level=row.level,
                node_type=row.node_type,
                source_key=row.source_key,
                title=row.title,
                source_path=row.source_path,
                sort_order=row.sort_order,
            )
        )
    for row in session.scalars(
        select(ReleaseMapping).where(ReleaseMapping.release_id == source.id)
    ):
        session.add(
            ReleaseMapping(
                release_id=target.id,
                catalog_node_id=row.catalog_node_id,
                knowledge_id=row.knowledge_id,
                canonical_id=row.canonical_id,
            )
        )
    for row in session.scalars(
        select(ReleaseKnowledge).where(ReleaseKnowledge.release_id == source.id)
    ):
        session.add(
            ReleaseKnowledge(
                release_id=target.id,
                knowledge_id=row.knowledge_id,
                canonical_id=row.canonical_id,
                revision_id=row.revision_id,
            )
        )
    for row in session.scalars(
        select(ReleaseRelation).where(ReleaseRelation.release_id == source.id)
    ):
        session.add(
            ReleaseRelation(
                release_id=target.id,
                relation_id=row.relation_id,
                relation_revision_id=row.relation_revision_id,
                relation_type=row.relation_type,
                from_canonical_id=row.from_canonical_id,
                to_canonical_id=row.to_canonical_id,
                note=row.note,
            )
        )


def rollback_knowledge_base(
    session: Session,
    kb_id: int,
    source_version: str,
    actor: str,
    request_id: str,
    reason: str,
):
    kb = _kb(session, kb_id)
    source = get_release(session, kb_id, source_version)
    version_no = _next_version(session, kb_id)
    label = f"kb_{kb_id}.v{version_no}"
    now = utc_now()
    batch = ReleaseBatch(
        knowledge_base_id=kb_id,
        base_release_id=kb.current_release_id,
        source_release_id=source.id,
        release_type="rollback",
        release_note=reason,
        validation_status="passed",
        status="published",
        created_by=actor,
        published_by=actor,
        published_at=now,
    )
    session.add(batch)
    session.flush()
    release = ReleaseVersion(
        knowledge_base_id=kb_id,
        version_no=version_no,
        version_label=label,
        base_release_id=kb.current_release_id,
        batch_id=batch.id,
        release_type="rollback",
        content_hash=source.content_hash,
        published_by=actor,
        published_at=now,
        reason=reason,
    )
    session.add(release)
    session.flush()
    _copy_release_rows(session, source, release)
    current = session.get(ReleaseCurrent, kb_id)
    if current:
        current.release_id = release.id
        current.updated_at = now
    else:
        session.add(
            ReleaseCurrent(
                knowledge_base_id=kb_id, release_id=release.id, updated_at=now
            )
        )
    kb.current_release_id = release.id
    kb.status = "published"
    kb.row_version += 1
    kb.updated_by = actor
    _audit(session, actor, "release.rollback", label, request_id, kb_id)
    session.commit()
    return release_response(release)


def list_audit_logs(session: Session, page_num: int = 1, page_size: int = 10):
    total = session.scalar(select(func.count()).select_from(AuditLog)) or 0
    rows = list(
        session.scalars(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
    )
    return total, [
        {
            "id": row.id,
            "actorType": "admin",
            "actorId": row.actor_id,
            "action": row.action,
            "resourceType": row.entity_type,
            "resourceId": row.entity_key,
            "requestId": row.request_id,
            "createdAt": utc_isoformat(row.created_at),
        }
        for row in rows
    ]
