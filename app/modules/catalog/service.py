from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.models import (
    AuditLog,
    CatalogKnowledgeNode,
    CatalogNode,
    ChangeLog,
    ContentSpace,
    KnowledgeObject,
    KnowledgePolicyMapping,
    KnowledgeRelation,
    KnowledgeTerm,
    PolicyRule,
    TextbookEdition,
    TextbookMapping,
)
from app.models.base import utc_now
from app.schemas.catalog import (
    CatalogKnowledgeAttach,
    CatalogNodeCreate,
    CatalogNodeMove,
    CatalogNodeUpdate,
    KnowledgeCreate,
    KnowledgeNodeMove,
    KnowledgeStatusBatch,
    KnowledgeUpdate,
    PolicyMappingCreate,
    RelationBatch,
    RelationCreate,
    TextbookMappingCreate,
)

CANONICAL_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
NODE_TYPES = {1: "domain", 2: "topic", 3: "unit", 4: "group"}
TERM_TYPES = {
    "aliases": "alias",
    "core_keywords": "core_keyword",
    "derivative_keywords": "derivative_keyword",
    "ocr_signals": "ocr_signal",
}


def _json_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def ensure_context(
    session: Session,
    space_code: str = "default",
    edition_code: str = "pep_math_2024_63",
) -> tuple[ContentSpace, TextbookEdition]:
    space = session.scalar(
        select(ContentSpace).where(ContentSpace.space_code == space_code)
    )
    if space is None:
        space = ContentSpace(space_code=space_code, name="默认编辑空间")
        session.add(space)
        session.flush()
    edition = session.scalar(
        select(TextbookEdition).where(TextbookEdition.edition_code == edition_code)
    )
    if edition is None:
        edition = TextbookEdition(
            edition_code=edition_code,
            edition_name="人教版小学数学2024审定新版（六三制）",
        )
        session.add(edition)
        session.flush()
    return space, edition


def _audit(
    session: Session, actor: str, action: str, entity_type: str, entity_key: str
) -> None:
    session.add(
        AuditLog(
            actor_id=actor,
            action=action,
            entity_type=entity_type,
            entity_key=entity_key,
            summary=action,
            created_at=utc_now(),
        )
    )


def _change(
    session: Session,
    space_id: int,
    entity_type: str,
    entity_key: str,
    payload: dict[str, Any],
    actor: str,
    operation: str = "create",
) -> None:
    session.add(
        ChangeLog(
            space_id=space_id,
            entity_type=entity_type,
            entity_key=entity_key,
            operation=operation,
            after_hash=_json_hash(payload),
            after_payload=payload,
            operator_id=actor,
        )
    )


def node_payload(node: CatalogNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "space_id": node.space_id,
        "edition_id": node.edition_id,
        "parent_id": node.parent_id,
        "level": node.level,
        "node_type": node.node_type,
        "title": node.title,
        "sort_order": node.sort_order,
        "status": node.status,
        "row_version": node.row_version,
    }


def _term_values(session: Session, knowledge_id: int) -> dict[str, list[str]]:
    values = {name: [] for name in TERM_TYPES}
    rows = session.scalars(
        select(KnowledgeTerm)
        .where(KnowledgeTerm.knowledge_id == knowledge_id)
        .order_by(KnowledgeTerm.sort_order, KnowledgeTerm.id)
    )
    reverse = {value: key for key, value in TERM_TYPES.items()}
    for row in rows:
        key = reverse.get(row.term_type)
        if key:
            values[key].append(row.term)
    return values


