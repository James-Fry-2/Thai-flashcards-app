"""add thai analysis

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cards") as batch_op:
        batch_op.add_column(sa.Column("syllable_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tone_pattern", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("consonant_classes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("has_cluster", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("has_rare_consonant", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("has_silent_mark", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("script_analysis", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cards") as batch_op:
        batch_op.drop_column("script_analysis")
        batch_op.drop_column("has_silent_mark")
        batch_op.drop_column("has_rare_consonant")
        batch_op.drop_column("has_cluster")
        batch_op.drop_column("consonant_classes")
        batch_op.drop_column("tone_pattern")
        batch_op.drop_column("syllable_count")
