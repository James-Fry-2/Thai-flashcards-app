"""tts_usage: characters sent to the text-to-speech provider (cache misses)

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
Create Date: 2026-11-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'y6z7a8b9c0d1'
down_revision = 'x5y6z7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tts_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("voice", sa.String(80), nullable=False),
        sa.Column("rate", sa.String(20), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tts_usage_cache_key", "tts_usage", ["cache_key"])
    op.create_index("ix_tts_usage_created_at", "tts_usage", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_tts_usage_created_at", table_name="tts_usage")
    op.drop_index("ix_tts_usage_cache_key", table_name="tts_usage")
    op.drop_table("tts_usage")
