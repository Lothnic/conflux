"""
Shared utility functions used across services.
"""

from __future__ import annotations


def source_url(thread_id: str, source: str | None, stored_url: str | None = None) -> str:
    if stored_url:
        return stored_url
    source = source or "delhi"
    if source.startswith("news:") or source.startswith("gov:"):
        return ""
    return f"https://reddit.com/r/{source}/comments/{thread_id}"