def knowledge_payload(session: Session, knowledge: KnowledgeObject) -> dict[str, Any]:
    terms = _term_values(session, knowledge.id)
    return {
        "id": knowledge.id,
        "canonical_id": knowledge.canonical_id,
        "name": knowledge.name,
        "type": knowledge.type,
        "grade_term": knowledge.grade_term,
        "scope": knowledge.scope,
        "cognitive_level": knowledge.cognitive_level,
        "importance": knowledge.importance,
        **terms,
        "exercise_signature": knowledge.exercise_signature,
        "solution_feature": knowledge.solution_feature,
        "scene_feature": knowledge.scene_feature,
        "numeric_feature": knowledge.numeric_feature,
        "status": knowledge.status,
        "row_version": knowledge.row_version,
    }


def _mapping_response(session: Session, mapping: TextbookMapping) -> dict[str, Any]:
    edition = session.get(TextbookEdition, mapping.edition_id)
    knowledge = session.get(KnowledgeObject, mapping.knowledge_id)
    return {
        "id": mapping.id,
        "canonicalId": knowledge.canonical_id if knowledge else None,
        "editionCode": edition.edition_code if edition else None,
        "textbookPath": mapping.textbook_path,
        "mappingType": mapping.mapping_type,
        "alignmentType": mapping.alignment_type,
        "editionLabel": mapping.edition_label,
        "editionKeywords": mapping.edition_keywords,
        "pageStart": mapping.page_start,
        "pageEnd": mapping.page_end,
        "evidence": mapping.evidence,
        "status": mapping.status,
    }


def mapping_payload(session: Session, mapping: TextbookMapping) -> dict[str, Any]:
    payload = _mapping_response(session, mapping)
    edition = session.get(TextbookEdition, mapping.edition_id)
    return {
        "id": mapping.id,
        "space_id": mapping.space_id,
        "edition_id": mapping.edition_id,
        "edition_code": edition.edition_code if edition else None,
        "knowledge_id": mapping.knowledge_id,
        "catalog_node_id": mapping.catalog_node_id,
        "textbook_path": payload["textbookPath"],
        "mapping_type": payload["mappingType"],
        "alignment_type": payload["alignmentType"],
        "edition_label": payload["editionLabel"],
        "edition_keywords": payload["editionKeywords"],
        "page_start": payload["pageStart"],
        "page_end": payload["pageEnd"],
        "evidence": payload["evidence"],
        "status": payload["status"],
    }


def attach_payload(item: CatalogKnowledgeNode) -> dict[str, Any]:
    return {
        "id": item.id,
        "space_id": item.space_id,
        "group_node_id": item.group_node_id,
        "knowledge_id": item.knowledge_id,
        "sort_order": item.sort_order,
        "status": item.status,
        "row_version": item.row_version,
    }


def relation_payload(relation: KnowledgeRelation) -> dict[str, Any]:
    return {
        "id": relation.id,
        "space_id": relation.space_id,
        "from_knowledge_id": relation.from_knowledge_id,
        "to_knowledge_id": relation.to_knowledge_id,
        "relation_type": relation.relation_type,
        "edition_id": relation.edition_id,
        "basis": relation.basis,
        "note": relation.note,
        "status": relation.status,
    }


def _check_row_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise BusinessError("CONFLICT", "数据已被其他人修改，请刷新后重试", 409)


def _group_context(
    session: Session, group_node_id: int
) -> tuple[ContentSpace, CatalogNode]:
    group = session.get(CatalogNode, group_node_id)
    if not group or group.level != 4 or group.status == "disabled":
        raise BusinessError(
            "VALIDATION_FAILED", "知识点只能挂到启用的四级知识点组", 422
        )
    space = session.get(ContentSpace, group.space_id)
    if not space:
        raise BusinessError("NOT_FOUND", "编辑空间不存在", 404)
    return space, group


def _knowledge_space(session: Session, knowledge_id: int) -> ContentSpace:
    space_id = session.scalar(
        select(CatalogKnowledgeNode.space_id).where(
            CatalogKnowledgeNode.knowledge_id == knowledge_id
        )
    )
    space = session.get(ContentSpace, space_id) if space_id else None
    if not space:
        space, _ = ensure_context(session)
    return space


