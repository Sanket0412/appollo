"""Step 7: embed the resume and every new job, store similarity, and pick the shortlist.

Everything here is local and free (fastembed, BAAI/bge-small-en-v1.5, 384 dims).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from pipeline.log import get_logger
from pipeline.settings import REPO_ROOT, get_settings, resume_text

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DESCRIPTION_CHARS = 2000

log = get_logger("embed")


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    company: str
    description: str | None
    is_nyc_metro: bool


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    embedding: np.ndarray
    similarity: float


def _cache_dir() -> str:
    # CI sets FASTEMBED_CACHE_PATH (workflow caches it); locally keep it under data/cache.
    env = os.environ.get("FASTEMBED_CACHE_PATH")
    path = Path(env).expanduser() if env else REPO_ROOT / "data" / "cache" / "fastembed"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


@lru_cache(maxsize=1)
def get_model():
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME, cache_dir=_cache_dir())


def embed_texts(texts: list[str]) -> np.ndarray:
    """Returns an (n, 384) float32 array of L2-normalized vectors."""
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    vectors = np.array(list(get_model().embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def job_text(title: str, company: str, description: str | None) -> str:
    return f"{title}\n{company}\n{(description or '')[:DESCRIPTION_CHARS]}"


def select_shortlist(scored: list[Scored], min_similarity: float, max_per_run: int) -> set[str]:
    """Ids to shortlist: similarity >= threshold, NYC metro first then similarity, capped."""
    eligible = [s for s in scored if s.similarity >= min_similarity]
    eligible.sort(key=lambda s: (not s.candidate.is_nyc_metro, -s.similarity))
    return {s.candidate.id for s in eligible[:max_per_run]}


def score_candidates(candidates: list[Candidate], resume: str) -> list[Scored]:
    if not candidates:
        return []
    vectors = embed_texts([resume] + [job_text(c.title, c.company, c.description) for c in candidates])
    resume_vec, job_vecs = vectors[0], vectors[1:]
    sims = job_vecs @ resume_vec
    return [Scored(c, v, float(s)) for c, v, s in zip(candidates, job_vecs, sims)]


def run_embedding_stage(conn, min_similarity: float | None = None) -> dict:
    """Embeds every status='new' job and moves it to shortlisted or not_shortlisted."""
    cfg = get_settings().search_config["scoring"]
    threshold = cfg["min_similarity"] if min_similarity is None else min_similarity

    with conn.cursor() as cur:
        cur.execute(
            "select id, title, company, description, is_nyc_metro from public.jobs where status = 'new'"
        )
        candidates = [Candidate(*row) for row in cur.fetchall()]

    scored = score_candidates(candidates, resume_text())
    keep = select_shortlist(scored, threshold, cfg["max_per_run"])

    with conn.cursor() as cur:
        for s in scored:
            cur.execute(
                "update public.jobs set embedding = %s, similarity = %s, status = %s where id = %s",
                (s.embedding, s.similarity, "shortlisted" if s.candidate.id in keep else "not_shortlisted", s.candidate.id),
            )
    conn.commit()

    counts = {"embedded": len(scored), "shortlisted": len(keep), "not_shortlisted": len(scored) - len(keep)}
    log.info("Embedding stage: %s (min_similarity=%.2f)", counts, threshold)
    return counts
