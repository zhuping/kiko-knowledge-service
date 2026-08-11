from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    KnowledgeBase,
    KnowledgeRevision,
    ReleaseCatalogNode,
    ReleaseKnowledge,
    ReleaseMapping,
    ReleaseRelation,
    ReleaseVersion,
    TextbookEdition,
)


def _tree_from_release(
    session: Session, release_id: int, root_title: str | None
) -> list[dict]:
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
            "title": (
                root_title
                if root_title and row.node_type == "book" and row.level == 0
                else row.title
            ),
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
    root_title = session.scalar(
        select(TextbookEdition.edition_name)
        .join(KnowledgeBase, KnowledgeBase.textbook_edition_id == TextbookEdition.id)
        .where(KnowledgeBase.id == release.knowledge_base_id)
    )
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
        "catalog": _tree_from_release(session, release.id, root_title),
        "knowledge": knowledge,
        "mappings": mappings,
        "relations": relations,
    }


def _flatten_catalog(nodes: list[dict]) -> list[dict]:
    rows = []
    for node in nodes:
        rows.append({key: value for key, value in node.items() if key != "children"})
        rows.extend(_flatten_catalog(node.get("children", [])))
    return rows


def release_diff(session: Session, kb_id: int, version_label: str) -> dict:
    from app.modules.release.service import get_release

    target = get_release(session, kb_id, version_label)
    base = (
        session.get(ReleaseVersion, target.base_release_id)
        if target.base_release_id
        else None
    )
    if base is None:
        base = session.scalar(
            select(ReleaseVersion)
            .where(
                ReleaseVersion.knowledge_base_id == kb_id,
                ReleaseVersion.version_no < target.version_no,
            )
            .order_by(ReleaseVersion.version_no.desc())
        )

    empty = {"catalog": [], "knowledge": [], "mappings": [], "relations": []}
    before = release_document(session, base) if base else empty
    after = release_document(session, target)
    sections = {
        "catalog": (
            _flatten_catalog(before["catalog"]),
            _flatten_catalog(after["catalog"]),
            lambda item: item["id"],
        ),
        "knowledge": (
            before["knowledge"],
            after["knowledge"],
            lambda item: item["canonicalId"],
        ),
        "mappings": (
            before["mappings"],
            after["mappings"],
            lambda item: f"{item['catalogNodeId']}:{item['canonicalId']}",
        ),
        "relations": (
            before["relations"],
            after["relations"],
            lambda item: ":".join(
                [item["relationType"], item["fromCanonicalId"], item["toCanonicalId"]]
            ),
        ),
    }

    items: list[dict[str, Any]] = []
    summary: dict[str, dict[str, int]] = {}
    for section, (before_rows, after_rows, key) in sections.items():
        before_by_key = {key(row): row for row in before_rows}
        after_by_key = {key(row): row for row in after_rows}
        counts = {"added": 0, "removed": 0, "modified": 0}
        for item_key in sorted(set(before_by_key) | set(after_by_key), key=str):
            old = before_by_key.get(item_key)
            new = after_by_key.get(item_key)
            if old is None:
                counts["added"] += 1
                items.append(
                    {
                        "type": section,
                        "change": "added",
                        "key": str(item_key),
                        "after": new,
                    }
                )
            elif new is None:
                counts["removed"] += 1
                items.append(
                    {
                        "type": section,
                        "change": "removed",
                        "key": str(item_key),
                        "before": old,
                    }
                )
            elif old != new:
                counts["modified"] += 1
                items.append(
                    {
                        "type": section,
                        "change": "modified",
                        "key": str(item_key),
                        "before": old,
                        "after": new,
                    }
                )
        summary[section] = counts

    return {
        "releaseVersion": target.version_label,
        "baseReleaseVersion": base.version_label if base else None,
        "changed": bool(items),
        "summary": summary,
        "items": items,
    }
