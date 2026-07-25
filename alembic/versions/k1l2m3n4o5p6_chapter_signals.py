"""chapter_signals: add page_signals column to uploads

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-07-22 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'k1l2m3n4o5p6'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('uploads') as batch_op:
        batch_op.add_column(sa.Column('page_signals', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('uploads') as batch_op:
        batch_op.drop_column('page_signals')
