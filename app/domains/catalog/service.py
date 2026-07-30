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
    CurriculumPackage,
    Exemplar,
    ExemplarObjective,
    Objective,
    ObjectiveExternalMapping,
    ObjectiveRelation,
    PackageVersion,
)
from app.repositories import catalog as repo
from app.schemas.admin import (
    ExemplarCreate,
    MappingCreate,
    NodeCreate,
    NodeUpdate,
    ObjectiveCreate,
    ObjectiveUpdate,
    PackageCreate,
    RelationCreate,
)


def _conflict(exc: IntegrityError):
    raise ApiError(409, "RESOURCE_CONFLICT", "编码、顺序或映射已存在") from exc


def mutable_version(db: Session, version_id: str) -> PackageVersion:
    version = repo.get_version(db, version_id)
    if not version:
        raise ApiError(404, "PACKAGE_VERSION_NOT_FOUND", "知识包版本不存在")
    if version.status != "draft":
        raise ApiError(
            409,
            "PACKAGE_VERSION_IMMUTABLE",
            "只有草稿版本允许编辑",
            {"status": version.status},
        )
    return version


def create_package(db: Session, actor: AdminContext, data: PackageCreate):
    require_role(actor, "editor", "admin")
    package = CurriculumPackage(
        code=data.code,
        subject_code=data.subject_code,
        grade=data.grade,
        semester=data.semester,
        edition=data.edition,
        publisher=data.publisher,
        curriculum_standard=data.curriculum_standard,
        region_json=data.regions,
    )
    version = PackageVersion(
        package_id=package.id,
        version=data.initial_version,
        status="draft",
        created_by=actor.subject,
    )
    db.add_all([package, version])
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action="package.create",
        resource_type="curriculum_package",
        resource_id=package.id,
        after={"code": package.code, "initial_version": version.version},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _conflict(exc)
    return package, version


def create_node(db: Session, actor: AdminContext, version_id: str, data: NodeCreate):
    version = mutable_version(db, version_id)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    if data.parent_id:
        parent = db.get(CurriculumNode, data.parent_id)
        if not parent or parent.package_version_id != version.id:
            raise ApiError(400, "INVALID_REQUEST", "父节点不属于当前版本")
    node = CurriculumNode(
        logical_id=data.logical_id or ulid(),
        package_version_id=version.id,
        parent_id=data.parent_id,
        node_type=data.node_type,
        code=data.code,
        name=data.name,
        order_no=data.order_no,
        source_json=data.source,
    )
    db.add(node)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _conflict(exc)
    return node


def _would_cycle(db: Session, node_id: str, parent_id: str | None) -> bool:
    seen = {node_id}
    current = db.get(CurriculumNode, parent_id) if parent_id else None
    while current:
        if current.id in seen:
            return True
        seen.add(current.id)
        current = (
            db.get(CurriculumNode, current.parent_id) if current.parent_id else None
        )
    return False


def update_node(db: Session, actor: AdminContext, node_id: str, data: NodeUpdate):
    node = db.get(CurriculumNode, node_id)
    if not node:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "课程节点不存在")
    version = mutable_version(db, node.package_version_id)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    if node.lock_version != data.lock_version:
        raise ApiError(409, "EDIT_CONFLICT", "课程节点已被其他人修改")
    values = data.model_dump(exclude_unset=True, exclude={"lock_version"})
    if "parent_id" in values:
        parent = (
            db.get(CurriculumNode, values["parent_id"]) if values["parent_id"] else None
        )
        if parent and parent.package_version_id != version.id:
            raise ApiError(400, "INVALID_REQUEST", "父节点不属于当前版本")
        if values["parent_id"] and not parent:
            raise ApiError(400, "INVALID_REQUEST", "父节点不存在")
        if _would_cycle(db, node.id, values["parent_id"]):
            raise ApiError(409, "CATALOG_CYCLE", "课程目录不能形成环")
    if "source" in values:
        values["source_json"] = values.pop("source")
    for key, value in values.items():
        setattr(node, key, value)
    node.lock_version += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _conflict(exc)
    return node


def create_objective(
    db: Session, actor: AdminContext, version_id: str, data: ObjectiveCreate
):
    version = mutable_version(db, version_id)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    node = db.get(CurriculumNode, data.node_id)
    if not node or node.package_version_id != version.id:
        raise ApiError(400, "INVALID_REQUEST", "教学目标节点不属于当前版本")
    objective = Objective(
        logical_id=data.logical_id or ulid(),
        package_version_id=version.id,
        node_id=data.node_id,
        code=data.code,
        name=data.name,
        definition=data.definition,
        attainment=data.attainment,
        required_concepts_json=data.required_concepts,
        required_actions_json=data.required_actions,
        allowed_variations_json=data.allowed_variations,
        exclusions_json=data.exclusions,
        match_hints_json=data.match_hints,
        source_json=data.source,
    )
    db.add(objective)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _conflict(exc)
    return objective


