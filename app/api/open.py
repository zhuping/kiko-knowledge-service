from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.response import success
from app.core.security import verify_open_request
from app.models.operations import ApiClient
from app.modules.release.service import get_release_document
from app.schemas.catalog import DetailsRequest, GradeTerm, ScopeRequest, SearchRequest

router = APIRouter(prefix="/api/v1/open", tags=["open"])


def _tree(document: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    nodes = document.get("catalog_node", {})
    attachments = document.get("catalog_knowledge_node", {})
    knowledge = document.get("knowledge_object", {})
    knowledge_by_id = {int(item["id"]): item for item in knowledge.values()}
    children: dict[int | None, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes.values():
        children[node.get("parent_id")].append(node)
    for values in children.values():
        values.sort(key=lambda item: (item.get("sort_order", 0), item.get("id", 0)))

    def build(node: dict[str, Any]) -> dict[str, Any]:
        result = {
            "id": f"node-{node['id']}",
            "key": f"node-{node['id']}",
            "title": node["title"],
            "level": node["level"],
            "nodeType": node["node_type"],
            "status": node.get("status", "active"),
            "children": [build(child) for child in children.get(node["id"], [])],
        }
        if node["level"] == 4:
            result["children"].extend(
                {
                    "id": f"knowledge-{item['id']}",
                    "key": f"knowledge-{item['id']}",
                    "canonicalId": knowledge_by_id[int(item["knowledge_id"])][
                        "canonical_id"
                    ],
                    "title": knowledge_by_id[int(item["knowledge_id"])]["name"],
                    "level": 5,
                    "nodeType": "knowledge",
                    "status": knowledge_by_id[int(item["knowledge_id"])].get(
                        "status", "active"
                    ),
                    "children": [],
                }
                for item in sorted(
                    attachments.values(),
                    key=lambda value: (value.get("sort_order", 0), value.get("id", 0)),
                )
                if item.get("group_node_id") == node["id"]
                and int(item.get("knowledge_id")) in knowledge_by_id
            )
        return result

    return [build(node) for node in children.get(None, [])]


def _details(
    document: dict[str, dict[str, dict[str, Any]]], canonical_ids: list[str]
) -> list[dict[str, Any]]:
    knowledge = document.get("knowledge_object", {})
    mappings = document.get("textbook_mapping", {})
    relations = list(document.get("knowledge_relation", {}).values())
    by_canonical = {item.get("canonical_id"): item for item in knowledge.values()}
    by_id = {int(item.get("id")): item for item in knowledge.values()}
    result = []
    for canonical_id in canonical_ids:
        item = by_canonical.get(canonical_id)
        if not item:
            continue
        item_id = int(item["id"])
        prerequisites = []
        successors = []
        groups = {"parallel": [], "cross": []}
        for relation in relations:
            source = by_id.get(int(relation["from_knowledge_id"]))
            target = by_id.get(int(relation["to_knowledge_id"]))
            if not source or not target:
                continue
            if relation.get("relation_type") == "prerequisite":
                if int(relation["to_knowledge_id"]) == item_id:
                    prerequisites.append(source["canonical_id"])
                if int(relation["from_knowledge_id"]) == item_id:
                    successors.append(target["canonical_id"])
            elif relation.get("relation_type") in groups:
                other = (
                    source if int(relation["to_knowledge_id"]) == item_id else target
                )
                if other["id"] != item_id:
                    groups[relation["relation_type"]].append(other["canonical_id"])
        result.append(
            {
                "canonicalId": canonical_id,
                "knowledgeName": item["name"],
                "knowledgeType": item["type"],
                "gradeTerm": item["grade_term"],
                "scope": item["scope"],
                "cognitiveLevel": item["cognitive_level"],
                "importance": item["importance"],
                "aliases": item.get("aliases", []),
                "coreKeywords": item.get("core_keywords", []),
                "derivativeKeywords": item.get("derivative_keywords", []),
                "ocrSignals": item.get("ocr_signals", []),
                "exerciseSignature": item.get("exercise_signature"),
                "solutionFeature": item.get("solution_feature"),
                "sceneFeature": item.get("scene_feature"),
                "numericFeature": item.get("numeric_feature"),
                "status": item.get("status", "active"),
                "rowVersion": item.get("row_version", 1),
                "prerequisites": prerequisites,
                "successors": successors,
                "parallel": groups["parallel"],
                "cross": groups["cross"],
                "textbookMappings": [
                    {
                        "editionCode": mapping.get("edition_code"),
                        "textbookPath": mapping["textbook_path"],
                        "mappingType": mapping["mapping_type"],
                        "alignmentType": mapping["alignment_type"],
                        "editionLabel": mapping.get("edition_label"),
                        "editionKeywords": mapping.get("edition_keywords", []),
                        "pageStart": mapping.get("page_start"),
                        "pageEnd": mapping.get("page_end"),
                        "evidence": mapping.get("evidence"),
                    }
                    for mapping in mappings.values()
                    if int(mapping.get("knowledge_id")) == item_id
                    and mapping.get("status") != "disabled"
                ],
            }
        )
    return result


def _request_id(request: Request) -> str:
    return request.state.request_id


@router.get("/knowledge/tree")
def knowledge_tree(
    request: Request,
    release_version: str | None = Query(None, alias="releaseVersion"),
    db: Session = Depends(get_db),
    _client: ApiClient = Depends(verify_open_request),
):
    version, document = get_release_document(db, release_version)
    return success(_tree(document), _request_id(request), version.version_label)


@router.post("/knowledge/search")
def knowledge_search(
    payload: SearchRequest,
    request: Request,
    db: Session = Depends(get_db),
    _client: ApiClient = Depends(verify_open_request),
):
    version, document = get_release_document(db, payload.release_version)
    items = list(document.get("knowledge_object", {}).values())
    keyword = (payload.keyword or "").lower()
    items = [
        item
        for item in items
        if (
            not keyword
            or keyword in item["name"].lower()
            or any(keyword in term.lower() for term in item.get("aliases", []))
            or any(keyword in term.lower() for term in item.get("core_keywords", []))
            or any(
                keyword in term.lower() for term in item.get("derivative_keywords", [])
            )
            or any(keyword in term.lower() for term in item.get("ocr_signals", []))
        )
        and (not payload.canonical_id or item["canonical_id"] == payload.canonical_id)
        and (not payload.grade_term or item["grade_term"] == payload.grade_term)
        and (not payload.knowledge_type or item["type"] == payload.knowledge_type)
        and (not payload.scope or item["scope"] == payload.scope)
        and (not payload.status or item["status"] == payload.status)
    ]
    start = (payload.page_num - 1) * payload.page_size
    return success(
        {
            "total": len(items),
            "pageNum": payload.page_num,
            "pageSize": payload.page_size,
            "list": _details(
                document,
                [
                    item["canonical_id"]
                    for item in items[start : start + payload.page_size]
                ],
            ),
        },
        _request_id(request),
        version.version_label,
    )


@router.post("/knowledge/details:batch")
def knowledge_details(
    payload: DetailsRequest,
    request: Request,
    db: Session = Depends(get_db),
    _client: ApiClient = Depends(verify_open_request),
):
    version, document = get_release_document(db, payload.release_version)
    return success(
        _details(document, payload.canonical_ids[:100]),
        _request_id(request),
        version.version_label,
    )


@router.get("/knowledge/{canonical_id}/relations")
def knowledge_relations(
    canonical_id: str,
    request: Request,
    release_version: str | None = Query(None, alias="releaseVersion"),
    db: Session = Depends(get_db),
    _client: ApiClient = Depends(verify_open_request),
):
    version, document = get_release_document(db, release_version)
    details = _details(document, [canonical_id])
    if not details:
        return success({}, _request_id(request), version.version_label)
    detail = details[0]
    return success(
        {
            key: detail[key]
            for key in (
                "canonicalId",
                "prerequisites",
                "successors",
                "parallel",
                "cross",
            )
        },
        _request_id(request),
        version.version_label,
    )


@router.get("/knowledge/filter")
def knowledge_filter(
    request: Request,
    grade_term: GradeTerm | None = Query(None, alias="gradeTerm"),
    edition_code: str | None = Query(None, alias="editionCode"),
    release_version: str | None = Query(None, alias="releaseVersion"),
    db: Session = Depends(get_db),
    _client: ApiClient = Depends(verify_open_request),
):
    version, document = get_release_document(db, release_version)
    items = [
        item
        for item in document.get("knowledge_object", {}).values()
        if not grade_term or item["grade_term"] == grade_term
    ]
    if edition_code:
        mapped = {
            int(mapping["knowledge_id"])
            for mapping in document.get("textbook_mapping", {}).values()
            if mapping.get("edition_code") == edition_code
            and mapping.get("status") != "disabled"
        }
        items = [item for item in items if int(item["id"]) in mapped]
    return success(
        {"canonicalIds": [item["canonical_id"] for item in items]},
        _request_id(request),
        version.version_label,
    )


@router.post("/scope:check")
def check_scope(
    payload: ScopeRequest,
    request: Request,
    db: Session = Depends(get_db),
    _client: ApiClient = Depends(verify_open_request),
):
    version, document = get_release_document(db)
    details = _details(document, payload.canonical_ids)
    reasons = []
    if not payload.canonical_ids:
        reasons.append("业务端未提供已匹配的 canonicalIds")
    elif not details:
        reasons.append("正式知识快照中未找到对应知识对象")
    else:
        if payload.grade_term:
            details = [
                item for item in details if item["gradeTerm"] == payload.grade_term
            ]
            if not details:
                reasons.append("知识对象与请求年级不匹配")
        if payload.edition_code and details:
            if not any(
                mapping.get("editionCode") == payload.edition_code
                for item in details
                for mapping in item["textbookMappings"]
            ):
                reasons.append("知识对象未映射到请求教材版本")
    passed = bool(details) and not reasons
    return success(
        {
            "curriculumStatus": "课内" if passed else "未映射",
            "complianceStatus": "通过" if passed else "无依据",
            "reasons": reasons or ["正式知识对象与教材映射满足请求条件"],
        },
        _request_id(request),
        version.version_label,
    )
