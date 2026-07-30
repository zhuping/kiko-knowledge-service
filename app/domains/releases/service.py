from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.ids import ulid
from app.core.security import AdminContext, require_role
from app.core.time import utcnow
from app.domains.audit.service import record
from app.models import (
    CurriculumNode,
    Exemplar,
    ExemplarObjective,
    Objective,
    ObjectiveExternalMapping,
    ObjectiveRelation,
    PackageVersion,
)
from app.repositories import catalog as repo
from app.schemas.admin import VersionCreate


def _version_or_404(db: Session, version_id: str, *, lock: bool = False):
    version = repo.get_version(db, version_id, lock=lock)
    if not version:
        raise ApiError(404, "PACKAGE_VERSION_NOT_FOUND", "知识包版本不存在")
    return version


def create_version(
    db: Session,
    actor: AdminContext,
    package_id: str,
    data: VersionCreate,
) -> PackageVersion:
    package = repo.get_package(db, package_id, lock=True)
    if not package:
        raise ApiError(404, "UNKNOWN_PACKAGE", "知识包不存在")
    require_role(actor, "editor", "admin", package_id=package.id)
    based_on_id = data.based_on_version_id or package.current_release_id
    based_on = _version_or_404(db, based_on_id) if based_on_id else None
    if based_on and (
        based_on.package_id != package.id or based_on.status != "published"
    ):
        raise ApiError(409, "PACKAGE_NOT_PUBLISHED", "草稿只能从已发布版本克隆")
    version = PackageVersion(
        package_id=package.id,
        version=data.version,
        status="draft",
        based_on_version_id=based_on.id if based_on else None,
        release_notes=data.release_notes,
        created_by=actor.subject,
    )
    db.add(version)
    db.flush()
    if based_on:
        _clone_content(db, based_on.id, version.id)
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action="package_version.create",
        resource_type="package_version",
        resource_id=version.id,
        after={"version": version.version, "based_on_version_id": based_on_id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "RESOURCE_CONFLICT", "知识包版本已存在") from exc
    return version


def _clone_content(db: Session, source_id: str, target_id: str) -> None:
    source_nodes = sorted(
        repo.list_nodes(db, source_id),
        key=lambda item: len(repo.node_path(db, item.id)),
    )
    node_map: dict[str, str] = {}
    for source in source_nodes:
        node_map[source.id] = ulid()
    for source in source_nodes:
        db.add(
            CurriculumNode(
                id=node_map[source.id],
                logical_id=source.logical_id,
                package_version_id=target_id,
                parent_id=node_map.get(source.parent_id),
                node_type=source.node_type,
                code=source.code,
                name=source.name,
                order_no=source.order_no,
                source_json=source.source_json,
                status=source.status,
            )
        )
    db.flush()
    objective_map: dict[str, str] = {}
    for source in repo.list_objectives(db, source_id):
        objective_map[source.id] = ulid()
        db.add(
            Objective(
                id=objective_map[source.id],
                logical_id=source.logical_id,
                package_version_id=target_id,
                node_id=node_map[source.node_id],
                code=source.code,
                name=source.name,
                definition=source.definition,
                attainment=source.attainment,
                required_concepts_json=source.required_concepts_json,
                required_actions_json=source.required_actions_json,
                allowed_variations_json=source.allowed_variations_json,
                exclusions_json=source.exclusions_json,
                match_hints_json=source.match_hints_json,
                source_json=source.source_json,
                status=source.status,
            )
        )
    for source in repo.list_relations(db, source_id):
        db.add(
            ObjectiveRelation(
                package_version_id=target_id,
                source_objective_id=objective_map[source.source_objective_id],
                target_objective_id=objective_map[source.target_objective_id],
                relation_type=source.relation_type,
                is_required=source.is_required,
                metadata_json=source.metadata_json,
                created_at=utcnow(),
            )
        )
    exemplar_map: dict[str, str] = {}
    exemplars = repo.list_exemplars(db, source_id)
    for source in exemplars:
        exemplar_map[source.id] = ulid()
        db.add(
            Exemplar(
                id=exemplar_map[source.id],
                logical_id=source.logical_id,
                package_version_id=target_id,
                exemplar_type=source.exemplar_type,
                source_type=source.source_type,
                source_json=source.source_json,
                question_text=source.question_text,
                options_json=source.options_json,
                answer_json=source.answer_json,
                solution_text=source.solution_text,
                task_signature_json=source.task_signature_json,
                media_json=source.media_json,
                display_level=source.display_level,
                status=source.status,
            )
        )
    for source in repo.list_exemplar_links(db, list(exemplar_map)):
        db.add(
            ExemplarObjective(
                exemplar_id=exemplar_map[source.exemplar_id],
                objective_id=objective_map[source.objective_id],
                role=source.role,
                created_at=utcnow(),
            )
        )
    for source in repo.list_mappings(db, source_id):
        db.add(
            ObjectiveExternalMapping(
                package_version_id=target_id,
                objective_id=objective_map[source.objective_id],
                namespace=source.namespace,
                external_id=source.external_id,
                metadata_json=source.metadata_json,
                created_at=utcnow(),
            )
        )


