"""replace the pre-V1 schema with the revision and release snapshot model.

The previous schema has no safe lossless migration because its entities and
release semantics are different.  This reset is intentionally limited to the
application tables and is only activated when a legacy marker table exists.
Back up a non-development database before upgrading it.
"""

from alembic import op
from sqlalchemy import inspect, select

from app.models import Base, TextbookEdition
from app.models.base import utc_now

revision = "0003_v1_revision_model"
down_revision = "0002_contract_policy"
branch_labels = None
depends_on = None

LEGACY_MARKERS = {"content_space", "knowledge_term"}
APP_TABLES = (
    "knowledge_policy_mapping",
    "policy_rule",
    "release_relation",
    "release_knowledge",
    "release_mapping",
    "release_catalog_node",
    "release_snapshot",
    "release_batch_item",
    "release_current",
    "release_version",
    "release_batch",
    "relation_revision",
    "knowledge_relation",
    "knowledge_base_mapping",
    "textbook_mapping",
    "knowledge_revision",
    "knowledge_object",
    "catalog_node",
    "knowledge_base",
    "knowledge_term",
    "textbook_edition",
    "content_space",
    "change_log",
    "audit_log",
    "job",
    "api_nonce",
    "api_rate_bucket",
    "api_client",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if existing.intersection(LEGACY_MARKERS):
        mysql = bind.dialect.name == "mysql"
        if mysql:
            bind.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        try:
            for table_name in APP_TABLES:
                if table_name in existing:
                    op.drop_table(table_name)
        finally:
            if mysql:
                bind.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
    Base.metadata.create_all(bind=bind)
    if not bind.execute(select(TextbookEdition.id).limit(1)).first():
        now = utc_now()
        bind.execute(
            TextbookEdition.__table__.insert(),
            [
                {
                    "edition_code": f"pep_math_2024_g{grade}_t{term}",
                    "edition_name": (
                        f"人教版2024数学{['', '一', '二'][grade]}年级"
                        f"{'上' if term == 1 else '下'}册"
                    ),
                    "subject": "math",
                    "grade_term": f"g{grade}_t{term}",
                    "version_year": 2024,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                }
                for grade in (1, 2)
                for term in (1, 2)
            ],
        )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
