"""
Multi-source data ingestion for civic complaints.

Fetches from Reddit, news RSS feeds, Google News, and data.gov.in.
Normalizes all sources into a common thread dict shape.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import sqlalchemy as sa
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("conflux.ingest")

# ─── Config ─────────────────────────────────────────────────────

SUBREDDIT = os.getenv("SUBREDDIT", "delhi")
HOURS_BACK = int(os.getenv("HOURS_BACK", "24"))
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "60.0"))

REDDIT_INGEST_ENABLED = os.getenv("REDDIT_INGEST_ENABLED", "1") == "1"
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "conflux/0.1")

NEWS_INGEST_ENABLED = os.getenv("NEWS_INGEST_ENABLED", "1") == "1"

DATA_GOV_API_KEY = os.getenv("DATA_GOV_API_KEY", "")
DATA_GOV_RESOURCE_ID = os.getenv("DATA_GOV_RESOURCE_ID", "")
DATA_GOV_LIMIT = int(os.getenv("DATA_GOV_LIMIT", "100"))

DEMO_MODE = os.getenv("CONFLUX_DEMO", "0") == "1"

# Import geocoding from the geocoding module
from worker.geocoding import GEOCODE_USER_AGENT, GEOCODE_CITY, resolve_location  # noqa: E402

# ─── Infrastructure keywords ────────────────────────────────────

INFRA_KEYWORDS = [
    "pothole", "potholes", "waterlogging", "water logging",
    "garbage", "trash", "waste management", "sewer", "sewage",
    "drainage", "water supply", "drinking water",
    "streetlight", "street light", "broken signal", "traffic signal",
    "manhole", "open drain", "overflowing drain",
    "power cut", "power outage", "electricity outage",
    "road repair", "road damaged", "broken road", "bad road",
    "traffic jam", "traffic congestion",
    "illegal parking", "encroachment", "dust pollution",
    "air pollution", "noise pollution", "water contamination",
    "pipeline burst", "pipeline leak", "water crisis",
    "landfill", "ghazipur", "bhalswa", "okhla",
    "yamuna", "polluted", "contaminated",
    "\u0938\u0940\u0935\u0930", "\u092a\u093e\u0928\u0940", "\u0917\u0902\u0926\u0917\u0940",
    "\u0915\u091a\u0930\u093e", "\u091f\u0942\u091f\u0940", "\u0938\u0921\u093c\u0915",
    "\u0917\u0921\u094d\u0922\u093e", "\u091c\u0932\u092d\u0930\u093e\u0935",
    "\u092c\u093f\u091c\u0932\u0940", "\u0928\u093e\u0932\u0940",
]

# ─── Reddit ─────────────────────────────────────────────────────

TARGET_SUBS_RAW = os.getenv(
    "TARGET_SUBS",
    "delhi,NewDelhi,india,gurgaon,noida,mumbai,bangalore,pune,hyderabad,kolkata,chennai",
)
TARGET_SUBS = [sub.strip() for sub in TARGET_SUBS_RAW.split(",") if sub.strip()]

SEARCH_QUERIES = [
    "pothole OR waterlogging OR drainage OR sewer OR garbage",
    "broken road OR traffic jam OR power cut OR streetlight",
    "water supply OR pollution OR dust OR footpath OR parking",
    "metro OR bus stop OR sanitation OR waste OR pipeline",
]


def _fetch_reddit_url(url: str) -> dict | None:
    """Fetch JSON from a Reddit endpoint with rate limiting."""
    time.sleep(1.2)
    candidates = [url]
    if "old.reddit.com" in url:
        candidates.append(url.replace("old.reddit.com", "www.reddit.com"))

    for candidate in candidates:
        try:
            req = Request(candidate, method="GET")
            req.add_header("User-Agent", REDDIT_USER_AGENT)
            req.add_header("Accept", "application/json")
            resp = urlopen(req, timeout=15)
            return json.loads(resp.read().decode())
        except (HTTPError, URLError, json.JSONDecodeError) as e:
            log.warning(f"Reddit fetch failed for {candidate[:80]}: {e}")
            continue
    return None


def fetch_new_threads() -> list[dict]:
    """Fetch infra-relevant threads from multiple Reddit subreddits."""
    if not REDDIT_INGEST_ENABLED:
        log.info("Reddit JSON ingestion disabled by REDDIT_INGEST_ENABLED=0.")
        return []
    if not TARGET_SUBS:
        log.info("Reddit ingestion skipped because TARGET_SUBS is empty.")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    all_threads: dict[str, dict] = {}
    seen_ids: set[str] = set()

    for sub in TARGET_SUBS:
        new_url = f"https://old.reddit.com/r/{sub}/new.json?limit=50"
        log.info(f"Fetching r/{sub}/new...")
        data = _fetch_reddit_url(new_url)
        if data:
            for post_data in data.get("data", {}).get("children", []):
                post = post_data.get("data", {})
                created_utc = post.get("created_utc", 0)
                created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                if created_dt < cutoff:
                    continue
                tid = post.get("id", "")
                if not tid or tid in seen_ids:
                    continue
                title = post.get("title", "")
                content = post.get("selftext", "")
                blob = f"{title} {content}".lower()
                if any(kw in blob for kw in INFRA_KEYWORDS):
                    seen_ids.add(tid)
                    all_threads[tid] = _make_thread(tid, post, sub)

        for query in SEARCH_QUERIES:
            encoded = quote_plus(query)
            search_url = f"https://old.reddit.com/r/{sub}/search.json?q={encoded}&sort=new&restrict_sr=on&limit=15&t=month"
            log.info(f"Searching r/{sub} with: {query[:50]}...")
            data = _fetch_reddit_url(search_url)
            if not data:
                continue
            for post_data in data.get("data", {}).get("children", []):
                post = post_data.get("data", {})
                tid = post.get("id", "")
                if not tid or tid in seen_ids:
                    continue
                title = post.get("title", "")
                content = post.get("selftext", "")
                blob = f"{title} {content}".lower()
                if any(kw in blob for kw in INFRA_KEYWORDS):
                    seen_ids.add(tid)
                    all_threads[tid] = _make_thread(tid, post, sub)

    threads = list(all_threads.values())
    log.info(f"Multi-source fetch returned {len(threads)} infra-relevant threads from {TARGET_SUBS}.")
    return threads


def _make_thread(thread_id: str, post: dict, subreddit: str) -> dict:
    created_utc = post.get("created_utc", 0)
    created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
    title = post.get("title", "")
    content = post.get("selftext", "")
    geo = resolve_location(title, content)
    return {
        "thread_id": thread_id,
        "subreddit": subreddit,
        "title": title,
        "content": content,
        "flair": post.get("link_flair_text", "") or "",
        "upvotes": post.get("score", 0),
        "published_at": created_dt,
        **geo,
        "url": f"https://reddit.com/r/{subreddit}/comments/{thread_id}",
    }


# ─── News RSS ───────────────────────────────────────────────────

DEFAULT_NEWS_FEEDS = [
    ("toi-delhi", "https://timesofindia.indiatimes.com/rssfeeds/-2128839596.cms"),
    ("thehindu-delhi", "https://www.thehindu.com/news/cities/delhi/feeder/default.rss"),
    ("toi-india", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
]

GOOGLE_NEWS_QUERIES = [
    "Delhi water contamination OR water supply",
    "Delhi pothole OR road damage OR traffic signal",
    "Delhi garbage OR sanitation OR waste",
    "Delhi waterlogging OR drainage OR sewer",
    "Gurgaon civic waterlogging OR pothole",
    "Noida civic water supply OR traffic",
]


def _parse_news_feeds_env() -> list[tuple[str, str]]:
    raw = os.getenv("NEWS_FEEDS", "").strip()
    if not raw:
        feeds = list(DEFAULT_NEWS_FEEDS)
        for query in GOOGLE_NEWS_QUERIES:
            feeds.append((
                "gnews:" + query[:32].replace(" ", "-"),
                "https://news.google.com/rss/search?q="
                + quote_plus(query + " when:30d")
                + "&hl=en-IN&gl=IN&ceid=IN:en",
            ))
        return feeds
    feeds: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "|" in part:
            name, url = part.split("|", 1)
            feeds.append((name.strip(), url.strip()))
        else:
            feeds.append((part.split("//")[-1].split("/")[0], part))
    return feeds


def fetch_news_threads() -> list[dict]:
    """Fetch infra-relevant items from public civic news RSS feeds."""
    if not NEWS_INGEST_ENABLED:
        log.info("News ingestion disabled (NEWS_INGEST_ENABLED=0). Skipping.")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    threads: dict[str, dict] = {}

    for source, url in _parse_news_feeds_env():
        log.info(f"Fetching news feed {source}: {url[:70]}...")
        try:
            req = Request(url, method="GET")
            req.add_header("User-Agent", GEOCODE_USER_AGENT)
            resp = urlopen(req, timeout=15)
            root = ET.fromstring(resp.read())
        except (HTTPError, URLError, ET.ParseError, ValueError) as e:
            log.warning(f"News feed {source} failed: {e}")
            continue

        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            content = (item.findtext("description") or "").strip()
            link = (item.findtext("link") or "").strip()
            blob = f"{title} {content}".lower()
            if not title or not any(kw in blob for kw in INFRA_KEYWORDS):
                continue

            pub_raw = item.findtext("pubDate")
            published = datetime.now(timezone.utc)
            if pub_raw:
                try:
                    published = parsedate_to_datetime(pub_raw)
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    if published < cutoff:
                        continue
                except (TypeError, ValueError):
                    pass

            uid = item.findtext("guid") or link or title
            tid = "news-" + hashlib.md5(uid.encode("utf-8")).hexdigest()[:16]
            if tid in threads:
                continue
            geo = resolve_location(title, content)
            threads[tid] = {
                "thread_id": tid,
                "subreddit": f"news:{source}",
                "title": title,
                "content": content,
                "flair": "News",
                "upvotes": 0,
                "published_at": published,
                **geo,
                "url": link or url,
                "source": "news",
            }

    items = list(threads.values())
    log.info(f"News fetch returned {len(items)} infra-relevant items.")
    return items


# ─── data.gov.in open data ──────────────────────────────────────

def fetch_opendata_threads() -> list[dict]:
    """Pull a civic dataset from India's Open Government Data platform."""
    if not DATA_GOV_API_KEY or not DATA_GOV_RESOURCE_ID:
        log.info("data.gov.in ingestion skipped (set DATA_GOV_API_KEY and DATA_GOV_RESOURCE_ID to enable).")
        return []

    url = (
        f"https://api.data.gov.in/resource/{DATA_GOV_RESOURCE_ID}"
        f"?api-key={DATA_GOV_API_KEY}&format=json&limit={DATA_GOV_LIMIT}"
    )
    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", GEOCODE_USER_AGENT)
        resp = urlopen(req, timeout=20)
        payload = json.loads(resp.read().decode())
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        log.warning(f"data.gov.in fetch failed: {e}")
        return []

    records = payload.get("records", [])
    title_keys = ("title", "subject", "complaint", "description", "issue", "grievance")
    loc_keys = ("location", "area", "address", "ward", "city", "place", "locality")
    threads: dict[str, dict] = {}

    for rec in records:
        if not isinstance(rec, dict):
            continue
        lower = {k.lower(): v for k, v in rec.items()}
        title = next((str(lower[k]) for k in title_keys if lower.get(k)), "")
        if not title:
            continue
        blob = " ".join(str(v) for v in rec.values()).lower()
        if not any(kw in blob for kw in INFRA_KEYWORDS):
            continue
        loc_text = next((str(lower[k]) for k in loc_keys if lower.get(k)), GEOCODE_CITY)

        tid = "ogd-" + hashlib.md5((DATA_GOV_RESOURCE_ID + title + loc_text).encode("utf-8")).hexdigest()[:16]
        if tid in threads:
            continue
        geo = resolve_location(title, loc_text)
        threads[tid] = {
            "thread_id": tid,
            "subreddit": "gov:data.gov.in",
            "title": title,
            "content": blob[:500],
            "flair": "OpenData",
            "upvotes": 0,
            "published_at": datetime.now(timezone.utc),
            **geo,
            "url": f"https://data.gov.in/resource/{DATA_GOV_RESOURCE_ID}",
            "source": "data.gov.in",
        }

    items = list(threads.values())
    log.info(f"data.gov.in fetch returned {len(items)} infra-relevant records.")
    return items


