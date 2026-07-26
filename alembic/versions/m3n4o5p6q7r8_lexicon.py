"""lexicon: add shared Thai->English lexicon table (Volubilis)

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-07-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'm3n4o5p6q7r8'
down_revision = 'l2m3n4o5p6q7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'lexicon',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('thai', sa.Text(), nullable=False),
        sa.Column('romanization', sa.Text(), nullable=True),
        sa.Column('english', sa.Text(), nullable=False),
        sa.Column('pos', sa.String(30), nullable=True),
        sa.Column('source', sa.String(30), nullable=False, server_default='volubilis'),
    )
    op.create_index('ix_lexicon_thai', 'lexicon', ['thai'])


def downgrade() -> None:
    op.drop_index('ix_lexicon_thai', table_name='lexicon')
    op.drop_table('lexicon')
