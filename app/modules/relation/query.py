from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.models import (
    KnowledgeObject,
    KnowledgeRelation,
    KnowledgeRevision,
    RelationRevision,
    ReleaseRelation,
    ReleaseVersion,
)
from app.modules.knowledge.service import _knowledge_statement
from app.schemas.catalog import KnowledgeSearch, RelationSearch


def _pending_knowledge_ids(session: Session) -> set[int]:
    formal = (
        select(ReleaseRelation.id)
        .where(
            ReleaseRelation.relation_id == KnowledgeRelation.id,
            ReleaseRelation.relation_revision_id
            == KnowledgeRelation.latest_revision_id,
        )
        .exists()
    )
    all_knowledge_ids = set(session.scalars(select(KnowledgeObject.id)))
    rows = session.execute(
        select(
            RelationRevision.from_knowledge_id,
            RelationRevision.to_knowledge_id,
        )
        .join(
            KnowledgeRelation,
            RelationRevision.id == KnowledgeRelation.latest_revision_id,
        )
        .where(~formal)
    ).all()
    pending_ids = {
        knowledge_id for row in rows for knowledge_id in row if knowledge_id is not None
    }
    formal_rows = session.execute(
        select(
            RelationRevision.from_knowledge_id,
            RelationRevision.to_knowledge_id,
        )
        .join(
            KnowledgeRelation,
            RelationRevision.id == KnowledgeRelation.latest_revision_id,
        )
        .where(formal)
    ).all()
    formal_ids = {
        knowledge_id
        for row in formal_rows
        for knowledge_id in row
        if knowledge_id is not None
    }
    return all_knowledge_ids - (formal_ids - pending_ids)


def _statement(session: Session, data: RelationSearch):
    statement = select(KnowledgeObject)
    if data.canonical_id:
        statement = statement.where(KnowledgeObject.canonical_id == data.canonical_id)
    if any(
        (
            data.knowledge_name,
            data.grade_term_code,
            data.knowledge_type,
            data.knowledge_base_id,
        )
    ):
        statement = _knowledge_statement(
            KnowledgeSearch(
                canonical_id=data.canonical_id,
                keyword=data.knowledge_name,
                grade_term_code=data.grade_term_code,
                knowledge_type=data.knowledge_type,
                scope=None,
                knowledge_base_id=data.knowledge_base_id,
                page_num=1,
                page_size=100,
            )
        )
    if data.status:
        pending_ids = _pending_knowledge_ids(session)
        if data.status == "pending":
            statement = statement.where(KnowledgeObject.id.in_(pending_ids))
        elif pending_ids:
            statement = statement.where(KnowledgeObject.id.not_in(pending_ids))
    return statement.order_by(KnowledgeObject.id)


def _page(
    session: Session, statement, page_num: int, page_size: int
) -> tuple[int, list[KnowledgeObject]]:
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


def _relation_rows(
    session: Session, knowledge_ids: set[int]
) -> list[tuple[KnowledgeRelation, RelationRevision]]:
    if not knowledge_ids:
        return []
    return list(
        session.execute(
            select(KnowledgeRelation, RelationRevision)
            .join(
                RelationRevision,
                RelationRevision.id == KnowledgeRelation.latest_revision_id,
            )
            .where(
                or_(
                    RelationRevision.from_knowledge_id.in_(knowledge_ids),
                    RelationRevision.to_knowledge_id.in_(knowledge_ids),
                )
            )
            .order_by(KnowledgeRelation.id)
        ).all()
    )


def _formal_versions(
    session: Session, relation_ids: set[int]
) -> tuple[dict[int, list[dict[str, str]]], set[tuple[int, int]]]:
    if not relation_ids:
        return {}, set()
    rows = session.execute(
        select(
            ReleaseRelation.relation_id,
            ReleaseRelation.relation_revision_id,
            ReleaseVersion.knowledge_base_id,
            ReleaseVersion.version_label,
        )
        .join(ReleaseVersion, ReleaseVersion.id == ReleaseRelation.release_id)
        .where(ReleaseRelation.relation_id.in_(relation_ids))
        .order_by(ReleaseVersion.published_at.desc())
    ).all()
    versions: dict[int, list[dict[str, str]]] = defaultdict(list)
    seen_knowledge_bases: dict[int, set[int]] = defaultdict(set)
    formal_revisions: set[tuple[int, int]] = set()
    for relation_id, revision_id, knowledge_base_id, version_label in rows:
        formal_revisions.add((relation_id, revision_id))
        if knowledge_base_id not in seen_knowledge_bases[relation_id]:
            seen_knowledge_bases[relation_id].add(knowledge_base_id)
            versions[relation_id].append(
                {
                    "knowledgeBaseId": str(knowledge_base_id),
                    "releaseVersion": version_label,
                }
            )
    return dict(versions), formal_revisions


