from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.models import (
    AuditLog,
    ChangeLog,
    ContentSpace,
    ReleaseBatch,
    ReleaseBatchItem,
    ReleaseCurrent,
    ReleaseSnapshot,
    ReleaseVersion,
)
from app.models.base import utc_now


def _content_hash(document: dict[str, dict[str, dict[str, Any]]]) -> str:
    raw = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def current_version(session: Session) -> ReleaseVersion | None:
    current = session.get(ReleaseCurrent, 1)
    return session.get(ReleaseVersion, current.release_id) if current else None


def snapshot_document(
    session: Session, release_id: int | None
) -> dict[str, dict[str, dict[str, Any]]]:
    document: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    if release_id is None:
        return document
    for row in session.scalars(
        select(ReleaseSnapshot).where(ReleaseSnapshot.release_id == release_id)
    ):
        document[row.entity_type][row.entity_key] = row.payload
    return document


def _selected_changes(session: Session, batch: ReleaseBatch) -> list[ChangeLog]:
    items = list(
        session.scalars(
            select(ReleaseBatchItem).where(ReleaseBatchItem.batch_id == batch.id)
        )
    )
    changes: list[ChangeLog] = []
    for item in items:
        change = session.get(ChangeLog, item.change_log_id)
        if change is None or change.after_hash != item.selected_hash:
            raise BusinessError("CONFLICT", "发布批次引用的草稿已发生变化", 409)
        changes.append(change)
    return changes


def candidate_document(
    session: Session, batch: ReleaseBatch
) -> dict[str, dict[str, dict[str, Any]]]:
    document = snapshot_document(session, batch.base_release_id)
    for change in _selected_changes(session, batch):
        bucket = document[change.entity_type]
        if change.operation == "delete":
            bucket.pop(change.entity_key, None)
        elif change.after_payload is not None:
            bucket[change.entity_key] = change.after_payload
    return document


def _has_prerequisite_cycle(relations: list[dict[str, Any]]) -> bool:
    graph: dict[int, list[int]] = defaultdict(list)
    for relation in relations:
        if relation.get("relation_type") == "prerequisite":
            graph[int(relation["from_knowledge_id"])].append(
                int(relation["to_knowledge_id"])
            )
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


