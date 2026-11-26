"""generated_text.usage: token counts and cost of each model call

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
Create Date: 2026-11-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'x5y6z7a8b9c0'
down_revision = 'w4x5y6z7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generated_text") as batch:
        batch.add_column(sa.Column("usage", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("generated_text") as batch:
        batch.drop_column("usage")
