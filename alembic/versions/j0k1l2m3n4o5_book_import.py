"""book import: kind, parent_upload_id, chapter_map, requires_confirmation, source_title, chapter_label, section_label

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-07-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('uploads') as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(20), nullable=False, server_default='single'))
        batch_op.add_column(sa.Column('parent_upload_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('chapter_map', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('requires_confirmation', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('source_title', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('chapter_label', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('section_label', sa.Text(), nullable=True))

    op.create_index('ix_uploads_parent_upload_id', 'uploads', ['parent_upload_id'])


def downgrade() -> None:
    op.drop_index('ix_uploads_parent_upload_id', table_name='uploads')

    with op.batch_alter_table('uploads') as batch_op:
        batch_op.drop_column('section_label')
        batch_op.drop_column('chapter_label')
        batch_op.drop_column('source_title')
        batch_op.drop_column('requires_confirmation')
        batch_op.drop_column('chapter_map')
        batch_op.drop_column('parent_upload_id')
        batch_op.drop_column('kind')
