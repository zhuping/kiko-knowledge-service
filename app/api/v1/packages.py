from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.http import ok
from app.core.database import DbSession
from app.core.errors import ApiError
from app.core.security import ClientAppDependency
from app.domains.classification.client_catalog import (
    allowed_packages,
    objective_detail,
    objective_exemplars,
)
from app.models import ClientApp

router = APIRouter(tags=["client-catalog"])


@router.get("/packages")
def list_packages(db: Session = DbSession, client: ClientApp = ClientAppDependency):
    return ok(allowed_packages(db, client))


@router.get("/packages/{package_id}")
def get_package(
    package_id: str,
    db: Session = DbSession,
    client: ClientApp = ClientAppDependency,
):
    package = next(
        (item for item in allowed_packages(db, client) if item["id"] == package_id),
        None,
    )
    if not package:
        raise ApiError(404, "UNKNOWN_PACKAGE", "知识包不存在")
    return ok(package)


@router.get("/objectives/{logical_id}")
def get_objective(
    logical_id: str,
    db: Session = DbSession,
    client: ClientApp = ClientAppDependency,
):
    return ok(objective_detail(db, client, logical_id))


@router.get("/objectives/{logical_id}/exemplars")
def get_objective_exemplars(
    logical_id: str,
    db: Session = DbSession,
    client: ClientApp = ClientAppDependency,
):
    return ok(objective_exemplars(db, client, logical_id))
