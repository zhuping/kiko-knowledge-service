"""make fixed-length knowledge IDs start with one."""

import re

from alembic import op
from sqlalchemy import text

revision = "0007_ids_start_one"
down_revision = "0006_numeric_canonical_ids"
branch_labels = None
depends_on = None

NUMERIC_ID = re.compile(r"^\d{8}$")


def _rewrite_ids(prefix: str) -> None:
    connection = op.get_bind()
    target_id = re.compile(rf"^{prefix}\d{{7}}$")
    rows = (
        connection.execute(
            text("SELECT id, canonical_id FROM knowledge_object ORDER BY canonical_id")
        )
        .mappings()
        .all()
    )
    if not rows or all(target_id.fullmatch(row["canonical_id"] or "") for row in rows):
        return
    if not all(NUMERIC_ID.fullmatch(row["canonical_id"] or "") for row in rows):
        raise RuntimeError("knowledge_object 中存在非 8 位数字 ID，无法迁移")

    mapping = {
        row["canonical_id"]: f"{prefix}{index:07d}" for index, row in enumerate(rows, 1)
    }
    row_id_by_old = {row["canonical_id"]: row["id"] for row in rows}
    dependent_columns = (
        ("release_mapping", "canonical_id"),
        ("release_knowledge", "canonical_id"),
        ("release_relation", "from_canonical_id"),
        ("release_relation", "to_canonical_id"),
        ("audit_log", "entity_key"),
    )

    temporary_ids = {
        old_id: f"T{index:07d}" for index, old_id in enumerate(row_id_by_old, 1)
    }
    for old_id, row_id in row_id_by_old.items():
        temporary_id = temporary_ids[old_id]
        for table, column in dependent_columns:
            condition = (
                " AND entity_type = 'knowledge_object'" if table == "audit_log" else ""
            )
            connection.execute(
                text(
                    f"UPDATE {table} SET {column} = :temporary_id "
                    f"WHERE {column} = :old_id{condition}"
                ),
                {"old_id": old_id, "temporary_id": temporary_id},
            )
        connection.execute(
            text(
                "UPDATE knowledge_object SET canonical_id = :temporary_id "
                "WHERE id = :knowledge_id"
            ),
            {"knowledge_id": row_id, "temporary_id": temporary_id},
        )

    for old_id, row_id in row_id_by_old.items():
        temporary_id = temporary_ids[old_id]
        new_id = mapping[old_id]
        for table, column in dependent_columns:
            condition = (
                " AND entity_type = 'knowledge_object'" if table == "audit_log" else ""
            )
            connection.execute(
                text(
                    f"UPDATE {table} SET {column} = :new_id "
                    f"WHERE {column} = :temporary_id{condition}"
                ),
                {"temporary_id": temporary_id, "new_id": new_id},
            )
        connection.execute(
            text(
                "UPDATE knowledge_object SET canonical_id = :new_id "
                "WHERE id = :knowledge_id"
            ),
            {"knowledge_id": row_id, "new_id": new_id},
        )


def upgrade() -> None:
    _rewrite_ids("1")


def downgrade() -> None:
    _rewrite_ids("0")
