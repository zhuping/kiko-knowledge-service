from __future__ import annotations

import csv
import hashlib
import io
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.ids import ulid
from app.core.security import AdminContext, require_role
from app.core.time import utcnow
from app.domains.audit.service import record
from app.domains.catalog.service import mutable_version
from app.models import (
    CurriculumNode,
    Exemplar,
    ExemplarObjective,
    ImportJob,
    Objective,
    ObjectiveExternalMapping,
    ObjectiveRelation,
)
from app.repositories import catalog as repo
from app.schemas.admin import ImportCreate

SECTIONS = {"nodes", "objectives", "relations", "exemplars", "mappings"}


def _parse_csv(content: str) -> dict:
    result = {section: [] for section in SECTIONS}
    for line_no, row in enumerate(csv.DictReader(io.StringIO(content)), start=2):
        section = row.get("record_type", "").strip()
        if section not in SECTIONS:
            raise ApiError(
                422,
                "IMPORT_INVALID",
                "CSV record_type 不合法",
                {"line": line_no},
            )
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except json.JSONDecodeError as exc:
            raise ApiError(
                422,
                "IMPORT_INVALID",
                "CSV payload_json 不是合法 JSON",
                {"line": line_no},
            ) from exc
        result[section].append(payload)
    return result


def parse_document(data: ImportCreate) -> dict:
    try:
        payload = (
            json.loads(data.content)
            if data.format == "json"
            else _parse_csv(data.content)
        )
    except json.JSONDecodeError as exc:
        raise ApiError(422, "IMPORT_INVALID", "导入内容不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise ApiError(422, "IMPORT_INVALID", "导入根节点必须是对象")
    unknown = set(payload) - SECTIONS
    if unknown:
        raise ApiError(
            422,
            "IMPORT_INVALID",
            "导入包含未知分区",
            {"sections": sorted(unknown)},
        )
    normalized = {section: payload.get(section, []) for section in SECTIONS}
    if any(not isinstance(items, list) for items in normalized.values()):
        raise ApiError(422, "IMPORT_INVALID", "导入分区必须是数组")
    return normalized


def preview_import(
    db: Session,
    actor: AdminContext,
    version_id: str,
    data: ImportCreate,
) -> ImportJob:
    version = mutable_version(db, version_id)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    source_hash = hashlib.sha256(data.content.encode()).hexdigest()
    existing = (
        db.query(ImportJob)
        .filter_by(package_version_id=version.id, source_hash=source_hash)
        .one_or_none()
    )
    if existing:
        return existing
    payload = parse_document(data)
    errors = validate_document(payload)
    job = ImportJob(
        package_version_id=version.id,
        source_hash=source_hash,
        status="validated" if not errors else "failed",
        preview_json={section: len(items) for section, items in payload.items()},
        errors_json=errors,
        payload_json=payload if not errors else None,
        created_by=actor.subject,
    )
    db.add(job)
    db.commit()
    return job


def validate_document(payload: dict) -> list[dict]:
    errors = []
    node_ids = [item.get("logical_id") for item in payload["nodes"]]
    objective_ids = [item.get("logical_id") for item in payload["objectives"]]
    if None in node_ids or len(node_ids) != len(set(node_ids)):
        errors.append({"code": "NODE_LOGICAL_ID_INVALID"})
    if None in objective_ids or len(objective_ids) != len(set(objective_ids)):
        errors.append({"code": "OBJECTIVE_LOGICAL_ID_INVALID"})
    node_set, objective_set = set(node_ids), set(objective_ids)
    for item in payload["nodes"]:
        if item.get("parent_logical_id") and item["parent_logical_id"] not in node_set:
            errors.append(
                {"code": "NODE_PARENT_UNKNOWN", "logical_id": item.get("logical_id")}
            )
    for item in payload["objectives"]:
        if item.get("node_logical_id") not in node_set:
            errors.append(
                {"code": "OBJECTIVE_NODE_UNKNOWN", "logical_id": item.get("logical_id")}
            )
    for item in payload["relations"]:
        if (
            item.get("source_objective_logical_id") not in objective_set
            or item.get("target_objective_logical_id") not in objective_set
        ):
            errors.append({"code": "RELATION_OBJECTIVE_UNKNOWN"})
    for item in payload["exemplars"]:
        links = item.get("objectives") or []
        if any(link.get("objective_logical_id") not in objective_set for link in links):
            errors.append(
                {
                    "code": "EXEMPLAR_OBJECTIVE_UNKNOWN",
                    "logical_id": item.get("logical_id"),
                }
            )
    return errors


def confirm_import(db: Session, actor: AdminContext, job_id: str) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if not job:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "导入任务不存在")
    version = mutable_version(db, job.package_version_id)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    if job.status == "imported":
        return job
    if job.status != "validated" or job.errors_json:
        raise ApiError(422, "IMPORT_INVALID", "导入内容未通过校验")
    payload = job.payload_json or {}
    try:
        _write_document(db, version.id, payload)
        job.status = "imported"
        job.payload_json = None
        record(
            db,
            actor_type="admin",
            actor_id=actor.subject,
            action="package.import",
            resource_type="import_job",
            resource_id=job.id,
            after=job.preview_json,
        )
        db.commit()
    except (KeyError, TypeError, ValueError, IntegrityError) as exc:
        db.rollback()
        job = db.get(ImportJob, job_id)
        job.status = "failed"
        job.errors_json = [{"code": "IMPORT_WRITE_FAILED", "message": str(exc)[:500]}]
        job.payload_json = None
        db.commit()
        raise ApiError(422, "IMPORT_INVALID", "导入写入失败") from exc
    return job


