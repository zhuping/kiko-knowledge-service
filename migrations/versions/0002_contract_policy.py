"""add policy rules and knowledge policy mappings"""

from alembic import op

from app.models import KnowledgePolicyMapping, PolicyRule

revision = "0002_contract_policy"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    PolicyRule.__table__.create(bind=bind, checkfirst=True)
    KnowledgePolicyMapping.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    KnowledgePolicyMapping.__table__.drop(bind=bind, checkfirst=True)
    PolicyRule.__table__.drop(bind=bind, checkfirst=True)
