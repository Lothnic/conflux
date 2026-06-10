"""
Geocoding and location resolution for civic complaints.

Uses an LLM to extract place names, then Nominatim for coordinate lookup.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("conflux.geocoding")

# ─── Config ─────────────────────────────────────────────────────

GEOCODE_ENABLED = os.getenv("GEOCODE_ENABLED", "1") == "1"
GEOCODE_CITY = os.getenv("GEOCODE_CITY", "Delhi")
GEOCODE_RATE_LIMIT = float(os.getenv("GEOCODE_RATE_LIMIT", "1.2"))
GEOCODE_USER_AGENT = os.getenv("GEOCODE_USER_AGENT", "conflux/0.1")
GEOCODE_MIN_CONFIDENCE = float(os.getenv("GEOCODE_MIN_CONFIDENCE", "0.45"))
GEOCODE_CITY_FALLBACK_ENABLED = os.getenv("GEOCODE_CITY_FALLBACK_ENABLED", "0") == "1"
LLM_GEOLOCATION_ENABLED = os.getenv("LLM_GEOLOCATION_ENABLED", "1") == "1"
LOCAL_GEO_FALLBACK_ENABLED = os.getenv("LOCAL_GEO_FALLBACK_ENABLED", "1") == "1"

GEO_LLM_API_KEY = os.getenv("GEO_LLM_API_KEY") or os.getenv("GROQ_API_KEY", "")
GEO_LLM_MODEL = os.getenv("GEO_LLM_MODEL") or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEO_LLM_API_URL = os.getenv("GEO_LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")


# ─── Local gazetteer fallback ───────────────────────────────────

LOCAL_PLACE_CANDIDATES = [
    ("Ghazipur", "neighborhood"),
    ("Bhalswa", "neighborhood"),
    ("Okhla", "neighborhood"),
    ("Yamuna", "neighborhood"),
    ("Chattarpur", "neighborhood"),
    ("Gulmohar Park", "neighborhood"),
    ("Janakpuri", "neighborhood"),
    ("Pitampura", "neighborhood"),
    ("Rohini", "neighborhood"),
    ("Dwarka", "neighborhood"),
    ("Karol Bagh", "neighborhood"),
    ("Lajpat Nagar", "neighborhood"),
    ("Saket", "neighborhood"),
    ("Vasant Kunj", "neighborhood"),
    ("Mayur Vihar", "neighborhood"),
    ("Noida", "city"),
    ("Gurgaon", "city"),
    ("Gurugram", "city"),
    ("Delhi", "city"),
]


def extract_location_candidate_locally(title: str, content: str) -> dict | None:
    """Cheap gazetteer fallback for source titles when the LLM is unavailable."""
    if not LOCAL_GEO_FALLBACK_ENABLED:
        return None

    blob = f"{title} {content or ''}".lower()
    for place, precision in LOCAL_PLACE_CANDIDATES:
        if place.lower() in blob:
            return {
                "location_text": place,
                "precision": precision,
                "confidence": 0.7 if precision != "city" else 0.35,
                "reason": "Matched local place gazetteer",
            }

    sector_match = re.search(r"\b(?:sector|sec)\s*[- ]?([0-9]{1,3}[a-z]?)\b", blob)
    if sector_match:
        return {
            "location_text": f"Sector {sector_match.group(1)}",
            "precision": "neighborhood",
            "confidence": 0.62,
            "reason": "Matched sector mention",
        }

    return None


# ─── LLM location extraction ────────────────────────────────────

def extract_location_candidate(title: str, content: str) -> dict:
    """Use an OpenAI-compatible LLM to extract the most geocodable place phrase."""
    local_candidate = extract_location_candidate_locally(title, content)
    if local_candidate:
        return local_candidate

    if not LLM_GEOLOCATION_ENABLED or not GEO_LLM_API_KEY:
        return {
            "location_text": "",
            "confidence": 0.0,
            "precision": "unresolved",
            "reason": "LLM geolocation disabled or API key missing",
        }

    prompt = f"""Extract the most specific real-world location mentioned in this civic complaint.
Return only JSON with keys:
- location_text: string, a concise geocoder-ready place in/near {GEOCODE_CITY}, India
- confidence: number from 0 to 1
- precision: one of "landmark", "street", "intersection", "neighborhood", "ward", "city", "unresolved"
- reason: short string

Rules:
- Do not invent a place. If no specific place is mentioned, use location_text="" and precision="unresolved".
- Prefer named landmarks, metro stations, markets, intersections, sectors, colonies, roads, wards, or neighborhoods.
- Do not output latitude or longitude.