def _relation_detail(
    relation: KnowledgeRelation,
    revision: RelationRevision,
    objects: dict[int, KnowledgeObject],
    revisions: dict[int, KnowledgeRevision],
    versions: dict[int, list[dict[str, str]]],
    formal_revisions: set[tuple[int, int]],
) -> dict[str, Any]:
    source = objects.get(revision.from_knowledge_id)
    target = objects.get(revision.to_knowledge_id)
    source_revision = revisions.get(source.latest_revision_id) if source else None
    target_revision = revisions.get(target.latest_revision_id) if target else None
    return {
        "relationId": str(relation.id),
        "relationType": revision.relation_type,
        "fromCanonicalId": source.canonical_id if source else None,
        "toCanonicalId": target.canonical_id if target else None,
        "fromKnowledgeName": source_revision.name if source_revision else None,
        "toKnowledgeName": target_revision.name if target_revision else None,
        "operation": revision.operation,
        "note": revision.note,
        "currentFormalVersions": versions.get(relation.id, []),
        "status": (
            "published" if (relation.id, revision.id) in formal_revisions else "pending"
        ),
        "rowVersion": relation.row_version,
    }


def _group(
    knowledge_id: int,
    rows: list[tuple[KnowledgeRelation, RelationRevision]],
    objects: dict[int, KnowledgeObject],
    revisions: dict[int, KnowledgeRevision],
) -> dict[str, list[dict[str, str]]]:
    groups = {"prerequisites": [], "successors": [], "parallel": [], "cross": []}
    for _relation, revision in rows:
        if revision.operation != "upsert":
            continue
        source = objects.get(revision.from_knowledge_id)
        target = objects.get(revision.to_knowledge_id)
        if source is None or target is None:
            continue
        source_revision = revisions.get(source.latest_revision_id)
        target_revision = revisions.get(target.latest_revision_id)
        if revision.relation_type == "prerequisite":
            if revision.to_knowledge_id == knowledge_id:
                groups["prerequisites"].append(
                    {
                        "canonicalId": source.canonical_id,
                        "knowledgeName": (
                            source_revision.name
                            if source_revision
                            else source.canonical_id
                        ),
                    }
                )
            elif revision.from_knowledge_id == knowledge_id:
                groups["successors"].append(
                    {
                        "canonicalId": target.canonical_id,
                        "knowledgeName": (
                            target_revision.name
                            if target_revision
                            else target.canonical_id
                        ),
                    }
                )
        elif revision.relation_type in {"parallel", "cross"}:
            other = target if revision.from_knowledge_id == knowledge_id else source
            other_revision = revisions.get(other.latest_revision_id)
            groups[revision.relation_type].append(
                {
                    "canonicalId": other.canonical_id,
                    "knowledgeName": (
                        other_revision.name if other_revision else other.canonical_id
                    ),
                }
            )
    return groups


def list_relations(session: Session, data: RelationSearch) -> tuple[int, list[dict]]:
    total, knowledge_rows = _page(
        session, _statement(session, data), data.page_num, data.page_size
    )
    if not knowledge_rows:
        return total, []

    page_knowledge_ids = {knowledge.id for knowledge in knowledge_rows}
    relation_rows = _relation_rows(session, page_knowledge_ids)
    endpoint_ids = {
        endpoint_id
        for _relation, revision in relation_rows
        for endpoint_id in (revision.from_knowledge_id, revision.to_knowledge_id)
    }
    objects = {
        knowledge.id: knowledge
        for knowledge in session.scalars(
            select(KnowledgeObject).where(
                KnowledgeObject.id.in_(page_knowledge_ids | endpoint_ids)
            )
        )
    }
    revision_ids = {
        knowledge.latest_revision_id
        for knowledge in objects.values()
        if knowledge.latest_revision_id is not None
    }
    latest_revisions = {
        revision.id: revision
        for revision in session.scalars(
            select(KnowledgeRevision).where(KnowledgeRevision.id.in_(revision_ids))
        )
    }
    relation_ids = {relation.id for relation, _revision in relation_rows}
    versions, formal_revisions = _formal_versions(session, relation_ids)
    rows_by_knowledge: dict[int, list[tuple[KnowledgeRelation, RelationRevision]]] = (
        defaultdict(list)
    )
    for relation, revision in relation_rows:
        rows_by_knowledge[revision.from_knowledge_id].append((relation, revision))
        if revision.to_knowledge_id != revision.from_knowledge_id:
            rows_by_knowledge[revision.to_knowledge_id].append((relation, revision))

    result = []
    for knowledge in knowledge_rows:
        revision = latest_revisions.get(knowledge.latest_revision_id)
        if revision is None:
            raise BusinessError("INTERNAL_ERROR", "知识点当前修订不存在", 500)
        rows = rows_by_knowledge.get(knowledge.id, [])
        details = [
            _relation_detail(
                relation,
                relation_revision,
                objects,
                latest_revisions,
                versions,
                formal_revisions,
            )
            for relation, relation_revision in rows
        ]
        current_versions = []
        seen_versions = set()
        for detail in details:
            for version in detail["currentFormalVersions"]:
                key = (version["knowledgeBaseId"], version["releaseVersion"])
                if key not in seen_versions:
                    seen_versions.add(key)
                    current_versions.append(version)
        pending = not current_versions or any(
            detail["status"] == "pending" for detail in details
        )
        result.append(
            {
                "canonicalId": knowledge.canonical_id,
                "knowledgeName": revision.name,
                "gradeTermCode": revision.grade_term,
                **_group(knowledge.id, rows, objects, latest_revisions),
                "relationId": details[0]["relationId"] if details else None,
                "relations": details,
                "currentFormalVersions": current_versions,
                "status": "pending" if pending else "published",
                "rowVersion": knowledge.row_version,
            }
        )
    return total, result
