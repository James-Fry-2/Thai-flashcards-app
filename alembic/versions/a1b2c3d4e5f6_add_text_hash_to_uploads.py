"""add text_hash to uploads

Revision ID: a1b2c3d4e5f6
Revises: 34047d11e84a
Create Date: 2026-04-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '34047d11e84a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('uploads', sa.Column('text_hash', sa.String(64), nullable=True))
    op.create_index('ix_uploads_text_hash', 'uploads', ['text_hash'])


def downgrade() -> None:
    op.drop_index('ix_uploads_text_hash', table_name='uploads')
    op.drop_column('uploads', 'text_hash')
