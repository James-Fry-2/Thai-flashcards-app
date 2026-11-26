"""user_preferences: text-to-speech autoplay and default speed

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-11-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'z7a8b9c0d1e2'
down_revision = 'y6z7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_preferences") as batch:
        batch.add_column(sa.Column("tts_autoplay_on_reveal", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("tts_default_speed", sa.String(10), nullable=False, server_default="normal"))


def downgrade() -> None:
    with op.batch_alter_table("user_preferences") as batch:
        batch.drop_column("tts_default_speed")
        batch.drop_column("tts_autoplay_on_reveal")
