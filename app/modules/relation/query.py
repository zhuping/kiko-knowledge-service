from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeObject, KnowledgeRelation
from app.modules.knowledge.service import _knowledge_statement, knowledge_response
from app.modules.relation.service import (
    _formal_versions,
    _group_for_knowledge,
    _latest_revisions,
    _status,
)
from app.schemas.catalog import RelationSearch


def list_relations(session: Session, data: RelationSearch) -> tuple[int, list[dict]]:
    statement = select(KnowledgeObject)
    if data.canonical_id:
        statement = statement.where(KnowledgeObject.canonical_id == data.canonical_id)
    if data.knowledge_name or data.grade_term_code or data.knowledge_type:
        statement = _knowledge_statement(
            type(
                "Search",
                (),
                {
                    "canonical_id": data.canonical_id,
                    "keyword": data.knowledge_name,
                    "grade_term_code": data.grade_term_code,
                    "knowledge_type": data.knowledge_type,
                    "scope": None,
                    "knowledge_base_id": data.knowledge_base_id,
                },
            )()
        )
    result = []
    for knowledge in session.scalars(statement.order_by(KnowledgeObject.id)):
        groups = _group_for_knowledge(session, knowledge.id)
        relation_rows = [
            row
            for row in _latest_revisions(session)
            if knowledge.id in {row.from_knowledge_id, row.to_knowledge_id}
        ]
        versions = []
        for relation_id in {row.relation_id for row in relation_rows}:
            versions.extend(_formal_versions(session, relation_id))
        seen = set()
        unique_versions = []
        for version in versions:
            key = (version["knowledgeBaseId"], version["releaseVersion"])
            if key not in seen:
                seen.add(key)
                unique_versions.append(version)
        pending = any(
            _status(session, session.get(KnowledgeRelation, row.relation_id))
            == "pending"
            for row in relation_rows
        )
        details = knowledge_response(session, knowledge)
        result.append(
            {
                "canonicalId": knowledge.canonical_id,
                "knowledgeName": details["knowledgeName"],
                "gradeTermCode": details["gradeTermCode"],
                **groups,
                "currentFormalVersions": unique_versions,
                "status": "pending" if pending else "published",
                "rowVersion": knowledge.row_version,
            }
        )
    if data.status:
        result = [item for item in result if item["status"] == data.status]
    total = len(result)
    start = (data.page_num - 1) * data.page_size
    return total, result[start : start + data.page_size]