# ─── Demo data ──────────────────────────────────────────────────

def build_demo_threads() -> list[dict]:
    now = datetime.now(timezone.utc)
    demo = [
        {
            "thread_id": "demo-road-1",
            "subreddit": SUBREDDIT,
            "title": "Potholes on Ring Road near AIIMS are getting worse",
            "content": "Multiple lanes have deep potholes and traffic is crawling every evening.",
            "flair": "Roads",
            "upvotes": 125,
            "published_at": now,
            "lat": 28.5665,
            "lng": 77.2100,
        },
        {
            "thread_id": "demo-road-2",
            "subreddit": SUBREDDIT,
            "title": "Traffic light at Lajpat Nagar intersection is broken",
            "content": "Cars are blocking the crossing and pedestrians cannot safely cross.",
            "flair": "Traffic",
            "upvotes": 88,
            "published_at": now,
            "lat": 28.5678,
            "lng": 77.2432,
        },
        {
            "thread_id": "demo-road-3",
            "subreddit": SUBREDDIT,
            "title": "Road repair needed near Connaught Place outer circle",
            "content": "The surface is uneven and two wheelers are swerving around damaged patches.",
            "flair": "Roads",
            "upvotes": 97,
            "published_at": now,
            "lat": 28.6315,
            "lng": 77.2167,
        },
        {
            "thread_id": "demo-sanitation-1",
            "subreddit": SUBREDDIT,
            "title": "Garbage overflow near Karol Bagh market",
            "content": "Bins are full and the street smells bad after noon.",
            "flair": "Sanitation",
            "upvotes": 142,
            "published_at": now,
            "lat": 28.6519,
            "lng": 77.1909,
        },
        {
            "thread_id": "demo-sanitation-2",
            "subreddit": SUBREDDIT,
            "title": "Trash collection missed again in Dwarka sector 10",
            "content": "Residents report bags piling up for the third day.",
            "flair": "Waste",
            "upvotes": 76,
            "published_at": now,
            "lat": 28.5873,
            "lng": 77.0444,
        },
        {
            "thread_id": "demo-sanitation-3",
            "subreddit": SUBREDDIT,
            "title": "Illegal dumping behind the park in Janakpuri",
            "content": "Construction debris and waste are blocking the back lane.",
            "flair": "Waste",
            "upvotes": 64,
            "published_at": now,
            "lat": 28.6216,
            "lng": 77.0910,
        },
        {
            "thread_id": "demo-water-1",
            "subreddit": SUBREDDIT,
            "title": "Severe waterlogging after rain in East Delhi",
            "content": "Drainage is clogged and the road stays flooded for hours.",
            "flair": "Drainage",
            "upvotes": 133,
            "published_at": now,
            "lat": 28.6510,
            "lng": 77.3027,
        },
        {
            "thread_id": "demo-water-2",
            "subreddit": SUBREDDIT,
            "title": "Sewer smell and drain overflow near Shahdara",
            "content": "Residents say the drain has not been cleaned in weeks.",
            "flair": "Drainage",
            "upvotes": 91,
            "published_at": now,
            "lat": 28.6776,
            "lng": 77.2910,
        },
        {
            "thread_id": "demo-water-3",
            "subreddit": SUBREDDIT,
            "title": "Water pipeline leak causing road damage in Saket",
            "content": "The broken pipe has created puddles and a slippery road surface.",
            "flair": "Water",
            "upvotes": 58,
            "published_at": now,
            "lat": 28.5245,
            "lng": 77.2066,
        },
    ]
    return demo
