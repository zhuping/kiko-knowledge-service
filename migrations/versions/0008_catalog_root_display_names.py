"""use textbook display names for synthetic book catalog roots."""

from alembic import op
from sqlalchemy import select, update

from app.models import (
    CatalogNode,
    KnowledgeBase,
    ReleaseCatalogNode,
    ReleaseVersion,
    TextbookEdition,
)

revision = "0008_catalog_root_names"
down_revision = "0007_ids_start_one"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    catalog_roots = bind.execute(
        select(CatalogNode.id, TextbookEdition.edition_name)
        .join(TextbookEdition, TextbookEdition.id == CatalogNode.edition_id)
        .where(CatalogNode.node_type == "book", CatalogNode.parent_id.is_(None))
    ).all()
    for node_id, edition_name in catalog_roots:
        bind.execute(
            update(CatalogNode)
            .where(CatalogNode.id == node_id)
            .values(title=edition_name)
        )

    release_roots = bind.execute(
        select(ReleaseCatalogNode.id, TextbookEdition.edition_name)
        .join(ReleaseVersion, ReleaseVersion.id == ReleaseCatalogNode.release_id)
        .join(KnowledgeBase, KnowledgeBase.id == ReleaseVersion.knowledge_base_id)
        .join(TextbookEdition, TextbookEdition.id == KnowledgeBase.textbook_edition_id)
        .where(
            ReleaseCatalogNode.node_type == "book",
            ReleaseCatalogNode.level == 0,
        )
    ).all()
    for node_id, edition_name in release_roots:
        bind.execute(
            update(ReleaseCatalogNode)
            .where(ReleaseCatalogNode.id == node_id)
            .values(title=edition_name)
        )


def downgrade() -> None:
    bind = op.get_bind()

    catalog_roots = bind.execute(
        select(CatalogNode.id, TextbookEdition.edition_code)
        .join(TextbookEdition, TextbookEdition.id == CatalogNode.edition_id)
        .where(CatalogNode.node_type == "book", CatalogNode.parent_id.is_(None))
    ).all()
    for node_id, edition_code in catalog_roots:
        bind.execute(
            update(CatalogNode)
            .where(CatalogNode.id == node_id)
            .values(title=edition_code)
        )

    release_roots = bind.execute(
        select(ReleaseCatalogNode.id, TextbookEdition.edition_code)
        .join(ReleaseVersion, ReleaseVersion.id == ReleaseCatalogNode.release_id)
        .join(KnowledgeBase, KnowledgeBase.id == ReleaseVersion.knowledge_base_id)
        .join(TextbookEdition, TextbookEdition.id == KnowledgeBase.textbook_edition_id)
        .where(
            ReleaseCatalogNode.node_type == "book",
            ReleaseCatalogNode.level == 0,
        )
    ).all()
    for node_id, edition_code in release_roots:
        bind.execute(
            update(ReleaseCatalogNode)
            .where(ReleaseCatalogNode.id == node_id)
            .values(title=edition_code)
        )
