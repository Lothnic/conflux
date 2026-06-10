"""
Heuristic fallback logic for proposal generation.

These keyword-matching and threshold functions provide fast, deterministic
proposals when the LLM (Groq) is unavailable or hasn't run yet.
"""

from __future__ import annotations


def infer_issue_type(keywords: str) -> str:
    text = (keywords or "").lower()
    if any(k in text for k in ["light", "lighting", "streetlight", "dark"]):
        return "Public Lighting"
    if any(k in text for k in ["pothole", "road", "traffic", "lane", "signal"]):
        return "Road & Traffic"
    if any(k in text for k in ["garbage", "trash", "waste", "dump", "litter"]):
        return "Sanitation"
    if any(k in text for k in ["water", "drain", "sewer", "flood", "pipeline"]):
        return "Water & Drainage"
    if any(k in text for k in ["park", "tree", "green", "noise", "pollution"]):
        return "Public Space & Environment"
    return "General Infrastructure"


def infer_urgency(size: int) -> str:
    if size >= 20:
        return "high"
    if size >= 8:
        return "medium"
    return "low"


def infer_budget(size: int) -> str:
    if size >= 20:
        return "\u20b92-8 crore"
    if size >= 8:
        return "\u20b940 lakh-\u20b92 crore"
    return "\u20b98-40 lakh"


def proposal_recommendations(issue_type: str) -> list[str]:
    if issue_type == "Road & Traffic":
        return [
            "Survey and prioritize repairs based on severity",
            "Repaint lane markings and improve signage",
            "Coordinate with traffic police for enforcement",
        ]
    if issue_type == "Sanitation":
        return [
            "Increase waste pickup frequency",
            "Add community bins and signage",
            "Launch local awareness and reporting campaign",
        ]
    if issue_type == "Water & Drainage":
        return [
            "Inspect and clear clogged drains",
            "Repair damaged pipelines",
            "Implement flood-mitigation micro-projects",
        ]
    if issue_type == "Public Lighting":
        return [
            "Audit non-functional streetlights",
            "Replace bulbs and wiring",
            "Pilot smart lighting in hotspots",
        ]
    if issue_type == "Public Space & Environment":
        return [
            "Create maintenance schedule for parks",
            "Install noise/pollution monitoring where needed",
            "Add greenery and buffer zones",
        ]
    return [
        "Conduct on-site inspection",
        "Engage local stakeholders",
        "Create phased repair plan",
    ]


# Delhi bodies that own each category of fix.
_AGENCY_MAP: dict[str, list[str]] = {
    "Road & Traffic": [
        "Public Works Department (PWD)",
        "Delhi Traffic Police",
        "Municipal Corporation of Delhi (MCD)",
    ],
    "Sanitation": [
        "Municipal Corporation of Delhi (MCD)",
        "Department of Urban Development",
        "Swachh Bharat Mission (Urban)",
    ],
    "Water & Drainage": [
        "Delhi Jal Board (DJB)",
        "Public Works Department (PWD)",
        "Irrigation & Flood Control Department",
    ],
    "Public Lighting": [
        "Municipal Corporation of Delhi (MCD)",
        "BSES/Tata Power-DDL (DISCOMs)",
        "Public Works Department (PWD)",
    ],
    "Public Space & Environment": [
        "Delhi Development Authority (DDA)",
        "Delhi Pollution Control Committee (DPCC)",
        "Forest Department, GNCTD",
    ],
}


def responsible_agencies(issue_type: str) -> list[str]:
    return _AGENCY_MAP.get(
        issue_type,
        ["Municipal Corporation of Delhi (MCD)", "Office of the District Magistrate"],
    )


def proposal_communication_plan(issue_type: str) -> list[str]:
    """Sequenced stakeholder-outreach steps (heuristic fallback)."""
    lead = responsible_agencies(issue_type)[0]
    return [
        f"Week 1: File a consolidated grievance with {lead} via the Delhi PGMS portal, citing the clustered citizen reports",
        "Week 1: Brief the local Resident Welfare Association (RWA) and ward councillor to build community backing",
        "Week 2: Submit a formal representation to the area MLA for MLA-LAD fund consideration",
        "Week 3: Issue a press note to local Delhi dailies to raise public visibility",
        "Week 4: Escalate to the LG / DDC office if no acknowledgement is received within the PGMS SLA",
    ]


def impact_rationale(issue_type: str, size: int) -> str:
    """One-line justification for the assigned urgency with a rough reach estimate."""
    affected = max(size, 1) * 75  # rough per-complaint catchment of affected residents
    level = infer_urgency(size)
    return (
        f"{level.capitalize()} urgency: {size} clustered complaints indicate a recurring {issue_type.lower()} "
        f"problem affecting an estimated {affected:,}+ residents in the surrounding area."
    )
