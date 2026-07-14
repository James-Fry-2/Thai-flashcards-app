"""
Embedding service — compute, store, and query vector embeddings for cards, topics, and tags.

Storage: float32 numpy array as raw bytes in LargeBinary columns (no vector database).
Brute-force cosine similarity via numpy is fast enough for thousands of items (<10ms).
"""
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.db.models.card import Card
from src.db.models.tag import Tag
from src.db.models.topic import Topic
from src.db.models.embeddings import CardEmbedding, TagEmbedding, TopicEmbedding
from src.utils.embeddings import (
    cosine_similarity_matrix,
    embed_batch,
    embed_text,
    text_hash as compute_hash,
)


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _card_text(card: Card) -> str:
    parts = [f"{card.thai} | {card.english}"]
    if card.example_thai:
        parts.append(card.example_thai)
    return " | ".join(parts)


def _topic_text(topic: Topic) -> str:
    if topic.description:
        return f"{topic.name}: {topic.description}"
    return topic.name


def _tag_text(tag: Tag) -> str:
    if tag.description:
        return f"{tag.name}: {tag.description}"
    return tag.name


# ---------------------------------------------------------------------------
# Blob encode / decode
# ---------------------------------------------------------------------------

def _to_blob(vec: list[float]) -> bytes:
    return np.array(vec, dtype=np.float32).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------

def _is_stale(record, text: str) -> bool:
    """True if the stored embedding needs to be recomputed."""
    settings = get_settings()
    return record.model_name != settings.embedding_model or record.text_hash != compute_hash(text)


# ---------------------------------------------------------------------------
# Per-entity embed helpers
# ---------------------------------------------------------------------------

async def embed_card(db: AsyncSession, card_id: int, force: bool = False) -> bool:
    """Compute and store embedding for one card. Skip if up-to-date unless force=True. Returns True if embedded."""
    settings = get_settings()
    card = await db.get(Card, card_id)
    if not card:
        return False

    text = _card_text(card)
    existing = await db.get(CardEmbedding, card_id)

    if existing and not force and not _is_stale(existing, text):
        return False

    vec = embed_text(text)
    if vec is None:
        return False

    now = datetime.now(timezone.utc)
    if existing:
        existing.model_name = settings.embedding_model
        existing.embedding = _to_blob(vec)
        existing.text_hash = compute_hash(text)
        existing.updated_at = now
    else:
        db.add(CardEmbedding(
            card_id=card_id,
            model_name=settings.embedding_model,
            embedding=_to_blob(vec),
            text_hash=compute_hash(text),
            updated_at=now,
        ))

    await db.flush()
    return True


async def embed_topic(db: AsyncSession, topic_id: int, force: bool = False) -> bool:
    """Compute and store embedding for one topic. Returns True if embedded."""
    settings = get_settings()
    topic = await db.get(Topic, topic_id)
    if not topic:
        return False

    text = _topic_text(topic)
    existing = await db.get(TopicEmbedding, topic_id)

    if existing and not force and not _is_stale(existing, text):
        return False

    vec = embed_text(text)
    if vec is None:
        return False

    now = datetime.now(timezone.utc)
    if existing:
        existing.model_name = settings.embedding_model
        existing.embedding = _to_blob(vec)
        existing.text_hash = compute_hash(text)
        existing.updated_at = now
    else:
        db.add(TopicEmbedding(
            topic_id=topic_id,
            model_name=settings.embedding_model,
            embedding=_to_blob(vec),
            text_hash=compute_hash(text),
            updated_at=now,
        ))

    await db.flush()
    return True


async def embed_tag(db: AsyncSession, tag_id: int, force: bool = False) -> bool:
    """Compute and store embedding for one tag. Returns True if embedded."""
    settings = get_settings()
    tag = await db.get(Tag, tag_id)
    if not tag:
        return False

    text = _tag_text(tag)
    existing = await db.get(TagEmbedding, tag_id)

    if existing and not force and not _is_stale(existing, text):
        return False

    vec = embed_text(text)
    if vec is None:
        return False

    now = datetime.now(timezone.utc)
    if existing:
        existing.model_name = settings.embedding_model
        existing.embedding = _to_blob(vec)
        existing.text_hash = compute_hash(text)
        existing.updated_at = now
    else:
        db.add(TagEmbedding(
            tag_id=tag_id,
            model_name=settings.embedding_model,
            embedding=_to_blob(vec),
            text_hash=compute_hash(text),
            updated_at=now,
        ))

    await db.flush()
    return True


# ---------------------------------------------------------------------------
# Batch embed for bulk card creation
# ---------------------------------------------------------------------------

