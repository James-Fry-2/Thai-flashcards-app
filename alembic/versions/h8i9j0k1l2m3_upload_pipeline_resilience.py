"""resilient upload pipeline: upload_pages table + stage/progress columns

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-07-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'h8i9j0k1l2m3'
down_revision = 'g7h8i9j0k1l2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- new columns on uploads ---
    with op.batch_alter_table('uploads') as batch_op:
        batch_op.add_column(sa.Column('stage', sa.String(20), nullable=False, server_default='queued'))
        batch_op.add_column(sa.Column('total_pages', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pages_processed', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'))

    # --- upload_pages table ---
    op.create_table(
        'upload_pages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column('upload_id', sa.Integer(), sa.ForeignKey('uploads.id', ondelete='CASCADE'), nullable=False),
        sa.Column('page_index', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('engine_used', sa.String(30), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.UniqueConstraint('upload_id', 'page_index', name='uq_upload_pages_upload_page'),
    )
    op.create_index('ix_upload_pages_upload_id', 'upload_pages', ['upload_id'])


def downgrade() -> None:
    op.drop_index('ix_upload_pages_upload_id', table_name='upload_pages')
    op.drop_table('upload_pages')

    with op.batch_alter_table('uploads') as batch_op:
        batch_op.drop_column('attempts')
        batch_op.drop_column('pages_processed')
        batch_op.drop_column('total_pages')
        batch_op.drop_column('stage')
