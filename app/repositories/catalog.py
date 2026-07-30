from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def get_package(db: Session, package_id: str, *, lock: bool = False):
    query = select(CurriculumPackage).where(CurriculumPackage.id == package_id)
    return db.scalar(query.with_for_update() if lock else query)


def get_version(db: Session, version_id: str, *, lock: bool = False):
    query = select(PackageVersion).where(PackageVersion.id == version_id)
    return db.scalar(query.with_for_update() if lock else query)


def find_version(
    db: Session, package_id: str, version: str, *, published_only: bool = False
):
    query = select(PackageVersion).where(
        PackageVersion.package_id == package_id, PackageVersion.version == version
    )
    if published_only:
        query = query.where(PackageVersion.status == "published")
    return db.scalar(query)


def current_version(db: Session, package_id: str):
    package = get_package(db, package_id)
    return (
        db.get(PackageVersion, package.current_release_id)
        if package and package.current_release_id
        else None
    )


def list_packages(db: Session, allowed_ids: list[str] | None = None):
    query = select(CurriculumPackage).order_by(CurriculumPackage.code)
    if allowed_ids is not None:
        query = query.where(CurriculumPackage.id.in_(allowed_ids))
    return list(db.scalars(query))


def list_versions(db: Session, package_id: str):
    return list(
        db.scalars(
            select(PackageVersion)
            .where(PackageVersion.package_id == package_id)
            .order_by(PackageVersion.created_at.desc())
        )
    )


def list_nodes(db: Session, version_id: str):
    return list(
        db.scalars(
            select(CurriculumNode)
            .where(CurriculumNode.package_version_id == version_id)
            .order_by(CurriculumNode.order_no, CurriculumNode.id)
        )
    )


def list_objectives(db: Session, version_id: str, *, active_only: bool = False):
    query = select(Objective).where(Objective.package_version_id == version_id)
    if active_only:
        query = query.where(Objective.status == "active")
    return list(db.scalars(query.order_by(Objective.code)))


def list_relations(db: Session, version_id: str):
    return list(
        db.scalars(
            select(ObjectiveRelation).where(
                ObjectiveRelation.package_version_id == version_id
            )
        )
    )


def list_exemplars(db: Session, version_id: str, *, active_only: bool = False):
    query = select(Exemplar).where(Exemplar.package_version_id == version_id)
    if active_only:
        query = query.where(Exemplar.status == "active")
    return list(db.scalars(query.order_by(Exemplar.created_at)))


def list_exemplar_links(db: Session, exemplar_ids: list[str]):
    if not exemplar_ids:
        return []
    return list(
        db.scalars(
            select(ExemplarObjective).where(
                ExemplarObjective.exemplar_id.in_(exemplar_ids)
            )
        )
    )


def list_mappings(db: Session, version_id: str):
    return list(
        db.scalars(
            select(ObjectiveExternalMapping).where(
                ObjectiveExternalMapping.package_version_id == version_id
            )
        )
    )


def objective_by_logical_id(db: Session, version_ids: list[str], logical_id: str):
    if not version_ids:
        return None
    return db.scalar(
        select(Objective).where(
            Objective.package_version_id.in_(version_ids),
            Objective.logical_id == logical_id,
            Objective.status == "active",
        )
    )


def node_path(db: Session, node_id: str) -> list[CurriculumNode]:
    path = []
    seen = set()
    current = db.get(CurriculumNode, node_id)
    while current:
        if current.id in seen:
            break
        seen.add(current.id)
        path.append(current)
        current = (
            db.get(CurriculumNode, current.parent_id) if current.parent_id else None
        )
    return list(reversed(path))
