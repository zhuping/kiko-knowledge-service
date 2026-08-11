from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import KnowledgeObject
from app.modules.knowledge.service import _create_revision
from app.modules.relation.query import list_relations
from app.modules.relation.service import _create_edge
from app.schemas.catalog import RelationSearch


def _create_points(session: Session, count: int) -> list[KnowledgeObject]:
    points = []
    for index in range(count):
        point = KnowledgeObject(
            canonical_id=f"1{index + 1:07d}",
            created_by="test",
            updated_by="test",
        )
        session.add(point)
        session.flush()
        _create_revision(
            session,
            point,
            {
                "name": f"测试知识点 {index}",
                "type": "skill",
                "grade_term": "g1_t1",
                "scope": "core",
                "ocr_signals": [],
                "exercise_signature": None,
            },
            "test",
        )
        points.append(point)
    return points


def test_relation_list_pages_and_batches_detail_queries(client):
    with client.app.state.session_factory() as session:
        points = _create_points(session, 25)
        _create_edge(session, points[0], points[1], "prerequisite", None, "test")
        session.commit()

    query_count = 0

    def count_query(*_args):
        nonlocal query_count
        query_count += 1

    event.listen(client.app.state.engine, "before_cursor_execute", count_query)
    try:
        with client.app.state.session_factory() as session:
            total, rows = list_relations(
                session, RelationSearch(page_num=1, page_size=10)
            )
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", count_query)

    assert total == 2
    assert len(rows) == 2
    assert query_count <= 6
    assert rows[0]["successors"] == [
        {"canonicalId": "10000002", "knowledgeName": "测试知识点 1"}
    ]
    assert rows[0]["status"] == "pending"
    with client.app.state.session_factory() as session:
        pending_total, pending_rows = list_relations(
            session,
            RelationSearch(status="pending", page_num=1, page_size=20),
        )
        published_total, published_rows = list_relations(
            session,
            RelationSearch(status="published", page_num=1, page_size=20),
        )

    assert pending_total == 2
    assert len(pending_rows) == 2
    assert published_total == 0
    assert published_rows == []

    with client.app.state.session_factory() as session:
        total, rows = list_relations(
            session,
            RelationSearch(knowledge_base_id=999999, page_num=1, page_size=20),
        )

    assert total == 0
    assert rows == []