def _write_terms(
    session: Session, knowledge: KnowledgeObject, values: dict[str, list[str]]
) -> None:
    for key, terms in values.items():
        for order, term in enumerate(terms):
            if term.strip():
                session.add(
                    KnowledgeTerm(
                        knowledge_id=knowledge.id,
                        term_type=TERM_TYPES[key],
                        term=term.strip(),
                        sort_order=order,
                    )
                )


def _replace_terms(
    session: Session, knowledge: KnowledgeObject, values: dict[str, list[str]]
) -> None:
    term_types = [TERM_TYPES[key] for key in values]
    session.execute(
        delete(KnowledgeTerm).where(
            KnowledgeTerm.knowledge_id == knowledge.id,
            KnowledgeTerm.term_type.in_(term_types),
        )
    )
    _write_terms(session, knowledge, values)


def create_node(session: Session, data: CatalogNodeCreate, actor: str) -> CatalogNode:
    if data.node_type != NODE_TYPES[data.level]:
        raise BusinessError("PARAM_INVALID", "层级和节点类型不匹配")
    space, edition = ensure_context(session, data.space_code, data.edition_code)
    if data.level == 1 and data.parent_id is not None:
        raise BusinessError("VALIDATION_FAILED", "一级节点不能有父节点", 422)
    if data.level > 1:
        parent = session.get(CatalogNode, data.parent_id)
        if not parent or parent.space_id != space.id or parent.edition_id != edition.id:
            raise BusinessError("NOT_FOUND", "父节点不存在", 404)
        if parent.level != data.level - 1:
            raise BusinessError("VALIDATION_FAILED", "父节点必须是相邻上一级", 422)
    node = CatalogNode(
        space_id=space.id,
        edition_id=edition.id,
        parent_id=data.parent_id,
        level=data.level,
        node_type=data.node_type,
        title=data.title,
        sort_order=data.sort_order,
    )
    session.add(node)
    session.flush()
    _change(session, space.id, "catalog_node", str(node.id), node_payload(node), actor)
    _audit(session, actor, "catalog_node.create", "catalog_node", str(node.id))
    session.commit()
    return node


def update_node(
    session: Session, node_id: int, data: CatalogNodeUpdate, actor: str
) -> CatalogNode:
    node = session.get(CatalogNode, node_id)
    if not node:
        raise BusinessError("NOT_FOUND", "目录节点不存在", 404)
    _check_row_version(node.row_version, data.row_version)
    for field in ("title", "status"):
        if field in data.model_fields_set:
            setattr(node, field, getattr(data, field))
    node.row_version += 1
    session.flush()
    _change(
        session,
        node.space_id,
        "catalog_node",
        str(node.id),
        node_payload(node),
        actor,
        "update",
    )
    _audit(session, actor, "catalog_node.update", "catalog_node", str(node.id))
    session.commit()
    return node


def move_node(
    session: Session, node_id: int, data: CatalogNodeMove, actor: str
) -> CatalogNode:
    node = session.get(CatalogNode, node_id)
    if not node:
        raise BusinessError("NOT_FOUND", "目录节点不存在", 404)
    _check_row_version(node.row_version, data.row_version)
    node.sort_order = data.sort_order
    node.row_version += 1
    session.flush()
    _change(
        session,
        node.space_id,
        "catalog_node",
        str(node.id),
        node_payload(node),
        actor,
        "update",
    )
    _audit(session, actor, "catalog_node.move", "catalog_node", str(node.id))
    session.commit()
    return node


