"""add review_sessions table

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("strategy", sa.String(20), nullable=True),
        sa.Column("direction", sa.String(20), nullable=False, server_default="th_to_en"),
        sa.Column("cards_reviewed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("xp_earned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_review_sessions_status", "review_sessions", ["status"])
    op.create_index("ix_review_sessions_created_at", "review_sessions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_review_sessions_created_at", table_name="review_sessions")
    op.drop_index("ix_review_sessions_status", table_name="review_sessions")
    op.drop_table("review_sessions")
