"""add tag hierarchy

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tags") as batch:
        batch.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch.create_index("ix_tags_parent_id", ["parent_id"])
        batch.create_foreign_key(
            "fk_tags_parent", "tags", ["parent_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("tags") as batch:
        batch.drop_constraint("fk_tags_parent", type_="foreignkey")
        batch.drop_index("ix_tags_parent_id")
        batch.drop_column("description")
        batch.drop_column("parent_id")
