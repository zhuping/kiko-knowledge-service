from __future__ import annotations

import hashlib
import json
import logging
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.media import validate_media_urls
from app.core.time import utcnow
from app.domains.classification.runtime import normalize_question
from app.models import (
    ClassificationFeedback,
    ClassificationTask,
    ClassificationTaskPackage,
    ClientApp,
    Exemplar,
    Objective,
    ObjectiveExternalMapping,
    PackageVersion,
)
from app.repositories import catalog as catalog_repo
from app.repositories import classification as repo
from app.schemas.classification import ClassificationCreate, FeedbackCreate

logger = logging.getLogger(__name__)


def _allowed(client: ClientApp, package_id: str) -> bool:
    allowed = client.allowed_package_ids_json
    return allowed is None or package_id in allowed


def _request_snapshot(data: ClassificationCreate) -> dict:
    snapshot = data.model_dump(mode="json")
    snapshot["question"]["media_urls"] = [
        urlunsplit((*urlsplit(value)[:3], "", ""))
        for value in snapshot["question"]["media_urls"]
    ]
    return snapshot


def _published_version(db: Session, package_id: str, version: str):
    package = catalog_repo.get_package(db, package_id)
    if not package:
        raise ApiError(404, "UNKNOWN_PACKAGE", "知识包不存在")
    if version == "latest_stable":
        result = (
            db.get(PackageVersion, package.current_release_id)
            if package.current_release_id
            else None
        )
    else:
        result = catalog_repo.find_version(db, package.id, version, published_only=True)
    if not result or result.status != "published":
        raise ApiError(409, "PACKAGE_NOT_PUBLISHED", "知识包没有可用发布版本")
    return result


def _resolve_versions(db: Session, client: ClientApp, data: ClassificationCreate):
    context = data.curriculum_context
    package_roles = [
        (context.active_package_id, "active", context.active_package_version),
        *((item, "previous", "latest_stable") for item in context.previous_package_ids),
        *((item, "later", "latest_stable") for item in context.later_package_ids),
    ]
    resolved = []
    for package_id, role, version_name in package_roles:
        if not _allowed(client, package_id):
            raise ApiError(403, "ACCESS_DENIED", "调用方无权访问指定知识包")
        resolved.append((_published_version(db, package_id, version_name), role))
    active = next(item for item, role in resolved if role == "active")
    node_ids = {
        item.logical_id
        for item in catalog_repo.list_nodes(db, active.id)
        if item.status == "active"
    }
    requested_nodes = {
        *context.active_node_ids,
        *([context.learned_through_node_id] if context.learned_through_node_id else []),
    }
    if not requested_nodes <= node_ids:
        raise ApiError(400, "INVALID_REQUEST", "课程范围节点不属于当前发布版本")
    return active, resolved