def create_knowledge(
    session: Session, data: KnowledgeCreate, actor: str
) -> KnowledgeObject:
    if not CANONICAL_ID.fullmatch(data.canonical_id):
        raise BusinessError("PARAM_INVALID", "canonicalId 格式无效")
    if session.scalar(
        select(KnowledgeObject).where(KnowledgeObject.canonical_id == data.canonical_id)
    ):
        raise BusinessError("CONFLICT", "canonicalId 已存在", 409)
    space, group = _group_context(session, data.group_node_id)
    knowledge = KnowledgeObject(
        canonical_id=data.canonical_id,
        name=data.knowledge_name,
        type=data.knowledge_type,
        grade_term=data.grade_term,
        scope=data.scope,
        cognitive_level=data.cognitive_level,
        importance=data.importance,
        exercise_signature=data.exercise_signature,
        solution_feature=data.solution_feature,
        scene_feature=data.scene_feature,
        numeric_feature=data.numeric_feature,
        created_by=actor,
        updated_by=actor,
    )
    session.add(knowledge)
    session.flush()
    _write_terms(
        session,
        knowledge,
        {
            "aliases": data.aliases,
            "core_keywords": data.core_keywords,
            "derivative_keywords": data.derivative_keywords,
            "ocr_signals": data.ocr_signals,
        },
    )
    attachment = CatalogKnowledgeNode(
        space_id=space.id,
        group_node_id=group.id,
        knowledge_id=knowledge.id,
    )
    session.add(attachment)
    session.flush()
    _change(
        session,
        space.id,
        "knowledge_object",
        knowledge.canonical_id,
        knowledge_payload(session, knowledge),
        actor,
    )
    _change(
        session,
        space.id,
        "catalog_knowledge_node",
        str(attachment.id),
        attach_payload(attachment),
        actor,
    )
    _audit(
        session, actor, "knowledge.create", "knowledge_object", knowledge.canonical_id
    )
    session.commit()
    return knowledge


def attach_knowledge(
    session: Session, data: CatalogKnowledgeAttach, actor: str
) -> CatalogKnowledgeNode:
    space, group = _group_context(session, data.group_node_id)
    if group.space_id != space.id:
        raise BusinessError("NOT_FOUND", "知识点组不存在", 404)
    knowledge = session.scalar(
        select(KnowledgeObject).where(KnowledgeObject.canonical_id == data.canonical_id)
    )
    if knowledge is None:
        raise BusinessError("NOT_FOUND", "知识对象不存在", 404)
    item = CatalogKnowledgeNode(
        space_id=space.id,
        group_node_id=group.id,
        knowledge_id=knowledge.id,
        sort_order=data.sort_order,
    )
    session.add(item)
    session.flush()
    _change(
        session,
        space.id,
        "catalog_knowledge_node",
        str(item.id),
        attach_payload(item),
        actor,
    )
    _audit(
        session,
        actor,
        "catalog_knowledge.attach",
        "catalog_knowledge_node",
        str(item.id),
    )
    session.commit()
    return item


def move_knowledge_node(
    session: Session, node_id: int, data: KnowledgeNodeMove, actor: str
) -> CatalogKnowledgeNode:
    item = session.get(CatalogKnowledgeNode, node_id)
    if not item:
        raise BusinessError("NOT_FOUND", "知识点挂载不存在", 404)
    _check_row_version(item.row_version, data.row_version)
    item.sort_order = data.sort_order
    item.row_version += 1
    session.flush()
    _change(
        session,
        item.space_id,
        "catalog_knowledge_node",
        str(item.id),
        attach_payload(item),
        actor,
        "update",
    )
    _audit(
        session, actor, "catalog_knowledge.move", "catalog_knowledge_node", str(item.id)
    )
    session.commit()
    return item


