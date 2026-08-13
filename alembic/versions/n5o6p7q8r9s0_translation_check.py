"""translation_check: add translation_status and translation_candidates to cards

Revision ID: n5o6p7q8r9s0
Revises: m3n4o5p6q7r8
Create Date: 2026-07-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'n5o6p7q8r9s0'
down_revision = 'm3n4o5p6q7r8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('cards') as batch_op:
        batch_op.add_column(
            sa.Column('translation_status', sa.Text(), nullable=False, server_default='unverified')
        )
        batch_op.add_column(sa.Column('translation_candidates', sa.Text(), nullable=True))
    op.create_index('ix_cards_translation_status', 'cards', ['translation_status'])


def downgrade() -> None:
    op.drop_index('ix_cards_translation_status', table_name='cards')
    with op.batch_alter_table('cards') as batch_op:
        batch_op.drop_column('translation_candidates')
        batch_op.drop_column('translation_status')