def create_task(
    db: Session, client: ClientApp, data: ClassificationCreate
) -> ClassificationTask:
    existing = repo.find_idempotent_task(db, client.id, data.client_request_id)
    if existing:
        return existing
    if repo.recent_task_count(db, client.id) >= client.rate_limit_per_minute:
        raise ApiError(429, "RATE_LIMITED", "超过调用方每分钟判断限额")
    validate_media_urls(data.question.media_urls, client)
    active, versions = _resolve_versions(db, client, data)
    request_json = _request_snapshot(data)
    normalized = normalize_question(request_json)
    task = ClassificationTask(
        client_app_id=client.id,
        client_request_id=data.client_request_id,
        source_question_id=data.source_question_id,
        active_package_version_id=active.id,
        request_json=request_json,
        question_hash=hashlib.sha256(normalized.encode()).hexdigest(),
        status="received",
    )
    db.add(task)
    for version, role in versions:
        db.add(
            ClassificationTaskPackage(
                task_id=task.id,
                package_version_id=version.id,
                role=role,
                created_at=utcnow(),
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return repo.find_idempotent_task(db, client.id, data.client_request_id)
    _enqueue(task.id)
    return task


def _enqueue(task_id: str) -> None:
    try:
        from app.workers.classification import classify_task

        classify_task.delay(task_id)
    except Exception:
        logger.warning(
            "classification enqueue failed task_id=%s", task_id, exc_info=True
        )


def owned_task(db: Session, client: ClientApp, task_id: str):
    task = repo.get_task(db, task_id)
    if not task or task.client_app_id != client.id:
        raise ApiError(404, "CLASSIFICATION_NOT_FOUND", "判断任务不存在")
    return task


def _objective_data(db: Session, objective_id: str | None):
    if not objective_id:
        return None
    objective = db.get(Objective, objective_id)
    path = catalog_repo.node_path(db, objective.node_id)
    return {
        "id": objective.logical_id,
        "revision_id": objective.id,
        "name": objective.name,
        "curriculum_path": [item.name for item in path],
    }


def task_data(db: Session, client: ClientApp, task_id: str) -> dict:
    task = owned_task(db, client, task_id)
    result = repo.get_result(db, task.id)
    packages = repo.task_packages(db, task.id)
    versions = [db.get(PackageVersion, item.package_version_id) for item in packages]
    data = {
        "classification_id": task.id,
        "status": task.status,
        "result": None,
        "versions": {
            "active_knowledge_package": db.get(
                PackageVersion, task.active_package_version_id
            ).version,
            "searched_package_versions": [
                f"{item.package_id}@{item.version}" for item in versions
            ],
            "classifier": None,
            "prompt": None,
            "task_signature": "task-signature-v1",
        },
        "failure": (
            {"code": task.failure_code, "message": task.failure_message}
            if task.failure_code
            else None
        ),
    }
    if not result:
        return data
    result_objectives = repo.result_objectives(db, result.id)
    secondary = [
        _objective_data(db, item.objective_id)
        for item in result_objectives
        if item.role == "secondary"
    ]
    evidence = []
    for item in repo.result_evidence(db, result.id):
        exemplar = db.get(Exemplar, item.exemplar_id)
        objective = db.get(Objective, item.objective_id)
        source = exemplar.source_json or {}
        evidence.append(
            {
                "exemplar_id": exemplar.logical_id,
                "objective_id": objective.logical_id,
                "source_title": source.get("title") or source.get("book"),
                "source_location": source.get("location")
                or source.get("page")
                or source.get("question_no"),
                "reason_summary": item.reason_summary,
                "display_level": item.display_level,
            }
        )
    mappings = {}
    if result.primary_objective_id:
        for mapping in db.query(ObjectiveExternalMapping).filter_by(
            package_version_id=db.get(
                Objective, result.primary_objective_id
            ).package_version_id,
            objective_id=result.primary_objective_id,
        ):
            mappings[mapping.namespace] = mapping.external_id
    data["result"] = {
        "primary_objective": _objective_data(db, result.primary_objective_id),
        "secondary_objectives": secondary,
        "match_type": result.match_type,
        "scope_status": result.scope_status,
        "confidence": float(result.confidence_score),
        "requires_confirmation": result.requires_confirmation,
        "reason_summary": result.reason_summary,
        "evidence": evidence,
        "external_mappings": mappings,
    }
    data["versions"]["classifier"] = result.classifier_version
    data["versions"]["prompt"] = result.prompt_version
    return data


def create_feedback(
    db: Session,
    client: ClientApp,
    task_id: str,
    data: FeedbackCreate,
) -> ClassificationFeedback:
    task = owned_task(db, client, task_id)
    if task.status not in {"completed", "needs_review"}:
        raise ApiError(409, "FEEDBACK_CONFLICT", "判断尚未结束，不能提交反馈")
    correction = {
        "primary_objective_id": data.corrected_primary_objective_id,
        "secondary_objective_ids": data.corrected_secondary_objective_ids,
        "match_type": data.corrected_match_type,
        "scope_status": data.corrected_scope_status,
    }
    correction = {key: value for key, value in correction.items() if value is not None}
    request_id = (
        data.feedback_request_id
        or hashlib.sha256(
            json.dumps(
                {
                    "classification_id": task.id,
                    "confirmed": data.confirmed,
                    "correction": correction,
                    "reason": data.reason,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()[:32]
    )
    existing = repo.find_feedback(db, client.id, request_id)
    if existing:
        return existing
    logical_ids = {
        item
        for item in [
            data.corrected_primary_objective_id,
            *data.corrected_secondary_objective_ids,
        ]
        if item
    }
    version_ids = [item.package_version_id for item in repo.task_packages(db, task.id)]
    found = {
        item.logical_id
        for version_id in version_ids
        for item in catalog_repo.list_objectives(db, version_id)
        if item.logical_id in logical_ids
    }
    if found != logical_ids:
        raise ApiError(400, "INVALID_REQUEST", "修正目标不属于本次冻结知识包")
    feedback = ClassificationFeedback(
        classification_id=task.id,
        client_app_id=client.id,
        feedback_request_id=request_id,
        confirmed=data.confirmed,
        correction_json=correction or None,
        reason=data.reason,
        status="submitted",
    )
    db.add(feedback)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return repo.find_feedback(db, client.id, request_id)
    return feedback
