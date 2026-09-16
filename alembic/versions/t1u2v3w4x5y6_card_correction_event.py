"""card_correction_event: append-only correction history log

Adds `card_correction_event`, the append-only history table behind the card
triage screen. `card_override` (from s0t1u2v3w4x5) stays the *current*
per-user state; this table is the *history* underneath it — every write
that goes through src/db/services/correction_service.py::apply_decision()
appends one row here in the same transaction. Rows are never updated or
deleted; undo() writes a compensating event instead.

`card_id` uses ON DELETE SET NULL (unlike card_flag/card_override's
CASCADE) so a correction's aggregate value survives the deletion of any one
card that contributed it — `thai_key`/`from_value` are denormalised onto
the row for exactly this reason.

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-09-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 't1u2v3w4x5y6'
down_revision = 's0t1u2v3w4x5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_correction_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("thai_key", sa.String(), nullable=False),
        sa.Column("target", sa.String(20), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("from_value", sa.Text(), nullable=True),
        sa.Column("to_value", sa.Text(), nullable=True),
        sa.Column("from_norm", sa.String(), nullable=True),
        sa.Column("prev_override", sa.Text(), nullable=True),
        sa.Column("ai_verdict", sa.String(20), nullable=True),
        sa.Column("ai_reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column(
            "applied_from_event_id",
            sa.Integer(),
            sa.ForeignKey("card_correction_event.id"),
            nullable=True,
        ),
        sa.Column(
            "reverts_event_id",
            sa.Integer(),
            sa.ForeignKey("card_correction_event.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_card_correction_event_user_created", "card_correction_event", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_card_correction_event_thai_target", "card_correction_event", ["thai_key", "target"]
    )
    op.create_index(
        "ix_card_correction_event_thai_target_norm",
        "card_correction_event",
        ["thai_key", "target", "from_norm"],
    )
    op.create_index(
        "ix_card_correction_event_batch_id", "card_correction_event", ["batch_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_card_correction_event_batch_id", table_name="card_correction_event")
    op.drop_index("ix_card_correction_event_thai_target_norm", table_name="card_correction_event")
    op.drop_index("ix_card_correction_event_thai_target", table_name="card_correction_event")
    op.drop_index("ix_card_correction_event_user_created", table_name="card_correction_event")
    op.drop_table("card_correction_event")
