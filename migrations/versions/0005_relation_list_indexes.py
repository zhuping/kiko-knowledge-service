"""add indexes used by relation list status and version queries."""

from alembic import op
from sqlalchemy import inspect

revision = "0005_relation_list_indexes"
down_revision = "0004_seed_catalog_nodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    index_names = {
        index["name"] for index in inspect(bind).get_indexes("release_relation")
    }
    if "ix_release_relation_relation_revision" not in index_names:
        op.create_index(
            "ix_release_relation_relation_revision",
            "release_relation",
            ["relation_id", "relation_revision_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    index_names = {
        index["name"] for index in inspect(bind).get_indexes("release_relation")
    }
    if "ix_release_relation_relation_revision" in index_names:
        op.drop_index(
            "ix_release_relation_relation_revision", table_name="release_relation"
        )
