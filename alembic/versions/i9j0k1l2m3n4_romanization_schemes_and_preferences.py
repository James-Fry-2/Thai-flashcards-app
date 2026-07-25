"""romanization scheme columns + user_preferences singleton

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-07-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'i9j0k1l2m3n4'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cards") as batch_op:
        batch_op.add_column(sa.Column("romanization_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("romanization_paiboon", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("romanization_rtgs", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("romanization_ipa", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("romanization_manual", sa.Text(), nullable=True))

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "romanization_display",
            sa.String(20),
            nullable=False,
            server_default="source",
        ),
        sa.Column(
            "romanization_fallback",
            sa.String(20),
            nullable=False,
            server_default="paiboon",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ','now'))"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ','now'))"),
        ),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
    with op.batch_alter_table("cards") as batch_op:
        batch_op.drop_column("romanization_manual")
        batch_op.drop_column("romanization_ipa")
        batch_op.drop_column("romanization_rtgs")
        batch_op.drop_column("romanization_paiboon")
        batch_op.drop_column("romanization_source")
