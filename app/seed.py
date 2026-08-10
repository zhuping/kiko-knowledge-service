from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import create_database_engine
from app.models import KnowledgeObject
from app.modules.import_export.service import (
    _validate,
    commit_import_job,
    create_import_job,
)

SEED_FILES = (
    "01-一年级数学原子知识点.xlsx",
    "02-二年级数学原子知识点.xlsx",
)
DEFAULT_SEED_DIR = Path(__file__).resolve().parents[1] / "seed_data"
SEED_ACTOR = "system:db-init"
SEED_REQUEST_ID = "db-init"


def seed_workbook(session: Session, path: Path) -> tuple[int, int]:
    total, errors, records = _validate(path.read_bytes())
    if errors:
        raise RuntimeError(f"种子文件校验失败：{path.name}，错误数 {len(errors)}")

    ids = {record["canonical_id"] for record in records}
    existing = set(
        session.scalars(
            select(KnowledgeObject.canonical_id).where(
                KnowledgeObject.canonical_id.in_(ids)
            )
        )
    )
    if existing:
        if existing != ids:
            missing = ", ".join(sorted(ids - existing))
            raise RuntimeError(f"种子数据不完整：{path.name} 缺少 {missing}")
        return 0, 0

    job = create_import_job(
        session,
        path.name,
        path.read_bytes(),
        SEED_ACTOR,
        SEED_REQUEST_ID,
    )
    commit_import_job(session, job.id, SEED_ACTOR, SEED_REQUEST_ID)
    relation_count = sum(len(record["prerequisites"]) for record in records)
    return total, relation_count


def seed_knowledge_workbooks(
    database_url: str | None = None, seed_dir: Path = DEFAULT_SEED_DIR
) -> tuple[int, int]:
    settings = Settings()
    engine = create_database_engine(database_url or settings.database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    point_count = 0
    relation_count = 0
    try:
        for filename in SEED_FILES:
            path = seed_dir / filename
            if not path.is_file():
                raise FileNotFoundError(f"未找到知识点种子文件：{path}")
            with session_factory() as session:
                points, relations = seed_workbook(session, path)
                point_count += points
                relation_count += relations
    finally:
        engine.dispose()
    return point_count, relation_count


if __name__ == "__main__":
    points, relations = seed_knowledge_workbooks()
    print(f"知识点种子完成：新增 {points} 个知识点、{relations} 条前置关系")
