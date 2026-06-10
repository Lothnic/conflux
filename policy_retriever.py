"""
Lightweight local policy retrieval for the planning agent.

This is intentionally file-backed and deterministic so the demo works without a
hosted vector DB or heavyweight ML dependencies in the web runtime.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


POLICY_DIR = Path(__file__).resolve().parent / "policy_docs"
TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]+")
STOP_WORDS = {
    "and", "are", "for", "from", "has", "have", "into", "near", "that",
    "the", "this", "with", "within", "will", "your", "about", "after",
    "before", "between", "should", "their", "there", "where",
}


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


def _tokens(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN_RE.findall(text) if tok.lower() not in STOP_WORDS]


def _tf(tokens: list[str]) -> Counter[str]:
    return Counter(tokens)


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    common = set(left) & set(right)
    dot = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def retrieve_policy(query: str, limit: int = 3) -> list[PolicyHit]:
    docs = _load_docs()
    if not docs:
        return []

    query_vector = _tf(_tokens(query))
    ranked: list[tuple[int, float]] = []
    for idx, (_, _, text) in enumerate(docs):
        ranked.append((idx, _cosine(query_vector, _tf(_tokens(text)))))
    ranked.sort(key=lambda item: item[1], reverse=True)

    hits = []
    for idx, score in ranked[:limit]:
        doc_id, title, text = docs[idx]
        snippet = "\n".join(line for line in text.splitlines()[2:] if line.strip())[:900]
        hits.append(PolicyHit(doc_id=doc_id, title=title, score=float(score), snippet=snippet))
    return hits
