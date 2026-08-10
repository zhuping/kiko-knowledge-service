from sqlalchemy import func, select

from app.models import Job, KnowledgeObject, KnowledgeRelation
from app.seed import DEFAULT_SEED_DIR, SEED_FILES, seed_workbook


def test_seed_workbooks_are_complete_and_idempotent(client):
    imported_points = 0
    imported_relations = 0
    for filename in SEED_FILES:
        with client.app.state.session_factory() as session:
            points, relations = seed_workbook(session, DEFAULT_SEED_DIR / filename)
            imported_points += points
            imported_relations += relations

    assert imported_points == 203
    assert imported_relations == 223

    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeObject)) == 203
        assert (
            session.scalar(select(func.count()).select_from(KnowledgeRelation)) == 223
        )
        jobs = list(session.scalars(select(Job).order_by(Job.id)))
        assert len(jobs) == 2
        assert all((job.payload_json or {}).get("committed") for job in jobs)

        points, relations = seed_workbook(session, DEFAULT_SEED_DIR / SEED_FILES[0])
        assert (points, relations) == (0, 0)