def create_mapping(
    session: Session, data: TextbookMappingCreate, actor: str
) -> TextbookMapping:
    space, edition = ensure_context(session, data.space_code, data.edition_code)
    knowledge = session.scalar(
        select(KnowledgeObject).where(KnowledgeObject.canonical_id == data.canonical_id)
    )
    if knowledge is None:
        raise BusinessError("NOT_FOUND", "知识对象不存在", 404)
    mapping = TextbookMapping(
        space_id=space.id,
        edition_id=edition.id,
        knowledge_id=knowledge.id,
        catalog_node_id=data.catalog_node_id,
        textbook_path=data.textbook_path,
        mapping_type=data.mapping_type,
        alignment_type=data.alignment_type,
        edition_label=data.edition_label,
        edition_keywords=data.edition_keywords,
        page_start=data.page_start,
        page_end=data.page_end,
        evidence=data.evidence,
    )
    session.add(mapping)
    session.flush()
    _change(
        session,
        space.id,
        "textbook_mapping",
        str(mapping.id),
        mapping_payload(session, mapping),
        actor,
    )
    _audit(
        session, actor, "textbook_mapping.create", "textbook_mapping", str(mapping.id)
    )
    session.commit()
    return mapping


def list_mappings(
    session: Session, edition_code: str | None = None, canonical_id: str | None = None
) -> list[dict[str, Any]]:
    statement = select(TextbookMapping).order_by(TextbookMapping.id)
    rows = list(session.scalars(statement))
    return [
        _mapping_response(session, row)
        for row in rows
        if (
            not edition_code
            or session.get(TextbookEdition, row.edition_id).edition_code == edition_code
        )
        and (
            not canonical_id
            or session.get(KnowledgeObject, row.knowledge_id).canonical_id
            == canonical_id
        )
    ]


def create_relation(
    session: Session, data: RelationCreate, actor: str, commit: bool = True
) -> KnowledgeRelation:
    if data.from_canonical_id == data.to_canonical_id:
        raise BusinessError("VALIDATION_FAILED", "知识关系不能自关联", 422)
    space, edition = ensure_context(
        session, data.space_code, data.edition_code or "pep_math_2024_63"
    )
    source = session.scalar(
        select(KnowledgeObject).where(
            KnowledgeObject.canonical_id == data.from_canonical_id
        )
    )
    target = session.scalar(
        select(KnowledgeObject).where(
            KnowledgeObject.canonical_id == data.to_canonical_id
        )
    )
    if source is None or target is None:
        raise BusinessError("NOT_FOUND", "关系引用的知识对象不存在", 404)
    existing = list(
        session.scalars(
            select(KnowledgeRelation).where(
                KnowledgeRelation.space_id == space.id,
                KnowledgeRelation.relation_type == data.relation_type,
                KnowledgeRelation.from_knowledge_id == source.id,
                KnowledgeRelation.to_knowledge_id == target.id,
            )
        )
    )
    if data.relation_type in {"parallel", "cross"}:
        existing += list(
            session.scalars(
                select(KnowledgeRelation).where(
                    KnowledgeRelation.space_id == space.id,
                    KnowledgeRelation.relation_type == data.relation_type,
                    KnowledgeRelation.from_knowledge_id == target.id,
                    KnowledgeRelation.to_knowledge_id == source.id,
                )
            )
        )
    if existing:
        raise BusinessError("CONFLICT", "关系已存在", 409)
    relation = KnowledgeRelation(
        space_id=space.id,
        from_knowledge_id=source.id,
        to_knowledge_id=target.id,
        relation_type=data.relation_type,
        edition_id=edition.id,
        basis=data.basis,
        note=data.note,
    )
    session.add(relation)
    session.flush()
    _change(
        session,
        space.id,
        "knowledge_relation",
        str(relation.id),
        relation_payload(relation),
        actor,
    )
    _audit(
        session,
        actor,
        "knowledge_relation.create",
        "knowledge_relation",
        str(relation.id),
    )
    if commit:
        session.commit()
    return relation