def _has_cycle(edges: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(target) for target in edges.get(node_id, [])):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in edges)


def validate_release(db: Session, version_id: str) -> list[dict]:
    version = _version_or_404(db, version_id)
    nodes = repo.list_nodes(db, version.id)
    objectives = repo.list_objectives(db, version.id, active_only=True)
    exemplars = repo.list_exemplars(db, version.id, active_only=True)
    links = repo.list_exemplar_links(db, [item.id for item in exemplars])
    relations = repo.list_relations(db, version.id)
    errors: list[dict] = []
    if not nodes:
        errors.append({"code": "CATALOG_EMPTY", "resource_id": version.id})
    if not objectives:
        errors.append({"code": "OBJECTIVES_EMPTY", "resource_id": version.id})
    objective_ids = {item.id for item in objectives}
    node_ids = {item.id for item in nodes if item.status == "active"}
    node_edges = {item.id: [item.parent_id] if item.parent_id else [] for item in nodes}
    if _has_cycle(node_edges):
        errors.append({"code": "CATALOG_CYCLE", "resource_id": version.id})
    prerequisite_edges: dict[str, list[str]] = {}
    for relation in relations:
        if relation.relation_type == "prerequisite_of":
            prerequisite_edges.setdefault(relation.source_objective_id, []).append(
                relation.target_objective_id
            )
    if _has_cycle(prerequisite_edges):
        errors.append({"code": "OBJECTIVE_RELATION_CYCLE", "resource_id": version.id})
    prototypes = {
        link.objective_id
        for link in links
        if link.role == "primary"
        and next(
            (
                exemplar.exemplar_type == "prototype" and exemplar.solution_text
                for exemplar in exemplars
                if exemplar.id == link.exemplar_id
            ),
            False,
        )
    }
    for objective in objectives:
        if objective.node_id not in node_ids:
            errors.append(
                {"code": "OBJECTIVE_NODE_INVALID", "resource_id": objective.id}
            )
        if not objective.source_json:
            errors.append(
                {"code": "OBJECTIVE_SOURCE_REQUIRED", "resource_id": objective.id}
            )
        if not objective.allowed_variations_json:
            errors.append(
                {"code": "OBJECTIVE_BOUNDARY_REQUIRED", "resource_id": objective.id}
            )
        if objective.id not in prototypes:
            errors.append(
                {"code": "OBJECTIVE_PROTOTYPE_REQUIRED", "resource_id": objective.id}
            )
    for link in links:
        if link.objective_id not in objective_ids:
            errors.append(
                {"code": "EXEMPLAR_OBJECTIVE_INVALID", "resource_id": link.id}
            )
    links_by_exemplar: dict[str, list[ExemplarObjective]] = {}
    for link in links:
        links_by_exemplar.setdefault(link.exemplar_id, []).append(link)
    for exemplar in exemplars:
        roles = {link.role for link in links_by_exemplar.get(exemplar.id, [])}
        if not exemplar.source_json or not exemplar.task_signature_json:
            errors.append(
                {"code": "EXEMPLAR_METADATA_REQUIRED", "resource_id": exemplar.id}
            )
        if (
            exemplar.exemplar_type in {"prototype", "boundary"}
            and "primary" not in roles
        ):
            errors.append(
                {"code": "EXEMPLAR_PRIMARY_REQUIRED", "resource_id": exemplar.id}
            )
        if exemplar.exemplar_type == "counterexample" and "distractor" not in roles:
            errors.append(
                {
                    "code": "COUNTEREXAMPLE_DISTRACTOR_REQUIRED",
                    "resource_id": exemplar.id,
                }
            )
    return errors