def validate_document(
    document: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    nodes = document.get("catalog_node", {})
    knowledge = document.get("knowledge_object", {})
    attachments = document.get("catalog_knowledge_node", {})
    mappings = document.get("textbook_mapping", {})
    relations = list(document.get("knowledge_relation", {}).values())

    for node in nodes.values():
        level = node.get("level")
        parent_id = node.get("parent_id")
        expected_type = {1: "domain", 2: "topic", 3: "unit", 4: "group"}.get(level)
        if expected_type != node.get("node_type"):
            errors.append({"entity": node.get("id"), "reason": "层级和节点类型不匹配"})
        if level == 1 and parent_id is not None:
            errors.append({"entity": node.get("id"), "reason": "一级节点不能有父节点"})
        if level and level > 1:
            parent = nodes.get(str(parent_id))
            if not parent or parent.get("level") != level - 1:
                errors.append(
                    {"entity": node.get("id"), "reason": "父节点不是相邻上一级"}
                )

    mapped_knowledge_ids: set[int] = set()
    for mapping in mappings.values():
        if mapping.get("status") != "disabled":
            mapped_knowledge_ids.add(int(mapping["knowledge_id"]))
        if not any(
            int(item.get("id")) == int(mapping.get("knowledge_id"))
            for item in knowledge.values()
        ):
            errors.append(
                {"entity": mapping.get("id"), "reason": "教材映射引用不存在的知识对象"}
            )

    for item in attachments.values():
        group = nodes.get(str(item.get("group_node_id")))
        if not group or group.get("level") != 4:
            errors.append(
                {"entity": item.get("id"), "reason": "五级知识点必须挂到四级知识点组"}
            )
        if not any(
            int(row.get("id")) == int(item.get("knowledge_id"))
            for row in knowledge.values()
        ):
            errors.append(
                {"entity": item.get("id"), "reason": "挂载引用不存在的知识对象"}
            )

    for item in knowledge.values():
        if (
            item.get("status") != "disabled"
            and int(item.get("id")) not in mapped_knowledge_ids
        ):
            errors.append(
                {
                    "entity": item.get("canonical_id"),
                    "reason": "启用知识对象缺少教材映射",
                }
            )

    known_ids = {int(item.get("id")) for item in knowledge.values()}
    for relation in relations:
        source = int(relation.get("from_knowledge_id"))
        target = int(relation.get("to_knowledge_id"))
        if source == target or source not in known_ids or target not in known_ids:
            errors.append({"entity": relation.get("id"), "reason": "知识关系引用无效"})
    if _has_prerequisite_cycle(relations):
        errors.append({"entity": "knowledge_relation", "reason": "前置关系存在有向环"})
    return errors


def create_batch(
    session: Session,
    space_code: str,
    version_label: str | None,
    release_note: str | None,
    change_log_ids: list[int],
    actor: str,
) -> ReleaseBatch:
    space = session.scalar(
        select(ContentSpace).where(ContentSpace.space_code == space_code)
    )
    if space is None:
        raise BusinessError("NOT_FOUND", "编辑空间不存在", 404)
    current = current_version(session)
    changes = (
        list(session.scalars(select(ChangeLog).where(ChangeLog.id.in_(change_log_ids))))
        if change_log_ids
        else list(
            session.scalars(
                select(ChangeLog).where(
                    ChangeLog.space_id == space.id, ChangeLog.status == "unreleased"
                )
            )
        )
    )
    if not changes:
        raise BusinessError("VALIDATION_FAILED", "没有待发布变更", 422)
    label = version_label or datetime.utcnow().strftime("%Y.%m.%d.%H%M%S")
    batch = ReleaseBatch(
        space_id=space.id,
        base_release_id=current.id if current else None,
        batch_type="normal",
        version_label=label,
        release_note=release_note,
        created_by=actor,
    )
    session.add(batch)
    session.flush()
    for change in changes:
        if change.status != "unreleased" or change.after_hash is None:
            raise BusinessError("CONFLICT", "只能选择未发布且内容完整的变更", 409)
        session.add(
            ReleaseBatchItem(
                batch_id=batch.id,
                change_log_id=change.id,
                selected_hash=change.after_hash,
            )
        )
    session.add(
        AuditLog(
            actor_id=actor,
            action="release_batch.create",
            entity_type="release_batch",
            entity_key=str(batch.id),
            summary=batch.version_label,
            created_at=utc_now(),
        )
    )
    session.commit()
    return batch


def validate_batch(session: Session, batch_id: int) -> list[dict[str, Any]]:
    batch = session.get(ReleaseBatch, batch_id)
    if batch is None:
        raise BusinessError("NOT_FOUND", "发布批次不存在", 404)
    errors = validate_document(candidate_document(session, batch))
    batch.validation_status = "failed" if errors else "passed"
    session.commit()
    return errors


def publish_batch(session: Session, batch_id: int, actor: str) -> ReleaseVersion:
    batch = session.get(ReleaseBatch, batch_id)
    if batch is None:
        raise BusinessError("NOT_FOUND", "发布批次不存在", 404)
    if batch.validation_status != "passed":
        errors = validate_batch(session, batch_id)
        if errors:
            raise BusinessError("VALIDATION_FAILED", "发布校验未通过", 422, errors)
        session.refresh(batch)
    document = candidate_document(session, batch)
    published_at = utc_now()
    version = ReleaseVersion(
        version_label=batch.version_label,
        base_release_id=batch.base_release_id,
        batch_id=batch.id,
        release_type=batch.batch_type,
        content_hash=_content_hash(document),
        published_by=actor,
        published_at=published_at,
    )
    session.add(version)
    session.flush()
    for entity_type, rows in document.items():
        for entity_key, payload in rows.items():
            session.add(
                ReleaseSnapshot(
                    release_id=version.id,
                    entity_type=entity_type,
                    entity_key=entity_key,
                    payload=payload,
                )
            )
    current = session.get(ReleaseCurrent, 1)
    if current is None:
        session.add(
            ReleaseCurrent(id=1, release_id=version.id, updated_at=published_at)
        )
    else:
        current.release_id = version.id
        current.updated_at = published_at
    for change in _selected_changes(session, batch):
        change.status = "released"
    batch.status = "published"
    batch.published_by = actor
    batch.published_at = published_at
    session.add(
        AuditLog(
            actor_id=actor,
            action="release.publish",
            entity_type="release_version",
            entity_key=version.version_label,
            summary=batch.release_note,
            created_at=published_at,
        )
    )
    session.commit()
    return version


def get_release_document(
    session: Session, version_label: Optional[str] = None
) -> tuple[ReleaseVersion, dict[str, dict[str, dict[str, Any]]]]:
    if version_label:
        version = session.scalar(
            select(ReleaseVersion).where(ReleaseVersion.version_label == version_label)
        )
    else:
        version = current_version(session)
    if version is None:
        raise BusinessError("NOT_FOUND", "当前没有正式版本", 404)
    return version, snapshot_document(session, version.id)


def list_releases(session: Session) -> list[ReleaseVersion]:
    return list(
        session.scalars(select(ReleaseVersion).order_by(ReleaseVersion.id.desc()))
    )
