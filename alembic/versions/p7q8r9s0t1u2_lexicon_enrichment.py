"""lexicon_enrichment: add scientific_name, level, usage columns to lexicon

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
Create Date: 2026-08-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'p7q8r9s0t1u2'
down_revision = 'o6p7q8r9s0t1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('lexicon') as batch_op:
        batch_op.add_column(sa.Column('scientific_name', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('level', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('usage', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('lexicon') as batch_op:
        batch_op.drop_column('usage')
        batch_op.drop_column('level')
        batch_op.drop_column('scientific_name')
