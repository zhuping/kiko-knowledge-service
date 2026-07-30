from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.http import ok
from app.core.database import DbSession
from app.core.errors import ApiError
from app.core.security import AdminContext, get_admin_context, require_role
from app.core.serialization import model_dict
from app.domains.catalog.service import create_package
from app.domains.releases import service
from app.repositories import catalog as repo
from app.schemas.admin import PackageCreate, ReviewDecision, VersionCreate

router = APIRouter(prefix="/admin", tags=["admin-packages"])


def _version(db: Session, package_id: str, version_id: str):
    version = repo.get_version(db, version_id)
    if not version or version.package_id != package_id:
        raise ApiError(404, "PACKAGE_VERSION_NOT_FOUND", "知识包版本不存在")
    return version


@router.get("/me")
def me(actor: AdminContext = Depends(get_admin_context)):
    return ok({"subject": actor.subject, "roles": sorted(actor.roles)})


@router.get("/packages")
def list_packages(
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    global_access = any(package_id is None for _role, package_id in _actor.grants)
    allowed_ids = (
        None
        if global_access
        else list({_package_id for _role, _package_id in _actor.grants if _package_id})
    )
    return ok([model_dict(item) for item in repo.list_packages(db, allowed_ids)])


@router.post("/packages", status_code=201)
def post_package(
    data: PackageCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    package, version = create_package(db, actor, data)
    return ok({"package": model_dict(package), "version": model_dict(version)})


@router.get("/packages/{package_id}")
def get_package(
    package_id: str,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    package = repo.get_package(db, package_id)
    if not package:
        raise ApiError(404, "UNKNOWN_PACKAGE", "知识包不存在")
    require_role(
        _actor,
        "viewer",
        "editor",
        "reviewer",
        "publisher",
        "admin",
        package_id=package.id,
    )
    return ok(
        {
            **model_dict(package),
            "versions": [
                model_dict(item) for item in repo.list_versions(db, package.id)
            ],
        }
    )


@router.get("/packages/{package_id}/versions")
def list_versions(
    package_id: str,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    if not repo.get_package(db, package_id):
        raise ApiError(404, "UNKNOWN_PACKAGE", "知识包不存在")
    require_role(
        _actor,
        "viewer",
        "editor",
        "reviewer",
        "publisher",
        "admin",
        package_id=package_id,
    )
    return ok([model_dict(item) for item in repo.list_versions(db, package_id)])


@router.post("/packages/{package_id}/versions", status_code=201)
def post_version(
    package_id: str,
    data: VersionCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    return ok(model_dict(service.create_version(db, actor, package_id, data)))


@router.post("/packages/{package_id}/versions/{version_id}/submit-review")
def submit_review(
    package_id: str,
    version_id: str,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    return ok(model_dict(service.submit_review(db, actor, version_id)))


@router.post("/packages/{package_id}/versions/{version_id}/approve")
def approve(
    package_id: str,
    version_id: str,
    data: ReviewDecision,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    return ok(
        model_dict(service.review(db, actor, version_id, approved=True, note=data.note))
    )


@router.post("/packages/{package_id}/versions/{version_id}/reject")
def reject(
    package_id: str,
    version_id: str,
    data: ReviewDecision,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    return ok(
        model_dict(
            service.review(db, actor, version_id, approved=False, note=data.note)
        )
    )


@router.post("/packages/{package_id}/versions/{version_id}/publish")
def publish(
    package_id: str,
    version_id: str,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    _version(db, package_id, version_id)
    return ok(model_dict(service.publish(db, actor, version_id)))


@router.post("/packages/{package_id}/rollback/{version_id}")
def rollback(
    package_id: str,
    version_id: str,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    return ok(model_dict(service.rollback(db, actor, package_id, version_id)))
