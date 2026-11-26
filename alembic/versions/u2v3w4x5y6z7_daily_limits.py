"""daily limits: user_preferences.daily_new_limit / daily_review_limit

Caps how many new cards are introduced and how many graduated reviews are
shown per day. Learning/relearning cards are never capped. Counts come from
review_log, so no counter table is needed.

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-11-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'u2v3w4x5y6z7'
down_revision = 't1u2v3w4x5y6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_preferences") as batch:
        batch.add_column(sa.Column("daily_new_limit", sa.Integer(), nullable=False, server_default="10"))
        batch.add_column(sa.Column("daily_review_limit", sa.Integer(), nullable=False, server_default="100"))


def downgrade() -> None:
    with op.batch_alter_table("user_preferences") as batch:
        batch.drop_column("daily_review_limit")
        batch.drop_column("daily_new_limit")
