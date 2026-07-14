"""unique constraint on (deck_id, thai) — deduplicate cards per deck

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'g7h8i9j0k1l2'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Find duplicate (deck_id, thai) groups — keep the oldest card (min id).
    #    Delete all card_schedules, card_tags, card_topic_memberships, card_embeddings
    #    and links that reference the duplicate cards before deleting the cards.
    dupes = conn.execute(sa.text("""
        SELECT id FROM cards
        WHERE (deck_id, thai) IN (
            SELECT deck_id, thai FROM cards
            GROUP BY deck_id, thai HAVING COUNT(*) > 1
        )
        AND id NOT IN (
            SELECT MIN(id) FROM cards
            GROUP BY deck_id, thai
        )
    """)).fetchall()

    dupe_ids = [row[0] for row in dupes]

    if dupe_ids:
        placeholders = ','.join(str(i) for i in dupe_ids)

        # Delete dependent rows first (FK order)
        for table in (
            'card_schedules',
            'card_tags',
            'card_topic_memberships',
            'card_embeddings',
            'card_links',
        ):
            try:
                conn.execute(sa.text(
                    f"DELETE FROM {table} WHERE card_id IN ({placeholders})"
                ))
            except Exception:
                pass  # table may not exist in all environments

        # Also handle card_links where the *linked* card is the dupe
        try:
            conn.execute(sa.text(
                f"DELETE FROM card_links WHERE linked_card_id IN ({placeholders})"
            ))
        except Exception:
            pass

        conn.execute(sa.text(
            f"DELETE FROM cards WHERE id IN ({placeholders})"
        ))

    # 2. Add the unique constraint.
    with op.batch_alter_table('cards') as batch_op:
        batch_op.create_unique_constraint('uq_cards_deck_thai', ['deck_id', 'thai'])


def downgrade() -> None:
    with op.batch_alter_table('cards') as batch_op:
        batch_op.drop_constraint('uq_cards_deck_thai', type_='unique')
