"""card_flags_overrides: user-facing content flags + per-user override overlay

Adds `card_flag` (a report queue item — no correction payload, just a marker
that something on a card looks wrong) and `card_override` (a private
per-user display-layer correction, one row per user/card/target, never
written back onto `cards`).

Also changes the behaviour of POST /cards/{card_id}/resolve-translation:
`action='correct'` now upserts a `card_override` row instead of writing
`cards.english` directly. No data migration is included for existing
`translation_status='confirmed'` cards — there is no record of whether a
historically confirmed card was a 'keep' or a 'correct', so we cannot
retroactively split "material value" from "user correction" for rows written
before this change. Those cards keep whatever value already lives in
`cards.english`; only corrections made after this migration land in
`card_override`. This is a deliberate, documented discontinuity rather than
an invented heuristic.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-08-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 's0t1u2v3w4x5'
down_revision = 'r9s0t1u2v3w4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_flag",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("flagged_value", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_card_flag_user_id", "card_flag", ["user_id"])
    op.create_index("ix_card_flag_card_id", "card_flag", ["card_id"])
    op.create_index("ix_card_flag_user_status", "card_flag", ["user_id", "status"])
    op.create_index("ix_card_flag_card_target", "card_flag", ["card_id", "target"])

    op.create_table(
        "card_override",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target", sa.String(20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "card_id", "target", name="uq_card_override_user_card_target"
        ),
    )


def downgrade() -> None:
    op.drop_table("card_override")

    op.drop_index("ix_card_flag_card_target", table_name="card_flag")
    op.drop_index("ix_card_flag_user_status", table_name="card_flag")
    op.drop_index("ix_card_flag_card_id", table_name="card_flag")
    op.drop_index("ix_card_flag_user_id", table_name="card_flag")
    op.drop_table("card_flag")
