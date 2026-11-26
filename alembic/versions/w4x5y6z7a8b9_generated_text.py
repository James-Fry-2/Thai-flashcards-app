"""generated_text: Claude-written dialogues and example sentences for reading

Revision ID: w4x5y6z7a8b9
Revises: v3w4x5y6z7a8
Create Date: 2026-11-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'w4x5y6z7a8b9'
down_revision = 'v3w4x5y6z7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_text",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("setting", sa.Text(), nullable=True),
        sa.Column("lines", sa.Text(), nullable=False),
        sa.Column("target_words", sa.Text(), nullable=False),
        sa.Column("check", sa.Text(), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_generated_text_user_id", "generated_text", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_generated_text_user_id", table_name="generated_text")
    op.drop_table("generated_text")
