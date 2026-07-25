"""compound_breakdown: add compound_breakdown and is_compound to cards

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-07-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'l2m3n4o5p6q7'
down_revision = 'k1l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('cards') as batch_op:
        batch_op.add_column(sa.Column('compound_breakdown', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('is_compound', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('cards') as batch_op:
        batch_op.drop_column('is_compound')
        batch_op.drop_column('compound_breakdown')
