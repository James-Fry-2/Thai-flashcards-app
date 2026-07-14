"""
Sentence-transformer embedding wrapper — multilingual (Thai + English).

Default model: paraphrase-multilingual-MiniLM-L12-v2 (384 dims, CPU-friendly).
Model is lazy-loaded on first use and cached — mirrors paddle_ocr.py / easy_ocr.py.

All sentence-transformers calls are wrapped in try/except; failures return None
so the rest of the app stays up if the model is unavailable.
"""
import hashlib
import sys
from typing import Optional

import numpy as np

_model = None


def get_model():
    """Lazy-load the sentence-transformers model. Returns the model or None on failure."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            from src.config.settings import get_settings
            _model = SentenceTransformer(get_settings().embedding_model)
        except Exception:
            return None
    return _model


def embed_text(text: str) -> Optional[list[float]]:
    """Return a single embedding vector for text. Returns None on failure or empty input."""
    if not text or not text.strip():
        return None
    model = get_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    except Exception:
        return None


def embed_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """Batch-embed texts for efficiency during backfill. Returns one vector per input, None for failures."""
    if not texts:
        return []
    model = get_model()
    if model is None:
        return [None] * len(texts)

    results: list[Optional[list[float]]] = [None] * len(texts)
    valid_indices = [i for i, t in enumerate(texts) if t and t.strip()]
    valid_texts = [texts[i] for i in valid_indices]

    if not valid_texts:
        return results

    try:
        vecs = model.encode(valid_texts, normalize_embeddings=True, batch_size=64)
        for pos, idx in enumerate(valid_indices):
            results[idx] = vecs[pos].tolist()
    except Exception:
        pass

    return results


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 on shape mismatch or zero vector."""
    try:
        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        if va.shape != vb.shape:
            return 0.0
        norm_a = float(np.linalg.norm(va))
        norm_b = float(np.linalg.norm(vb))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(va, vb) / (norm_a * norm_b))
    except Exception:
        return 0.0


def cosine_similarity_matrix(query: list[float], corpus: list[list[float]]) -> list[float]:
    """Vectorized: similarities of one query against many. Uses numpy."""
    if not corpus:
        return []
    try:
        q = np.array(query, dtype=np.float32)
        C = np.array(corpus, dtype=np.float32)  # (n, dim)
        if C.ndim != 2 or C.shape[0] == 0:
            return []
        # Vectors are normalized by encode(normalize_embeddings=True), but guard anyway
        q_norm = float(np.linalg.norm(q))
        C_norms = np.linalg.norm(C, axis=1)  # (n,)
        if q_norm == 0.0:
            return [0.0] * C.shape[0]
        dots = C @ q  # (n,)
        sims = dots / (C_norms * q_norm + 1e-9)
        return sims.tolist()
    except Exception:
        return [0.0] * len(corpus)


def text_hash(text: str) -> str:
    """SHA-256 of text string — used to detect when a card/topic/tag changed and embedding is stale."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# CLI helper  (python -m src.utils.embeddings [word1 word2 ...])
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = sys.argv[1:] if len(sys.argv) > 1 else [
        "สวัสดี",
        "hello",
        "hi there",
        "กินข้าว",
        "eating rice",
        "ฉันชอบอาหารไทย",
        "I love Thai food",
    ]

    from src.config.settings import get_settings
    print(f"Model: {get_settings().embedding_model}")
    print()

    vecs = embed_batch(samples)
    for s, v in zip(samples, vecs):
        status = f"{len(v)}-dim" if v else "FAILED"
        print(f"  {s!r:30s}  → {status}")

    print("\nPairwise cosine similarities:")
    for i in range(len(samples)):
        for j in range(i + 1, len(samples)):
            if vecs[i] and vecs[j]:
                sim = cosine_similarity(vecs[i], vecs[j])
                print(f"  {samples[i]!r:20s}  vs  {samples[j]!r:20s}  =  {sim:.4f}")
