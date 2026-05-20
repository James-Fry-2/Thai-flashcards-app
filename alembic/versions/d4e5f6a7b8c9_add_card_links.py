"""add card links

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "from_card_id",
            sa.Integer(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_card_id",
            sa.Integer(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("link_type", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("from_card_id", "to_card_id", "link_type", name="uq_card_link"),
    )
    op.create_index("ix_card_links_from", "card_links", ["from_card_id"])
    op.create_index("ix_card_links_to", "card_links", ["to_card_id"])


def downgrade() -> None:
    op.drop_index("ix_card_links_to", table_name="card_links")
    op.drop_index("ix_card_links_from", table_name="card_links")
    op.drop_table("card_links")
