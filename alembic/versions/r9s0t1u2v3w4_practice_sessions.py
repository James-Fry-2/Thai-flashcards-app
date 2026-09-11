"""practice_sessions: generalise quiz mode into mixed practice sessions

Drops quiz_option_log (smoke-test data only, confirmed safe) and replaces it
with practice_sessions / practice_attempts / practice_option_log, which
support interleaving multiple exercise types (mc_th_en, recall_th_en) over a
scoped set of cards.

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-08-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'r9s0t1u2v3w4'
down_revision = 'q8r9s0t1u2v3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("quiz_option_log")

    op.create_table(
        "practice_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "practice_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("practice_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exercise_type", sa.String(30), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("outcome", sa.Boolean(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_practice_attempts_session_id", "practice_attempts", ["session_id"])
    op.create_index("ix_practice_attempts_card_id", "practice_attempts", ["card_id"])

    op.create_table(
        "practice_option_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "attempt_id",
            sa.Integer(),
            sa.ForeignKey("practice_attempts.id", ondelete="CASCADE"),
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
        sa.CheckConstraint(
            "option_card_id IS NOT NULL OR option_text IS NOT NULL",
            name="ck_practice_option_log_card_or_text",
        ),
    )
    op.create_index("ix_practice_option_log_attempt_id", "practice_option_log", ["attempt_id"])
    op.create_index("ix_practice_option_log_option_card_id", "practice_option_log", ["option_card_id"])


def downgrade() -> None:
    op.drop_index("ix_practice_option_log_option_card_id", table_name="practice_option_log")
    op.drop_index("ix_practice_option_log_attempt_id", table_name="practice_option_log")
    op.drop_table("practice_option_log")

    op.drop_index("ix_practice_attempts_card_id", table_name="practice_attempts")
    op.drop_index("ix_practice_attempts_session_id", table_name="practice_attempts")
    op.drop_table("practice_attempts")

    op.drop_table("practice_sessions")

    # Recreate quiz_option_log exactly as migration q8r9s0t1u2v3 defined it.
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
