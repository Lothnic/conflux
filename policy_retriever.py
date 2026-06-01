"""
Lightweight local policy retrieval for the planning agent.

This is intentionally file-backed and deterministic so the hackathon demo works
without a hosted vector DB. It can later be swapped for Chroma/Qdrant.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


POLICY_DIR = Path(__file__).resolve().parent / "policy_docs"


@dataclass(frozen=True)
class PolicyHit:
    doc_id: str
    title: str
    score: float
    snippet: str


def _load_docs() -> list[tuple[str, str, str]]:
    docs = []
    for path in sorted(POLICY_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip() if text.splitlines() else path.stem
        docs.append((path.stem, title, text))
    return docs


def retrieve_policy(query: str, limit: int = 3) -> list[PolicyHit]:
    docs = _load_docs()
    if not docs:
        return []

    corpus = [doc[2] for doc in docs]
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(corpus + [query])
    scores = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
    ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[:limit]

    hits = []
    for idx, score in ranked:
        doc_id, title, text = docs[idx]
        snippet = "\n".join(line for line in text.splitlines()[2:] if line.strip())[:900]
        hits.append(PolicyHit(doc_id=doc_id, title=title, score=float(score), snippet=snippet))
    return hits