def update_objective(
    db: Session, actor: AdminContext, objective_id: str, data: ObjectiveUpdate
):
    objective = db.get(Objective, objective_id)
    if not objective:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "教学目标不存在")
    version = mutable_version(db, objective.package_version_id)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    if objective.lock_version != data.lock_version:
        raise ApiError(409, "EDIT_CONFLICT", "教学目标已被其他人修改")
    values = data.model_dump(exclude_unset=True, exclude={"lock_version"})
    if "node_id" in values:
        node = db.get(CurriculumNode, values["node_id"])
        if not node or node.package_version_id != version.id:
            raise ApiError(400, "INVALID_REQUEST", "教学目标节点不属于当前版本")
    aliases = {
        "required_concepts": "required_concepts_json",
        "required_actions": "required_actions_json",
        "allowed_variations": "allowed_variations_json",
        "exclusions": "exclusions_json",
        "match_hints": "match_hints_json",
        "source": "source_json",
    }
    for key, value in values.items():
        setattr(objective, aliases.get(key, key), value)
    objective.lock_version += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _conflict(exc)
    return objective


def _relation_cycle(
    db: Session, version_id: str, source_id: str, target_id: str
) -> bool:
    edges: dict[str, list[str]] = {}
    for relation in repo.list_relations(db, version_id):
        if relation.relation_type == "prerequisite_of":
            edges.setdefault(relation.source_objective_id, []).append(
                relation.target_objective_id
            )
    edges.setdefault(source_id, []).append(target_id)
    stack = [target_id]
    seen = set()
    while stack:
        current = stack.pop()
        if current == source_id:
            return True
        if current not in seen:
            seen.add(current)
            stack.extend(edges.get(current, []))
    return False


def create_relation(
    db: Session, actor: AdminContext, version_id: str, data: RelationCreate
):
    version = mutable_version(db, version_id)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    source = db.get(Objective, data.source_objective_id)
    target = db.get(Objective, data.target_objective_id)
    if (
        not source
        or not target
        or {
            source.package_version_id,
            target.package_version_id,
        }
        != {version.id}
    ):
        raise ApiError(400, "INVALID_REQUEST", "关系两端必须属于当前版本")
    if data.relation_type == "prerequisite_of" and _relation_cycle(
        db, version.id, source.id, target.id
    ):
        raise ApiError(409, "OBJECTIVE_RELATION_CYCLE", "前置关系不能形成环")
    relation = ObjectiveRelation(
        package_version_id=version.id,
        source_objective_id=source.id,
        target_objective_id=target.id,
        relation_type=data.relation_type,
        is_required=data.is_required,
        metadata_json=data.metadata,
        created_at=utcnow(),
    )
    db.add(relation)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _conflict(exc)
    return relation


def create_mapping(
    db: Session, actor: AdminContext, version_id: str, data: MappingCreate
):
    version = mutable_version(db, version_id)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    objective = db.get(Objective, data.objective_id)
    if not objective or objective.package_version_id != version.id:
        raise ApiError(400, "INVALID_REQUEST", "教学目标不属于当前版本")
    mapping = ObjectiveExternalMapping(
        package_version_id=version.id,
        objective_id=objective.id,
        namespace=data.namespace,
        external_id=data.external_id,
        metadata_json=data.metadata,
        created_at=utcnow(),
    )
    db.add(mapping)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _conflict(exc)
    return mapping


def create_exemplar(
    db: Session, actor: AdminContext, version_id: str, data: ExemplarCreate
):
    version = mutable_version(db, version_id)
    require_role(actor, "editor", "admin", package_id=version.package_id)
    roles = {link.role for link in data.objectives}
    if data.exemplar_type in {"prototype", "boundary"} and "primary" not in roles:
        raise ApiError(400, "INVALID_REQUEST", "正向样题至少关联一个主要目标")
    if data.exemplar_type == "counterexample" and "distractor" not in roles:
        raise ApiError(400, "INVALID_REQUEST", "反例至少关联一个易混淆目标")
    objective_ids = {link.objective_id for link in data.objectives}
    objectives = [db.get(Objective, objective_id) for objective_id in objective_ids]
    if any(not item or item.package_version_id != version.id for item in objectives):
        raise ApiError(400, "INVALID_REQUEST", "样题目标不属于当前版本")
    exemplar = Exemplar(
        logical_id=data.logical_id or ulid(),
        package_version_id=version.id,
        exemplar_type=data.exemplar_type,
        source_type=data.source_type,
        source_json=data.source,
        question_text=data.question_text,
        options_json=data.options,
        answer_json=data.answer,
        solution_text=data.solution_text,
        task_signature_json=data.task_signature,
        media_json=data.media,
        display_level=data.display_level,
    )
    db.add(exemplar)
    for link in data.objectives:
        db.add(
            ExemplarObjective(
                exemplar_id=exemplar.id,
                objective_id=link.objective_id,
                role=link.role,
                created_at=utcnow(),
            )
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _conflict(exc)
    return exemplar
