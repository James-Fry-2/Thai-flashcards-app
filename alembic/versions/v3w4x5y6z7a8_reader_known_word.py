"""reader_known_word: words marked "I know this" in Read & mine mode

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-11-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'v3w4x5y6z7a8'
down_revision = 'u2v3w4x5y6z7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reader_known_word",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("thai", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "thai", name="uq_reader_known_word_user_thai"),
    )
    op.create_index("ix_reader_known_word_user_id", "reader_known_word", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_reader_known_word_user_id", table_name="reader_known_word")
    op.drop_table("reader_known_word")