def _write_document(db: Session, version_id: str, payload: dict) -> None:
    node_map: dict[str, str] = {}
    for item in payload["nodes"]:
        node_map[item["logical_id"]] = ulid()
    pending = list(payload["nodes"])
    while pending:
        ready = [
            item
            for item in pending
            if not item.get("parent_logical_id")
            or item["parent_logical_id"] not in {row["logical_id"] for row in pending}
        ]
        if not ready:
            raise ValueError("课程目录形成环")
        for item in ready:
            db.add(
                CurriculumNode(
                    id=node_map[item["logical_id"]],
                    logical_id=item["logical_id"],
                    package_version_id=version_id,
                    parent_id=node_map.get(item.get("parent_logical_id")),
                    node_type=item["node_type"],
                    code=item["code"],
                    name=item["name"],
                    order_no=item["order_no"],
                    source_json=item.get("source"),
                    status=item.get("status", "active"),
                )
            )
            pending.remove(item)
    objective_map: dict[str, str] = {}
    for item in payload["objectives"]:
        objective_map[item["logical_id"]] = ulid()
        db.add(
            Objective(
                id=objective_map[item["logical_id"]],
                logical_id=item["logical_id"],
                package_version_id=version_id,
                node_id=node_map[item["node_logical_id"]],
                code=item["code"],
                name=item["name"],
                definition=item["definition"],
                attainment=item["attainment"],
                required_concepts_json=item.get("required_concepts", []),
                required_actions_json=item.get("required_actions", []),
                allowed_variations_json=item.get("allowed_variations", []),
                exclusions_json=item.get("exclusions", []),
                match_hints_json=item.get("match_hints"),
                source_json=item["source"],
                status=item.get("status", "active"),
            )
        )
    for item in payload["relations"]:
        db.add(
            ObjectiveRelation(
                package_version_id=version_id,
                source_objective_id=objective_map[item["source_objective_logical_id"]],
                target_objective_id=objective_map[item["target_objective_logical_id"]],
                relation_type=item["relation_type"],
                is_required=item.get("is_required", True),
                metadata_json=item.get("metadata"),
                created_at=utcnow(),
            )
        )
    for item in payload["exemplars"]:
        exemplar = Exemplar(
            logical_id=item.get("logical_id") or ulid(),
            package_version_id=version_id,
            exemplar_type=item["exemplar_type"],
            source_type=item["source_type"],
            source_json=item["source"],
            question_text=item["question_text"],
            options_json=item.get("options"),
            answer_json=item.get("answer"),
            solution_text=item.get("solution_text"),
            task_signature_json=item["task_signature"],
            media_json=item.get("media"),
            display_level=item.get("display_level", "reference"),
            status=item.get("status", "active"),
        )
        db.add(exemplar)
        for link in item["objectives"]:
            db.add(
                ExemplarObjective(
                    exemplar_id=exemplar.id,
                    objective_id=objective_map[link["objective_logical_id"]],
                    role=link["role"],
                    created_at=utcnow(),
                )
            )
    for item in payload["mappings"]:
        db.add(
            ObjectiveExternalMapping(
                package_version_id=version_id,
                objective_id=objective_map[item["objective_logical_id"]],
                namespace=item["namespace"],
                external_id=item["external_id"],
                metadata_json=item.get("metadata"),
                created_at=utcnow(),
            )
        )