def apply_relation_batch(
    session: Session, data: RelationBatch, actor: str
) -> list[KnowledgeRelation]:
    result = []
    for operation in data.operations:
        if operation.operation == "add":
            result.append(create_relation(session, operation, actor, commit=False))
            continue
        source = session.scalar(
            select(KnowledgeObject).where(
                KnowledgeObject.canonical_id == operation.from_canonical_id
            )
        )
        target = session.scalar(
            select(KnowledgeObject).where(
                KnowledgeObject.canonical_id == operation.to_canonical_id
            )
        )
        if not source or not target:
            raise BusinessError("NOT_FOUND", "关系引用的知识对象不存在", 404)
        relation = session.scalar(
            select(KnowledgeRelation).where(
                KnowledgeRelation.from_knowledge_id == source.id,
                KnowledgeRelation.to_knowledge_id == target.id,
                KnowledgeRelation.relation_type == operation.relation_type,
            )
        )
        if not relation and operation.relation_type in {"parallel", "cross"}:
            relation = session.scalar(
                select(KnowledgeRelation).where(
                    KnowledgeRelation.from_knowledge_id == target.id,
                    KnowledgeRelation.to_knowledge_id == source.id,
                    KnowledgeRelation.relation_type == operation.relation_type,
                )
            )
        if not relation:
            raise BusinessError("NOT_FOUND", "关系不存在", 404)
        relation.status = "disabled" if operation.operation == "disable" else "active"
        _change(
            session,
            relation.space_id,
            "knowledge_relation",
            str(relation.id),
            relation_payload(relation),
            actor,
            "update",
        )
        result.append(relation)
    session.commit()
    return result


def relation_groups(session: Session, canonical_id: str) -> dict[str, list[str]]:
    knowledge = get_knowledge(session, canonical_id)
    # ponytail: small V1 relation set; replace with a joined query if volume grows.
    space_id = _knowledge_space(session, knowledge.id).id
    all_rows = list(
        session.scalars(
            select(KnowledgeRelation).where(
                KnowledgeRelation.status == "active",
                KnowledgeRelation.space_id == space_id,
            )
        )
    )
    by_id = {
        item.id: item.canonical_id for item in session.scalars(select(KnowledgeObject))
    }
    groups = {"prerequisites": [], "successors": [], "parallel": [], "cross": []}
    for relation in all_rows:
        source = by_id.get(relation.from_knowledge_id)
        target = by_id.get(relation.to_knowledge_id)
        if relation.relation_type == "prerequisite":
            if relation.to_knowledge_id == knowledge.id and source:
                groups["prerequisites"].append(source)
            if relation.from_knowledge_id == knowledge.id and target:
                groups["successors"].append(target)
        elif relation.relation_type in {"parallel", "cross"}:
            if relation.from_knowledge_id == knowledge.id and target:
                groups[relation.relation_type].append(target)
            elif relation.to_knowledge_id == knowledge.id and source:
                groups[relation.relation_type].append(source)
    return groups


def get_knowledge(session: Session, canonical_id: str) -> KnowledgeObject:
    knowledge = session.scalar(
        select(KnowledgeObject).where(KnowledgeObject.canonical_id == canonical_id)
    )
    if knowledge is None:
        raise BusinessError("NOT_FOUND", "知识对象不存在", 404)
    return knowledge


def knowledge_response(session: Session, knowledge: KnowledgeObject) -> dict[str, Any]:
    payload = knowledge_payload(session, knowledge)
    mappings = list_mappings(session, canonical_id=knowledge.canonical_id)
    return {
        "canonicalId": payload["canonical_id"],
        "knowledgeName": payload["name"],
        "knowledgeType": payload["type"],
        "gradeTerm": payload["grade_term"],
        "scope": payload["scope"],
        "cognitiveLevel": payload["cognitive_level"],
        "importance": payload["importance"],
        "aliases": payload["aliases"],
        "coreKeywords": payload["core_keywords"],
        "derivativeKeywords": payload["derivative_keywords"],
        "ocrSignals": payload["ocr_signals"],
        "exerciseSignature": payload["exercise_signature"],
        "solutionFeature": payload["solution_feature"],
        "sceneFeature": payload["scene_feature"],
        "numericFeature": payload["numeric_feature"],
        "status": payload["status"],
        "rowVersion": payload["row_version"],
        "textbookMappings": mappings,
    }


