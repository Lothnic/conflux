"""
Conflux API models — Pydantic schemas for request/response validation.
"""

from pydantic import BaseModel
from typing import List


class Complaint(BaseModel):
    text: str
    language: str
    lat: float
    lon: float
    source: str  # e.g., "reddit", "nextdoor", "govt_poll"


class ComplainList(BaseModel):
    complaints: List[Complaint]


class ClusterProposal(BaseModel):
    cluster_id: str
    issue_type: str
    urgency: str  # "low", "medium", "high"
    location: dict  # lat, lon bounds
    summary: str
    recommendations: List[str]
    funding_sources: List[str]
    estimated_budget: str
    communication_plan: List[str] = []
    responsible_agencies: List[str] = []
    impact_rationale: str = ""


class ProposalResponse(BaseModel):
    proposals: List[ClusterProposal]