async def embed_cards_batch(db: AsyncSession, card_ids: list[int]) -> dict:
    """Embed multiple cards in one model call. Returns {"embedded": int, "skipped": int, "failed": list[int]}."""
    if not card_ids:
        return {"embedded": 0, "skipped": 0, "failed": []}

    settings = get_settings()

    # Load all cards
    result = await db.execute(select(Card).where(Card.id.in_(card_ids)))
    cards = {c.id: c for c in result.scalars().all()}

    # Load existing embeddings
    emb_result = await db.execute(
        select(CardEmbedding).where(CardEmbedding.card_id.in_(card_ids))
    )
    existing = {e.card_id: e for e in emb_result.scalars().all()}

    # Determine which cards need embedding
    to_embed: list[tuple[int, str]] = []
    skipped = 0
    for cid in card_ids:
        card = cards.get(cid)
        if not card:
            skipped += 1
            continue
        text = _card_text(card)
        rec = existing.get(cid)
        if rec and not _is_stale(rec, text):
            skipped += 1
            continue
        to_embed.append((cid, text))

    if not to_embed:
        return {"embedded": 0, "skipped": skipped, "failed": []}

    # One model call for all texts
    texts = [t for _, t in to_embed]
    vecs = embed_batch(texts)

    now = datetime.now(timezone.utc)
    embedded = 0
    failed: list[int] = []

    for (cid, text), vec in zip(to_embed, vecs):
        if vec is None:
            failed.append(cid)
            continue
        rec = existing.get(cid)
        if rec:
            rec.model_name = settings.embedding_model
            rec.embedding = _to_blob(vec)
            rec.text_hash = compute_hash(text)
            rec.updated_at = now
        else:
            db.add(CardEmbedding(
                card_id=cid,
                model_name=settings.embedding_model,
                embedding=_to_blob(vec),
                text_hash=compute_hash(text),
                updated_at=now,
            ))
        embedded += 1

    await db.flush()
    return {"embedded": embedded, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# Find similar items
# ---------------------------------------------------------------------------

async def find_similar_cards(
    db: AsyncSession,
    card_id: int,
    limit: int = 20,
    min_similarity: float = 0.5,
) -> list[dict]:
    """Return cards most similar to the given card by embedding, excluding itself. Sorted by similarity desc."""
    target_emb = await db.get(CardEmbedding, card_id)
    if target_emb is None:
        return []

    query_vec = _from_blob(target_emb.embedding).tolist()

    # Load all other embeddings
    result = await db.execute(
        select(CardEmbedding).where(CardEmbedding.card_id != card_id)
    )
    all_embs = result.scalars().all()
    if not all_embs:
        return []

    ids = [e.card_id for e in all_embs]
    corpus = [_from_blob(e.embedding).tolist() for e in all_embs]

    sims = cosine_similarity_matrix(query_vec, corpus)

    # Sort by similarity descending, filter by threshold
    scored = sorted(zip(sims, ids), key=lambda x: x[0], reverse=True)
    top = [(sim, cid) for sim, cid in scored if sim >= min_similarity][:limit]

    if not top:
        return []

    # Enrich with card metadata
    top_ids = [cid for _, cid in top]
    cards_result = await db.execute(select(Card).where(Card.id.in_(top_ids)))
    cards_by_id = {c.id: c for c in cards_result.scalars().all()}

    return [
        {
            "card_id": cid,
            "thai": cards_by_id[cid].thai if cid in cards_by_id else "",
            "english": cards_by_id[cid].english if cid in cards_by_id else "",
            "card_type": cards_by_id[cid].card_type if cid in cards_by_id else "",
            "deck_id": cards_by_id[cid].deck_id if cid in cards_by_id else None,
            "similarity": round(sim, 4),
        }
        for sim, cid in top
        if cid in cards_by_id
    ]


async def find_similar_topics(
    db: AsyncSession,
    topic_id: int,
    limit: int = 10,
    min_similarity: float = 0.7,
) -> list[dict]:
    """Return topics most similar to the given topic by embedding. Sorted by similarity desc."""
    target_emb = await db.get(TopicEmbedding, topic_id)
    if target_emb is None:
        return []

    query_vec = _from_blob(target_emb.embedding).tolist()

    result = await db.execute(
        select(TopicEmbedding).where(TopicEmbedding.topic_id != topic_id)
    )
    all_embs = result.scalars().all()
    if not all_embs:
        return []

    ids = [e.topic_id for e in all_embs]
    corpus = [_from_blob(e.embedding).tolist() for e in all_embs]
    sims = cosine_similarity_matrix(query_vec, corpus)

    scored = sorted(zip(sims, ids), key=lambda x: x[0], reverse=True)
    top = [(sim, tid) for sim, tid in scored if sim >= min_similarity][:limit]

    if not top:
        return []

    top_ids = [tid for _, tid in top]
    topics_result = await db.execute(select(Topic).where(Topic.id.in_(top_ids)))
    topics_by_id = {t.id: t for t in topics_result.scalars().all()}

    return [
        {
            "topic_id": tid,
            "name": topics_by_id[tid].name if tid in topics_by_id else "",
            "similarity": round(sim, 4),
        }
        for sim, tid in top
        if tid in topics_by_id
    ]


async def find_similar_tags(
    db: AsyncSession,
    tag_id: int,
    limit: int = 10,
    min_similarity: float = 0.7,
) -> list[dict]:
    """Return tags most similar to the given tag by embedding. Sorted by similarity desc."""
    target_emb = await db.get(TagEmbedding, tag_id)
    if target_emb is None:
        return []

    query_vec = _from_blob(target_emb.embedding).tolist()

    result = await db.execute(
        select(TagEmbedding).where(TagEmbedding.tag_id != tag_id)
    )
    all_embs = result.scalars().all()
    if not all_embs:
        return []

    ids = [e.tag_id for e in all_embs]
    corpus = [_from_blob(e.embedding).tolist() for e in all_embs]
    sims = cosine_similarity_matrix(query_vec, corpus)

    scored = sorted(zip(sims, ids), key=lambda x: x[0], reverse=True)
    top = [(sim, gid) for sim, gid in scored if sim >= min_similarity][:limit]

    if not top:
        return []

    top_ids = [gid for _, gid in top]
    tags_result = await db.execute(select(Tag).where(Tag.id.in_(top_ids)))
    tags_by_id = {t.id: t for t in tags_result.scalars().all()}

    return [
        {
            "tag_id": gid,
            "name": tags_by_id[gid].name if gid in tags_by_id else "",
            "similarity": round(sim, 4),
        }
        for sim, gid in top
        if gid in tags_by_id
    ]


# ---------------------------------------------------------------------------
# Query-based semantic search (embed a query text, rank stored embeddings)
# ---------------------------------------------------------------------------

async def search_topics_semantic(
    db: AsyncSession,
    query_text: str,
    limit: int = 10,
    min_similarity: float = 0.4,
) -> list[dict]:
    """Embed query_text, rank stored topic embeddings by cosine similarity.
    Returns [{topic_id, similarity}, ...] sorted desc. Returns [] if model unavailable."""
    vec = embed_text(query_text)
    if vec is None:
        return []

    result = await db.execute(select(TopicEmbedding))
    all_embs = result.scalars().all()
    if not all_embs:
        return []

    ids = [e.topic_id for e in all_embs]
    corpus = [_from_blob(e.embedding).tolist() for e in all_embs]
    sims = cosine_similarity_matrix(vec, corpus)

    scored = sorted(zip(sims, ids), key=lambda x: x[0], reverse=True)
    top = [(sim, tid) for sim, tid in scored if sim >= min_similarity][:limit]
    return [{"topic_id": tid, "similarity": round(sim, 4)} for sim, tid in top]


async def search_tags_semantic(
    db: AsyncSession,
    query_text: str,
    limit: int = 10,
    min_similarity: float = 0.4,
) -> list[dict]:
    """Same as search_topics_semantic but for tags."""
    vec = embed_text(query_text)
    if vec is None:
        return []

    result = await db.execute(select(TagEmbedding))
    all_embs = result.scalars().all()
    if not all_embs:
        return []

    ids = [e.tag_id for e in all_embs]
    corpus = [_from_blob(e.embedding).tolist() for e in all_embs]
    sims = cosine_similarity_matrix(vec, corpus)

    scored = sorted(zip(sims, ids), key=lambda x: x[0], reverse=True)
    top = [(sim, gid) for sim, gid in scored if sim >= min_similarity][:limit]
    return [{"tag_id": gid, "similarity": round(sim, 4)} for sim, gid in top]


async def search_cards_semantic(
    db: AsyncSession,
    query_text: str,
    limit: int = 500,
    min_similarity: float = 0.35,
) -> list[dict]:
    """Embed query_text, rank stored card embeddings. Returns [{card_id, similarity}, ...] sorted desc."""
    vec = embed_text(query_text)
    if vec is None:
        return []

    result = await db.execute(select(CardEmbedding))
    all_embs = result.scalars().all()
    if not all_embs:
        return []

    ids = [e.card_id for e in all_embs]
    corpus = [_from_blob(e.embedding).tolist() for e in all_embs]
    sims = cosine_similarity_matrix(vec, corpus)

    scored = sorted(zip(sims, ids), key=lambda x: x[0], reverse=True)
    top = [(sim, cid) for sim, cid in scored if sim >= min_similarity][:limit]
    return [{"card_id": cid, "similarity": round(sim, 4)} for sim, cid in top]


# ---------------------------------------------------------------------------
# Duplicate candidate detection (full pairwise via numpy upper-triangle)
# ---------------------------------------------------------------------------

async def find_duplicate_topic_candidates(
    db: AsyncSession,
    min_similarity: float = 0.85,
) -> list[dict]:
    """All topic pairs with embedding similarity >= threshold. Sorted by similarity desc."""
    result = await db.execute(select(TopicEmbedding))
    all_embs = result.scalars().all()
    if len(all_embs) < 2:
        return []

    ids = [e.topic_id for e in all_embs]
    matrix = np.array([_from_blob(e.embedding) for e in all_embs], dtype=np.float32)
    # Cosine similarity matrix (vectors are normalized)
    sim_matrix = matrix @ matrix.T  # (N, N)

    i_idx, j_idx = np.triu_indices(len(ids), k=1)
    sims = sim_matrix[i_idx, j_idx]
    mask = sims >= min_similarity

    if not mask.any():
        return []

    # Load topic metadata for matched ids
    matched_topic_ids = set()
    for i, j, keep in zip(i_idx, j_idx, mask):
        if keep:
            matched_topic_ids.add(ids[i])
            matched_topic_ids.add(ids[j])

    from src.db.models.topic import CardTopic
    from sqlalchemy import func

    count_subq = (
        select(CardTopic.topic_id, func.count(CardTopic.card_id).label("card_count"))
        .group_by(CardTopic.topic_id)
        .subquery()
    )
    topics_result = await db.execute(
        select(Topic, func.coalesce(count_subq.c.card_count, 0).label("card_count"))
        .outerjoin(count_subq, count_subq.c.topic_id == Topic.id)
        .where(Topic.id.in_(matched_topic_ids))
    )
    topic_meta = {
        row.Topic.id: {"id": row.Topic.id, "name": row.Topic.name, "card_count": row.card_count}
        for row in topics_result
    }

    pairs = []
    for i, j, sim, keep in zip(i_idx, j_idx, sims, mask):
        if not keep:
            continue
        a_id, b_id = ids[i], ids[j]
        if a_id not in topic_meta or b_id not in topic_meta:
            continue
        lo, hi = (a_id, b_id) if a_id < b_id else (b_id, a_id)
        pairs.append({
            "topic_a": topic_meta[lo],
            "topic_b": topic_meta[hi],
            "similarity": round(float(sim), 4),
        })

    return sorted(pairs, key=lambda p: p["similarity"], reverse=True)


async def find_duplicate_tag_candidates(
    db: AsyncSession,
    min_similarity: float = 0.85,
) -> list[dict]:
    """All tag pairs with embedding similarity >= threshold. Sorted by similarity desc."""
    result = await db.execute(select(TagEmbedding))
    all_embs = result.scalars().all()
    if len(all_embs) < 2:
        return []

    ids = [e.tag_id for e in all_embs]
    matrix = np.array([_from_blob(e.embedding) for e in all_embs], dtype=np.float32)
    sim_matrix = matrix @ matrix.T

    i_idx, j_idx = np.triu_indices(len(ids), k=1)
    sims = sim_matrix[i_idx, j_idx]
    mask = sims >= min_similarity

    if not mask.any():
        return []

    matched_tag_ids = set()
    for i, j, keep in zip(i_idx, j_idx, mask):
        if keep:
            matched_tag_ids.add(ids[i])
            matched_tag_ids.add(ids[j])

    from src.db.models.tag import CardTag
    from sqlalchemy import func

    count_subq = (
        select(CardTag.tag_id, func.count(CardTag.card_id).label("card_count"))
        .group_by(CardTag.tag_id)
        .subquery()
    )
    tags_result = await db.execute(
        select(Tag, func.coalesce(count_subq.c.card_count, 0).label("card_count"))
        .outerjoin(count_subq, count_subq.c.tag_id == Tag.id)
        .where(Tag.id.in_(matched_tag_ids))
    )
    tag_meta = {
        row.Tag.id: {"id": row.Tag.id, "name": row.Tag.name, "card_count": row.card_count}
        for row in tags_result
    }

    pairs = []
    for i, j, sim, keep in zip(i_idx, j_idx, sims, mask):
        if not keep:
            continue
        a_id, b_id = ids[i], ids[j]
        if a_id not in tag_meta or b_id not in tag_meta:
            continue
        lo, hi = (a_id, b_id) if a_id < b_id else (b_id, a_id)
        pairs.append({
            "tag_a": tag_meta[lo],
            "tag_b": tag_meta[hi],
            "similarity": round(float(sim), 4),
        })

    return sorted(pairs, key=lambda p: p["similarity"], reverse=True)
