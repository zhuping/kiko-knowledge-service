from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    KnowledgeRevision,
    ReleaseCatalogNode,
    ReleaseKnowledge,
    ReleaseMapping,
    ReleaseRelation,
    ReleaseVersion,
)


def _tree_from_release(session: Session, release_id: int) -> list[dict]:
    rows = list(
        session.scalars(
            select(ReleaseCatalogNode)
            .where(ReleaseCatalogNode.release_id == release_id)
            .order_by(ReleaseCatalogNode.sort_order, ReleaseCatalogNode.id)
        )
    )
    children: dict[int | None, list[ReleaseCatalogNode]] = defaultdict(list)
    for row in rows:
        children[row.parent_id].append(row)

    def build(row: ReleaseCatalogNode) -> dict:
        return {
            "id": str(row.catalog_node_id),
            "key": row.source_key,
            "sourceKey": row.source_key,
            "title": row.title,
            "level": row.level,
            "nodeType": row.node_type,
            "sourcePath": row.source_path,
            "sortOrder": row.sort_order,
            "children": [
                build(child) for child in children.get(row.catalog_node_id, [])
            ],
        }

    return [build(row) for row in children.get(None, [])]


def release_document(session: Session, release: ReleaseVersion) -> dict:
    knowledge = []
    for row in session.scalars(
        select(ReleaseKnowledge).where(ReleaseKnowledge.release_id == release.id)
    ):
        revision = session.get(KnowledgeRevision, row.revision_id)
        if revision:
            knowledge.append(
                {
                    "canonicalId": row.canonical_id,
                    "knowledgeName": revision.name,
                    "knowledgeType": revision.type,
                    "gradeTermCode": revision.grade_term,
                    "scope": revision.scope,
                    "ocrSignals": revision.ocr_signals or [],
                    "exerciseSignature": revision.exercise_signature,
                }
            )
    mappings = [
        {
            "catalogNodeId": str(row.catalog_node_id),
            "canonicalId": row.canonical_id,
        }
        for row in session.scalars(
            select(ReleaseMapping).where(ReleaseMapping.release_id == release.id)
        )
    ]
    relations = [
        {
            "relationType": row.relation_type,
            "fromCanonicalId": row.from_canonical_id,
            "toCanonicalId": row.to_canonical_id,
            "note": row.note,
        }
        for row in session.scalars(
            select(ReleaseRelation).where(ReleaseRelation.release_id == release.id)
        )
    ]
    return {
        "knowledgeBaseId": str(release.knowledge_base_id),
        "releaseVersion": release.version_label,
        "catalog": _tree_from_release(session, release.id),
        "knowledge": knowledge,
        "mappings": mappings,
        "relations": relations,
    }


def release_diff(session: Session, kb_id: int, version_label: str) -> dict:
    from app.modules.release.service import get_release

    target = get_release(session, kb_id, version_label)
    current = get_release(session, kb_id)
    if target.id == current.id:
        return {"releaseVersion": target.version_label, "changed": False, "items": []}
    return {
        "releaseVersion": target.version_label,
        "baseReleaseVersion": current.version_label,
        "changed": True,
        "items": [{"type": "release", "target": target.version_label}],
    }
