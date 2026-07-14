"""add embeddings

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1
Create Date: 2026-06-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2b3c4d5e6f7'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_embeddings",
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        # float32 numpy array as raw bytes; decode with np.frombuffer(embedding, dtype=np.float32)
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "topic_embeddings",
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tag_embeddings",
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tag_embeddings")
    op.drop_table("topic_embeddings")
    op.drop_table("card_embeddings")