Title: {title[:500]}
Body: {(content or "")[:1000]}"""

    payload = json.dumps({
        "model": GEO_LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You extract location mentions for civic geocoding. Output strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode()

    req = Request(GEO_LLM_API_URL, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {GEO_LLM_API_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Conflux/0.1")

    try:
        resp = urlopen(req, timeout=45)
        data = json.loads(resp.read().decode())
        content_json = json.loads(data["choices"][0]["message"]["content"])
        location_text = str(content_json.get("location_text") or "").strip()
        precision = str(content_json.get("precision") or "unresolved").strip().lower()
        confidence = float(content_json.get("confidence") or 0)
        return {
            "location_text": location_text,
            "precision": precision,
            "confidence": max(0.0, min(confidence, 1.0)),
            "reason": str(content_json.get("reason") or ""),
        }
    except (HTTPError, URLError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        log.warning(f"LLM location extraction failed: {e}")
        return {
            "location_text": "",
            "confidence": 0.0,
            "precision": "unresolved",
            "reason": str(e),
        }


# ─── Nominatim geocoder ─────────────────────────────────────────

def precision_to_meters(precision: str) -> int | None:
    return {
        "landmark": 80,
        "intersection": 120,
        "street": 250,
        "neighborhood": 900,
        "ward": 1800,
        "city": 8000,
    }.get(precision)


def geocoder_importance_score(raw: dict) -> float:
    try:
        importance = float(raw.get("importance") or 0)
    except (TypeError, ValueError):
        importance = 0
    return max(0.0, min(importance, 1.0))


def geocode_text(query: str) -> dict | None:
    if not GEOCODE_ENABLED:
        return None
    try:
        url = (
            "https://nominatim.openstreetmap.org/search?"
            f"format=json&addressdetails=1&q={quote_plus(query)}&limit=1"
        )
        req = Request(url, method="GET")
        req.add_header("User-Agent", GEOCODE_USER_AGENT)
        resp = urlopen(req, timeout=15)
        results = json.loads(resp.read().decode())
        if not results:
            return None
        raw = results[0]
        return {
            "lat": float(raw.get("lat")),
            "lng": float(raw.get("lon")),
            "raw": raw,
        }
    except HTTPError as e:
        if e.code == 429:
            log.warning("Geocoding rate-limited, backing off 3s...")
            time.sleep(3)
        else:
            log.warning(f"Geocoding failed for '{query[:60]}...': {e}")
        return None
    except Exception as e:
        log.warning(f"Geocoding failed for '{query[:60]}...': {e}")
        return None


def unresolved_geo(method: str = "unresolved", reason: str = "") -> dict:
    return {
        "lat": None,
        "lng": None,
        "location_text": "",
        "location_method": method,
        "location_confidence": 0.0,
        "location_precision_meters": None,
        "geocoder_provider": "",
        "geocoder_query": "",
        "geocoder_raw": json.dumps({"reason": reason}) if reason else "",
    }


# ─── High-level resolve ─────────────────────────────────────────

def resolve_location(title: str, content: str) -> dict:
    """Resolve a complaint to a geolocation with quality metadata."""
    if not GEOCODE_ENABLED:
        return unresolved_geo("geocoding_disabled")

    candidate = extract_location_candidate(title, content)
    location_text = candidate.get("location_text", "")
    precision = candidate.get("precision", "unresolved")
    llm_confidence = float(candidate.get("confidence", 0) or 0)

    if not location_text or precision in {"unresolved", "city"} or llm_confidence < GEOCODE_MIN_CONFIDENCE:
        if not GEOCODE_CITY_FALLBACK_ENABLED:
            return unresolved_geo("ai_place_extraction", candidate.get("reason", "No reliable location mention"))
        location_text = GEOCODE_CITY
        precision = "city"
        llm_confidence = min(llm_confidence, 0.25)

    time.sleep(GEOCODE_RATE_LIMIT)
    query = location_text if GEOCODE_CITY.lower() in location_text.lower() else f"{location_text}, {GEOCODE_CITY}, India"
    result = geocode_text(query)
    if not result:
        return {
            **unresolved_geo("geocoder_no_result", candidate.get("reason", "")),
            "location_text": location_text,
            "geocoder_query": query,
        }

    provider_confidence = geocoder_importance_score(result["raw"])
    confidence = round(max(0.0, min((llm_confidence * 0.72) + (provider_confidence * 0.28), 1.0)), 3)
    if confidence < GEOCODE_MIN_CONFIDENCE and not GEOCODE_CITY_FALLBACK_ENABLED:
        return {
            **unresolved_geo("low_confidence_geocode", candidate.get("reason", "")),
            "location_text": location_text,
            "location_confidence": confidence,
            "geocoder_provider": "nominatim",
            "geocoder_query": query,
            "geocoder_raw": json.dumps(result["raw"])[:4000],
        }

    return {
        "lat": result["lat"],
        "lng": result["lng"],
        "location_text": location_text,
        "location_method": "ai_extracted_geocoder",
        "location_confidence": confidence,
        "location_precision_meters": precision_to_meters(precision),
        "geocoder_provider": "nominatim",
        "geocoder_query": query,
        "geocoder_raw": json.dumps(result["raw"])[:4000],
    }


def resolve_coordinates(title: str, content: str) -> tuple[float | None, float | None]:
    """Backward-compatible wrapper for older callers/tests."""
    geo = resolve_location(title, content)
    return geo.get("lat"), geo.get("lng")