def submit_review(db: Session, actor: AdminContext, version_id: str):
    version = _version_or_404(db, version_id, lock=True)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    if version.status != "draft":
        raise ApiError(409, "INVALID_RELEASE_STATE", "只有草稿可以提交审核")
    errors = validate_release(db, version.id)
    if errors:
        raise ApiError(
            422,
            "RELEASE_VALIDATION_FAILED",
            "知识包完整性检查未通过",
            {"errors": errors},
        )
    version.status = "in_review"
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action="package_version.submit_review",
        resource_type="package_version",
        resource_id=version.id,
    )
    db.commit()
    return version


def review(
    db: Session,
    actor: AdminContext,
    version_id: str,
    *,
    approved: bool,
    note: str,
):
    version = _version_or_404(db, version_id, lock=True)
    require_role(actor, "reviewer", "admin", package_id=version.package_id)
    if version.status != "in_review":
        raise ApiError(409, "INVALID_RELEASE_STATE", "版本不在审核中")
    if approved and actor.subject == version.created_by:
        raise ApiError(409, "REVIEW_SEPARATION_REQUIRED", "创建者不能审核自己的版本")
    before = {"status": version.status}
    if approved:
        version.reviewed_by = actor.subject
        version.reviewed_at = utcnow()
    else:
        version.status = "draft"
        version.reviewed_by = None
        version.reviewed_at = None
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action="package_version.approve" if approved else "package_version.reject",
        resource_type="package_version",
        resource_id=version.id,
        before=before,
        after={"status": version.status, "note": note},
    )
    db.commit()
    return version


def publish(db: Session, actor: AdminContext, version_id: str):
    version = _version_or_404(db, version_id, lock=True)
    package = repo.get_package(db, version.package_id, lock=True)
    require_role(actor, "publisher", "admin", package_id=version.package_id)
    if version.status != "in_review" or not version.reviewed_by:
        raise ApiError(409, "INVALID_RELEASE_STATE", "版本尚未审核通过")
    if not (version.benchmark_result_json or {}).get("passed"):
        raise ApiError(422, "REGRESSION_GATE_FAILED", "黄金集回归未通过")
    version.status = "published"
    version.published_by = actor.subject
    version.published_at = utcnow()
    package.current_release_id = version.id
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action="package_version.publish",
        resource_type="package_version",
        resource_id=version.id,
        after={"version": version.version},
    )
    db.commit()
    return version


def rollback(db: Session, actor: AdminContext, package_id: str, version_id: str):
    package = repo.get_package(db, package_id, lock=True)
    version = _version_or_404(db, version_id, lock=True)
    if not package:
        raise ApiError(404, "UNKNOWN_PACKAGE", "知识包不存在")
    require_role(actor, "publisher", "admin", package_id=package.id)
    if version.package_id != package.id or version.status != "published":
        raise ApiError(409, "PACKAGE_NOT_PUBLISHED", "只能回滚到该知识包的已发布版本")
    previous = package.current_release_id
    package.current_release_id = version.id
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action="package.rollback",
        resource_type="curriculum_package",
        resource_id=package.id,
        before={"current_release_id": previous},
        after={"current_release_id": version.id},
    )
    db.commit()
    return version
