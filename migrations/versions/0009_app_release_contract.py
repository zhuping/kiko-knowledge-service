"""freeze App-facing release metadata and mapping order."""

import hashlib
import json
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "0009_app_release_contract"
down_revision = "0008_catalog_root_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in (
            "knowledge_base_mapping",
            "release_mapping",
            "release_version",
        )
    }
    if "sort_order" not in existing["knowledge_base_mapping"]:
        op.add_column(
            "knowledge_base_mapping",
            sa.Column("sort_order", sa.Integer(), nullable=True),
        )
    if "sort_order" not in existing["release_mapping"]:
        op.add_column(
            "release_mapping", sa.Column("sort_order", sa.Integer(), nullable=True)
        )
    for name, length in (
        ("knowledge_base_name", 200),
        ("grade_term", 32),
        ("subject", 50),
        ("textbook_edition_code", 64),
        ("textbook_edition_name", 200),
    ):
        if name not in existing["release_version"]:
            op.add_column(
                "release_version", sa.Column(name, sa.String(length), nullable=True)
            )

    draft_order: defaultdict[tuple[int, int], int] = defaultdict(int)
    rows = bind.execute(
        sa.text(
            "SELECT id, knowledge_base_id, catalog_node_id "
            "FROM knowledge_base_mapping ORDER BY id"
        )
    )
    for row in rows:
        key = (row.knowledge_base_id, row.catalog_node_id)
        draft_order[key] += 1
        bind.execute(
            sa.text(
                "UPDATE knowledge_base_mapping SET sort_order=:sort_order WHERE id=:id"
            ),
            {"id": row.id, "sort_order": draft_order[key]},
        )

    release_order: defaultdict[tuple[int, int], int] = defaultdict(int)
    rows = bind.execute(
        sa.text(
            "SELECT id, release_id, catalog_node_id FROM release_mapping ORDER BY id"
        )
    )
    for row in rows:
        key = (row.release_id, row.catalog_node_id)
        release_order[key] += 1
        bind.execute(
            sa.text("UPDATE release_mapping SET sort_order=:sort_order WHERE id=:id"),
            {"id": row.id, "sort_order": release_order[key]},
        )

    releases = bind.execute(
        sa.text(
            "SELECT rv.id, kb.name, kb.grade_term, kb.subject, "
            "te.edition_code, te.edition_name "
            "FROM release_version rv "
            "JOIN knowledge_base kb ON kb.id=rv.knowledge_base_id "
            "JOIN textbook_edition te ON te.id=kb.textbook_edition_id"
        )
    )
    for row in releases:
        bind.execute(
            sa.text(
                "UPDATE release_version SET knowledge_base_name=:name, "
                "grade_term=:grade_term, subject=:subject, "
                "textbook_edition_code=:edition_code, "
                "textbook_edition_name=:edition_name WHERE id=:id"
            ),
            row._mapping,
        )

    releases = bind.execute(
        sa.text(
            "SELECT id, knowledge_base_name, grade_term, subject, "
            "textbook_edition_code, textbook_edition_name FROM release_version"
        )
    ).mappings()
    for release in releases:
        release_id = release["id"]
        nodes = bind.execute(
            sa.text(
                "SELECT catalog_node_id, parent_id, level, node_type, source_key, "
                "title, source_path, sort_order FROM release_catalog_node "
                "WHERE release_id=:release_id ORDER BY catalog_node_id"
            ),
            {"release_id": release_id},
        ).all()
        mappings = bind.execute(
            sa.text(
                "SELECT catalog_node_id, knowledge_id, sort_order "
                "FROM release_mapping WHERE release_id=:release_id "
                "ORDER BY catalog_node_id, knowledge_id"
            ),
            {"release_id": release_id},
        ).all()
        knowledge = bind.execute(
            sa.text(
                "SELECT rk.knowledge_id, kr.content_hash FROM release_knowledge rk "
                "JOIN knowledge_revision kr ON kr.id=rk.revision_id "
                "WHERE rk.release_id=:release_id ORDER BY rk.knowledge_id"
            ),
            {"release_id": release_id},
        ).all()
        relations = bind.execute(
            sa.text(
                "SELECT rr.relation_id, rev.content_hash FROM release_relation rr "
                "JOIN relation_revision rev ON rev.id=rr.relation_revision_id "
                "WHERE rr.release_id=:release_id ORDER BY rr.relation_id"
            ),
            {"release_id": release_id},
        ).all()
        payload = {
            "metadata": [
                release["knowledge_base_name"],
                release["grade_term"],
                release["subject"],
                release["textbook_edition_code"],
                release["textbook_edition_name"],
            ],
            "nodes": [list(row) for row in nodes],
            "mappings": [list(row) for row in mappings],
            "knowledge": [list(row) for row in knowledge],
            "relations": [list(row) for row in relations],
        }
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        bind.execute(
            sa.text(
                "UPDATE release_version SET content_hash=:content_hash WHERE id=:id"
            ),
            {
                "id": release_id,
                "content_hash": hashlib.sha256(raw.encode()).hexdigest(),
            },
        )

    def ensure_contract(table: str, columns: list[str], name: str) -> None:
        current = sa.inspect(bind)
        nullable = next(
            column["nullable"]
            for column in current.get_columns(table)
            if column["name"] == columns[-1]
        )
        constraints = {
            tuple(constraint["column_names"])
            for constraint in current.get_unique_constraints(table)
        }
        with op.batch_alter_table(table) as batch:
            if nullable:
                batch.alter_column(
                    columns[-1], existing_type=sa.Integer(), nullable=False
                )
            if tuple(columns) not in constraints:
                batch.create_unique_constraint(name, columns)

    ensure_contract(
        "knowledge_base_mapping",
        ["knowledge_base_id", "catalog_node_id", "sort_order"],
        "uq_kb_mapping_order",
    )
    ensure_contract(
        "release_mapping",
        ["release_id", "catalog_node_id", "sort_order"],
        "uq_release_mapping_order",
    )
    release_columns = {
        column["name"]: column
        for column in sa.inspect(bind).get_columns("release_version")
    }
    nullable_release_fields = [
        name
        for name in (
            "knowledge_base_name",
            "grade_term",
            "subject",
            "textbook_edition_code",
            "textbook_edition_name",
        )
        if release_columns[name]["nullable"]
    ]
    if nullable_release_fields:
        release_types = {
            "knowledge_base_name": sa.String(200),
            "grade_term": sa.String(32),
            "subject": sa.String(50),
            "textbook_edition_code": sa.String(64),
            "textbook_edition_name": sa.String(200),
        }
        with op.batch_alter_table("release_version") as batch:
            for name in nullable_release_fields:
                batch.alter_column(
                    name, existing_type=release_types[name], nullable=False
                )


def downgrade() -> None:
    with op.batch_alter_table("release_mapping") as batch:
        batch.drop_constraint("uq_release_mapping_order", type_="unique")
        batch.drop_column("sort_order")
    with op.batch_alter_table("knowledge_base_mapping") as batch:
        batch.drop_constraint("uq_kb_mapping_order", type_="unique")
        batch.drop_column("sort_order")
    with op.batch_alter_table("release_version") as batch:
        for name in (
            "textbook_edition_name",
            "textbook_edition_code",
            "subject",
            "grade_term",
            "knowledge_base_name",
        ):
            batch.drop_column(name)
