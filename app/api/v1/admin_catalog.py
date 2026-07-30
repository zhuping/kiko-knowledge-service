from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.http import ok
from app.core.database import DbSession
from app.core.errors import ApiError
from app.core.security import AdminContext, get_admin_context, require_role
from app.core.serialization import model_dict
from app.domains.catalog import import_export, service
from app.models import CurriculumNode, Objective
from app.repositories import catalog as repo
from app.schemas.admin import (
    ExemplarCreate,
    ImportCreate,
    MappingCreate,
    NodeCreate,
    NodeUpdate,
    ObjectiveCreate,
    ObjectiveUpdate,
    RelationCreate,
)

router = APIRouter(prefix="/admin", tags=["admin-catalog"])


def _version(db: Session, package_id: str, version_id: str):
    version = repo.get_version(db, version_id)
    if not version or version.package_id != package_id:
        raise ApiError(404, "PACKAGE_VERSION_NOT_FOUND", "知识包版本不存在")
    return version


def _require_read(actor: AdminContext, package_id: str) -> None:
    require_role(
        actor,
        "viewer",
        "editor",
        "reviewer",
        "publisher",
        "admin",
        package_id=package_id,
    )


@router.get("/packages/{package_id}/versions/{version_id}/catalog")
def catalog(
    package_id: str,
    version_id: str,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    _require_read(_actor, package_id)
    return ok([model_dict(item) for item in repo.list_nodes(db, version_id)])


@router.post("/packages/{package_id}/versions/{version_id}/catalog", status_code=201)
def post_node(
    package_id: str,
    version_id: str,
    data: NodeCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    return ok(model_dict(service.create_node(db, actor, version_id, data)))


@router.patch("/packages/{package_id}/versions/{version_id}/catalog/{node_id}")
def patch_node(
    package_id: str,
    version_id: str,
    node_id: str,
    data: NodeUpdate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    node = db.get(CurriculumNode, node_id)
    if not node or node.package_version_id != version_id:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "课程节点不存在")
    node = service.update_node(db, actor, node_id, data)
    return ok(model_dict(node))


@router.get("/packages/{package_id}/versions/{version_id}/objectives")
def objectives(
    package_id: str,
    version_id: str,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    _require_read(_actor, package_id)
    return ok([model_dict(item) for item in repo.list_objectives(db, version_id)])


@router.post("/packages/{package_id}/versions/{version_id}/objectives", status_code=201)
def post_objective(
    package_id: str,
    version_id: str,
    data: ObjectiveCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    return ok(model_dict(service.create_objective(db, actor, version_id, data)))


@router.patch("/packages/{package_id}/versions/{version_id}/objectives/{objective_id}")
def patch_objective(
    package_id: str,
    version_id: str,
    objective_id: str,
    data: ObjectiveUpdate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    objective = db.get(Objective, objective_id)
    if not objective or objective.package_version_id != version_id:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "教学目标不存在")
    objective = service.update_objective(db, actor, objective_id, data)
    return ok(model_dict(objective))


@router.post("/packages/{package_id}/versions/{version_id}/relations", status_code=201)
def post_relation(
    package_id: str,
    version_id: str,
    data: RelationCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    return ok(model_dict(service.create_relation(db, actor, version_id, data)))


@router.post("/packages/{package_id}/versions/{version_id}/mappings", status_code=201)
def post_mapping(
    package_id: str,
    version_id: str,
    data: MappingCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    return ok(model_dict(service.create_mapping(db, actor, version_id, data)))


@router.get("/packages/{package_id}/versions/{version_id}/exemplars")
def exemplars(
    package_id: str,
    version_id: str,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    _require_read(_actor, package_id)
    return ok([model_dict(item) for item in repo.list_exemplars(db, version_id)])


@router.post("/packages/{package_id}/versions/{version_id}/exemplars", status_code=201)
def post_exemplar(
    package_id: str,
    version_id: str,
    data: ExemplarCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    return ok(model_dict(service.create_exemplar(db, actor, version_id, data)))


@router.post("/packages/{package_id}/versions/{version_id}/imports", status_code=201)
def preview_import(
    package_id: str,
    version_id: str,
    data: ImportCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    job = import_export.preview_import(db, actor, version_id, data)
    return ok(model_dict(job, exclude={"payload_json"}))


@router.post("/import-jobs/{job_id}/confirm")
def confirm_import(
    job_id: str,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    job = import_export.confirm_import(db, actor, job_id)
    return ok(model_dict(job, exclude={"payload_json"}))


@router.get("/packages/{package_id}/versions/{version_id}/export")
def export(
    package_id: str,
    version_id: str,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    _require_read(_actor, package_id)
    return ok(import_export.export_version(db, version_id))
