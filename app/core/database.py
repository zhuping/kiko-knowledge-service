from __future__ import annotations

from fastapi import Depends
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.errors import ApiError

engine_options = {"pool_pre_ping": True}
if settings.database_url == "sqlite://":
    engine_options.update(
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db


DbSession = Depends(get_db)


def check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _content_version_id(session: Session, item) -> str | None:
    from app.models import Exemplar, ExemplarObjective

    version_id = getattr(item, "package_version_id", None)
    if version_id:
        return version_id
    if isinstance(item, ExemplarObjective):
        exemplar = session.get(Exemplar, item.exemplar_id)
        return exemplar.package_version_id if exemplar else None
    return None


@event.listens_for(Session, "before_flush")
def prevent_published_content_changes(session: Session, _context, _instances) -> None:
    from app.models import (
        CurriculumNode,
        Exemplar,
        ExemplarObjective,
        Objective,
        ObjectiveExternalMapping,
        ObjectiveRelation,
        PackageVersion,
    )

    content_types = (
        CurriculumNode,
        Objective,
        ObjectiveRelation,
        Exemplar,
        ExemplarObjective,
        ObjectiveExternalMapping,
    )
    content_changed = [
        item
        for item in session.new.union(session.dirty).union(session.deleted)
        if isinstance(item, content_types)
        and (
            item in session.new or item in session.deleted or session.is_modified(item)
        )
    ]
    with session.no_autoflush:
        for version in session.deleted:
            if isinstance(version, PackageVersion) and version.status in {
                "published",
                "deprecated",
            }:
                raise ApiError(
                    409,
                    "PACKAGE_VERSION_IMMUTABLE",
                    "已发布版本不可删除",
                    {"package_version_id": version.id},
                )
        for version in session.dirty:
            if not isinstance(version, PackageVersion):
                continue
            state = inspect(version)
            history = state.attrs.status.history
            original_status = history.deleted[0] if history.deleted else version.status
            changed_fields = {
                attribute.key
                for attribute in state.attrs
                if attribute.history.has_changes()
            }
            deprecating = (
                original_status == "published"
                and version.status == "deprecated"
                and changed_fields <= {"status", "updated_at"}
            )
            if original_status in {"published", "deprecated"} and not deprecating:
                raise ApiError(
                    409,
                    "PACKAGE_VERSION_IMMUTABLE",
                    "已发布版本元数据不可修改",
                    {"package_version_id": version.id},
                )
        for item in content_changed:
            version_id = _content_version_id(session, item)
            version = session.get(PackageVersion, version_id) if version_id else None
            if version and version.status in {"published", "deprecated"}:
                raise ApiError(
                    409,
                    "PACKAGE_VERSION_IMMUTABLE",
                    "已发布版本不可修改",
                    {"package_version_id": version.id},
                )