def list_knowledge(
    session: Session,
    keyword: str | None = None,
    canonical_id: str | None = None,
    grade_term: str | None = None,
    knowledge_type: str | None = None,
    scope: str | None = None,
    status: str | None = None,
    page_num: int = 1,
    page_size: int = 10,
) -> tuple[int, list[dict[str, Any]]]:
    rows = list(session.scalars(select(KnowledgeObject).order_by(KnowledgeObject.id)))
    keyword = keyword.lower() if keyword else None
    filtered = []
    for row in rows:
        terms = _term_values(session, row.id)
        searchable = " ".join(
            [row.name, *(value for values in terms.values() for value in values)]
        ).lower()
        if keyword and keyword not in searchable:
            continue
        if canonical_id and row.canonical_id != canonical_id:
            continue
        if grade_term and row.grade_term != grade_term:
            continue
        if knowledge_type and row.type != knowledge_type:
            continue
        if scope and row.scope != scope:
            continue
        if status and row.status != status:
            continue
        filtered.append(row)
    start = (page_num - 1) * page_size
    return len(filtered), [
        knowledge_response(session, row) for row in filtered[start : start + page_size]
    ]


def update_knowledge(
    session: Session, canonical_id: str, data: KnowledgeUpdate, actor: str
) -> KnowledgeObject:
    knowledge = get_knowledge(session, canonical_id)
    _check_row_version(knowledge.row_version, data.row_version)
    field_map = {
        "knowledge_name": "name",
        "knowledge_type": "type",
        "grade_term": "grade_term",
        "scope": "scope",
        "cognitive_level": "cognitive_level",
        "importance": "importance",
        "exercise_signature": "exercise_signature",
        "solution_feature": "solution_feature",
        "scene_feature": "scene_feature",
        "numeric_feature": "numeric_feature",
    }
    for field, target in field_map.items():
        if field in data.model_fields_set:
            setattr(knowledge, target, getattr(data, field))
    term_values = {
        key: getattr(data, key)
        for key in TERM_TYPES
        if key in data.model_fields_set and getattr(data, key) is not None
    }
    if term_values:
        _replace_terms(session, knowledge, term_values)
    knowledge.updated_by = actor
    knowledge.row_version += 1
    session.flush()
    space = _knowledge_space(session, knowledge.id)
    _change(
        session,
        space.id,
        "knowledge_object",
        knowledge.canonical_id,
        knowledge_payload(session, knowledge),
        actor,
        "update",
    )
    _audit(
        session, actor, "knowledge.update", "knowledge_object", knowledge.canonical_id
    )
    session.commit()
    return knowledge


def update_status_batch(
    session: Session, data: KnowledgeStatusBatch, actor: str
) -> list[KnowledgeObject]:
    result = []
    for item in data.operations:
        knowledge = get_knowledge(session, item.canonical_id)
        _check_row_version(knowledge.row_version, item.row_version)
        knowledge.status = item.status
        knowledge.row_version += 1
        knowledge.updated_by = actor
        result.append(knowledge)
        space = _knowledge_space(session, knowledge.id)
        _change(
            session,
            space.id,
            "knowledge_object",
            knowledge.canonical_id,
            knowledge_payload(session, knowledge),
            actor,
            "update",
        )
        _audit(
            session,
            actor,
            "knowledge.status",
            "knowledge_object",
            knowledge.canonical_id,
        )
    session.commit()
    return result


