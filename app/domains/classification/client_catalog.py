from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import ClientApp, ExemplarObjective
from app.repositories import catalog as repo


def allowed_packages(db: Session, client: ClientApp) -> list[dict]:
    packages = repo.list_packages(db, client.allowed_package_ids_json)
    return [
        {
            "id": item.id,
            "code": item.code,
            "subject_code": item.subject_code,
            "grade": item.grade,
            "semester": item.semester,
            "edition": item.edition,
            "status": item.status,
            "current_release": (
                {
                    "id": version.id,
                    "version": version.version,
                    "published_at": version.published_at,
                }
                if (version := repo.current_version(db, item.id))
                else None
            ),
        }
        for item in packages
        if item.status == "active"
    ]


def _allowed_version_ids(db: Session, client: ClientApp) -> list[str]:
    return [
        package.current_release_id
        for package in repo.list_packages(db, client.allowed_package_ids_json)
        if package.status == "active" and package.current_release_id
    ]


def objective_detail(db: Session, client: ClientApp, logical_id: str) -> dict:
    objective = repo.objective_by_logical_id(
        db, _allowed_version_ids(db, client), logical_id
    )
    if not objective:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "教学目标不存在")
    path = repo.node_path(db, objective.node_id)
    mappings = {
        item.namespace: item.external_id
        for item in repo.list_mappings(db, objective.package_version_id)
        if item.objective_id == objective.id
    }
    return {
        "id": objective.logical_id,
        "revision_id": objective.id,
        "code": objective.code,
        "name": objective.name,
        "definition": objective.definition,
        "attainment": objective.attainment,
        "required_concepts": objective.required_concepts_json,
        "required_actions": objective.required_actions_json,
        "allowed_variations": objective.allowed_variations_json,
        "exclusions": objective.exclusions_json,
        "curriculum_path": [item.name for item in path],
        "external_mappings": mappings,
    }


def objective_exemplars(db: Session, client: ClientApp, logical_id: str) -> list[dict]:
    objective = repo.objective_by_logical_id(
        db, _allowed_version_ids(db, client), logical_id
    )
    if not objective:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "教学目标不存在")
    exemplars = {
        item.id: item
        for item in repo.list_exemplars(
            db, objective.package_version_id, active_only=True
        )
        if item.exemplar_type != "counterexample"
    }
    links = db.query(ExemplarObjective).filter_by(objective_id=objective.id).all()
    result = []
    for link in links:
        exemplar = exemplars.get(link.exemplar_id)
        if not exemplar or link.role not in {"primary", "supporting"}:
            continue
        source = exemplar.source_json or {}
        result.append(
            {
                "id": exemplar.logical_id,
                "type": exemplar.exemplar_type,
                "source_title": source.get("title") or source.get("book"),
                "source_location": source.get("location") or source.get("page"),
                "display_level": exemplar.display_level,
                "question_text": exemplar.question_text
                if exemplar.display_level in {"excerpt", "full"}
                else None,
                "answer": exemplar.answer_json
                if exemplar.display_level == "full"
                else None,
                "solution_text": exemplar.solution_text
                if exemplar.display_level == "full"
                else None,
            }
        )
    return result
