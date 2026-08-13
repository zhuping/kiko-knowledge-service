"""convert knowledge IDs to fixed-length numeric strings."""

import re

from alembic import op
from sqlalchemy import String, text

revision = "0006_numeric_canonical_ids"
down_revision = "0005_relation_list_indexes"
branch_labels = None
depends_on = None

NUMERIC_ID = re.compile(r"^\d{8}$")


def _convert_ids() -> None:
    connection = op.get_bind()
    rows = (
        connection.execute(
            text("SELECT id, canonical_id FROM knowledge_object ORDER BY canonical_id")
        )
        .mappings()
        .all()
    )
    if not rows or all(NUMERIC_ID.fullmatch(row["canonical_id"] or "") for row in rows):
        return
    mapping = {row["canonical_id"]: f"{index:08d}" for index, row in enumerate(rows, 1)}
    row_id_by_old = {row["canonical_id"]: row["id"] for row in rows}
    dependent_columns = (
        ("release_mapping", "canonical_id"),
        ("release_knowledge", "canonical_id"),
        ("release_relation", "from_canonical_id"),
        ("release_relation", "to_canonical_id"),
        ("audit_log", "entity_key"),
    )
    for old_id, new_id in mapping.items():
        for table, column in dependent_columns:
            connection.execute(
                text(
                    f"UPDATE {table} SET {column} = :new_id "
                    f"WHERE {column} = :old_id"
                    + (
                        " AND entity_type = 'knowledge_object'"
                        if table == "audit_log"
                        else ""
                    )
                ),
                {"old_id": old_id, "new_id": new_id},
            )
        connection.execute(
            text(
                "UPDATE knowledge_object SET canonical_id = :new_id "
                "WHERE id = :knowledge_id"
            ),
            {"knowledge_id": row_id_by_old[old_id], "new_id": new_id},
        )


def upgrade() -> None:
    _convert_ids()
    for table, column in (
        ("knowledge_object", "canonical_id"),
        ("release_mapping", "canonical_id"),
        ("release_knowledge", "canonical_id"),
        ("release_relation", "from_canonical_id"),
        ("release_relation", "to_canonical_id"),
    ):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table) as batch:
                batch.alter_column(
                    column,
                    existing_type=String(128),
                    type_=String(8),
                    existing_nullable=False,
                )
        else:
            op.alter_column(
                table,
                column,
                existing_type=String(128),
                type_=String(8),
                existing_nullable=False,
            )


def downgrade() -> None:
    for table, column in (
        ("knowledge_object", "canonical_id"),
        ("release_mapping", "canonical_id"),
        ("release_knowledge", "canonical_id"),
        ("release_relation", "from_canonical_id"),
        ("release_relation", "to_canonical_id"),
    ):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table) as batch:
                batch.alter_column(
                    column,
                    existing_type=String(8),
                    type_=String(128),
                    existing_nullable=False,
                )
        else:
            op.alter_column(
                table,
                column,
                existing_type=String(8),
                type_=String(128),
                existing_nullable=False,
            )