def export_version(db: Session, version_id: str) -> dict:
    version = repo.get_version(db, version_id)
    if not version or version.status != "published":
        raise ApiError(409, "PACKAGE_NOT_PUBLISHED", "只能导出已发布版本")
    nodes = repo.list_nodes(db, version.id)
    objectives = repo.list_objectives(db, version.id)
    relations = repo.list_relations(db, version.id)
    exemplars = repo.list_exemplars(db, version.id)
    links = repo.list_exemplar_links(db, [item.id for item in exemplars])
    mappings = repo.list_mappings(db, version.id)
    node_logical = {item.id: item.logical_id for item in nodes}
    objective_logical = {item.id: item.logical_id for item in objectives}
    links_by_exemplar: dict[str, list] = {}
    for link in links:
        links_by_exemplar.setdefault(link.exemplar_id, []).append(link)
    document = {
        "version": version.version,
        "nodes": [
            {
                "logical_id": item.logical_id,
                "parent_logical_id": node_logical.get(item.parent_id),
                "node_type": item.node_type,
                "code": item.code,
                "name": item.name,
                "order_no": item.order_no,
                "source": item.source_json,
                "status": item.status,
            }
            for item in nodes
        ],
        "objectives": [
            {
                "logical_id": item.logical_id,
                "node_logical_id": node_logical[item.node_id],
                "code": item.code,
                "name": item.name,
                "definition": item.definition,
                "attainment": item.attainment,
                "required_concepts": item.required_concepts_json,
                "required_actions": item.required_actions_json,
                "allowed_variations": item.allowed_variations_json,
                "exclusions": item.exclusions_json,
                "match_hints": item.match_hints_json,
                "source": item.source_json,
                "status": item.status,
            }
            for item in objectives
        ],
        "relations": [
            {
                "source_objective_logical_id": objective_logical[
                    item.source_objective_id
                ],
                "target_objective_logical_id": objective_logical[
                    item.target_objective_id
                ],
                "relation_type": item.relation_type,
                "is_required": item.is_required,
                "metadata": item.metadata_json,
            }
            for item in relations
        ],
        "exemplars": [
            {
                "logical_id": item.logical_id,
                "exemplar_type": item.exemplar_type,
                "source_type": item.source_type,
                "source": item.source_json,
                "question_text": item.question_text
                if item.display_level in {"excerpt", "full"}
                else None,
                "options": item.options_json if item.display_level == "full" else None,
                "answer": item.answer_json if item.display_level == "full" else None,
                "solution_text": item.solution_text
                if item.display_level == "full"
                else None,
                "task_signature": item.task_signature_json,
                "display_level": item.display_level,
                "objectives": [
                    {
                        "objective_logical_id": objective_logical[link.objective_id],
                        "role": link.role,
                    }
                    for link in links_by_exemplar.get(item.id, [])
                ],
            }
            for item in exemplars
        ],
        "mappings": [
            {
                "objective_logical_id": objective_logical[item.objective_id],
                "namespace": item.namespace,
                "external_id": item.external_id,
                "metadata": item.metadata_json,
            }
            for item in mappings
        ],
    }
    canonical = json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    document["content_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    return document