def tree_payload(
    session: Session,
    space_code: str = "default",
    edition_code: str = "pep_math_2024_63",
) -> list[dict[str, Any]]:
    space = session.scalar(
        select(ContentSpace).where(ContentSpace.space_code == space_code)
    )
    edition = session.scalar(
        select(TextbookEdition).where(TextbookEdition.edition_code == edition_code)
    )
    if not space or not edition:
        return []
    nodes = list(
        session.scalars(
            select(CatalogNode)
            .where(
                CatalogNode.space_id == space.id,
                CatalogNode.edition_id == edition.id,
                CatalogNode.status != "disabled",
            )
            .order_by(CatalogNode.sort_order, CatalogNode.id)
        )
    )
    children: dict[int | None, list[CatalogNode]] = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)
    attachments = list(
        session.scalars(
            select(CatalogKnowledgeNode)
            .where(
                CatalogKnowledgeNode.space_id == space.id,
                CatalogKnowledgeNode.status != "disabled",
            )
            .order_by(CatalogKnowledgeNode.sort_order, CatalogKnowledgeNode.id)
        )
    )
    knowledge = {item.id: item for item in session.scalars(select(KnowledgeObject))}

    def build(node: CatalogNode) -> dict[str, Any]:
        result = {
            "id": f"node-{node.id}",
            "key": f"node-{node.id}",
            "title": node.title,
            "level": node.level,
            "nodeType": node.node_type,
            "status": node.status,
            "children": [build(item) for item in children.get(node.id, [])],
        }
        if node.level == 4:
            result["children"].extend(
                {
                    "id": f"knowledge-{item.id}",
                    "key": f"knowledge-{item.id}",
                    "title": knowledge[item.knowledge_id].name,
                    "level": 5,
                    "nodeType": "knowledge",
                    "canonicalId": knowledge[item.knowledge_id].canonical_id,
                    "status": knowledge[item.knowledge_id].status,
                    "children": [],
                }
                for item in attachments
                if item.group_node_id == node.id and item.knowledge_id in knowledge
            )
        return result

    return [build(node) for node in children.get(None, [])]


def tree_rows(session: Session, space_code: str = "default") -> list[CatalogNode]:
    space = session.scalar(
        select(ContentSpace).where(ContentSpace.space_code == space_code)
    )
    if not space:
        return []
    return list(
        session.scalars(
            select(CatalogNode)
            .where(CatalogNode.space_id == space.id, CatalogNode.status != "disabled")
            .order_by(CatalogNode.level, CatalogNode.sort_order, CatalogNode.id)
        )
    )


def list_policy_mappings(
    session: Session, canonical_id: str | None = None
) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(KnowledgePolicyMapping).order_by(KnowledgePolicyMapping.id)
        )
    )
    result = []
    for row in rows:
        knowledge = session.get(KnowledgeObject, row.knowledge_id)
        rule = session.get(PolicyRule, row.policy_rule_id)
        if (
            not knowledge
            or not rule
            or (canonical_id and knowledge.canonical_id != canonical_id)
        ):
            continue
        result.append(
            {
                "id": row.id,
                "canonicalId": knowledge.canonical_id,
                "policyRuleId": rule.id,
                "ruleCode": rule.rule_code,
                "ruleVersion": rule.rule_version,
                "title": rule.title,
                "applicableCondition": row.applicable_condition,
                "basis": row.basis,
                "status": row.status,
            }
        )
    return result


def create_policy_mapping(
    session: Session, data: PolicyMappingCreate, actor: str
) -> KnowledgePolicyMapping:
    space, _ = ensure_context(session, data.space_code)
    knowledge = get_knowledge(session, data.canonical_id)
    if not session.get(PolicyRule, data.policy_rule_id):
        raise BusinessError("NOT_FOUND", "政策规则不存在", 404)
    mapping = KnowledgePolicyMapping(
        space_id=space.id,
        knowledge_id=knowledge.id,
        policy_rule_id=data.policy_rule_id,
        applicable_condition=data.applicable_condition,
        basis=data.basis,
    )
    session.add(mapping)
    session.flush()
    _audit(
        session,
        actor,
        "policy_mapping.create",
        "knowledge_policy_mapping",
        str(mapping.id),
    )
    session.commit()
    return mapping
