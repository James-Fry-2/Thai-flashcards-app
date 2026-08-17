"""quiz_option_log: multiple-choice quiz confusion log table

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-08-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'q8r9s0t1u2v3'
down_revision = 'p7q8r9s0t1u2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quiz_option_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("quiz_session_id", sa.String(36), nullable=False),
        sa.Column(
            "target_card_id",
            sa.Integer(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "option_card_id",
            sa.Integer(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("option_text", sa.Text(), nullable=True),
        sa.Column("option_source", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_target", sa.Boolean(), nullable=False),
        sa.Column("was_chosen", sa.Boolean(), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False, server_default="th_to_en"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quiz_option_log_quiz_session_id", "quiz_option_log", ["quiz_session_id"])
    op.create_index("ix_quiz_option_log_target_card_id", "quiz_option_log", ["target_card_id"])
    op.create_index("ix_quiz_option_log_option_card_id", "quiz_option_log", ["option_card_id"])
    op.create_index(
        "ix_quiz_option_log_target_option", "quiz_option_log", ["target_card_id", "option_card_id"]
    )
    op.create_index("ix_quiz_option_log_created_at", "quiz_option_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_quiz_option_log_created_at", table_name="quiz_option_log")
    op.drop_index("ix_quiz_option_log_target_option", table_name="quiz_option_log")
    op.drop_index("ix_quiz_option_log_option_card_id", table_name="quiz_option_log")
    op.drop_index("ix_quiz_option_log_target_card_id", table_name="quiz_option_log")
    op.drop_index("ix_quiz_option_log_quiz_session_id", table_name="quiz_option_log")
    op.drop_table("quiz_option_log")
