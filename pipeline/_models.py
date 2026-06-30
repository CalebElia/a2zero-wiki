import hashlib
from dataclasses import dataclass, field
from typing import Optional, Literal


@dataclass
class SilverDoc:
    uuid: str          # e.g. "a2zero-year1"
    source_type: str   # e.g. "annual-report"
    title: str
    year: Optional[str]
    path: str          # path to .md file
    ingest_date: str   # ISO 8601 date: "2026-06-18"


@dataclass
class Quad:
    id: str
    date: str          # ISO 8601 truncated to precision: "2021" | "2021-09" | "2021-09-15"
    date_precision: str          # "year" | "month" | "day"
    subject: str                 # canonical slug
    relation: str
    object: str
    sources: list[str]
    source_types: list[str]
    confidence: Literal[1, 2]   # 1 = Tier 2 (unverified), 2 = Tier 1 (confirmed)
    status: str                  # "confirmed" | "unverified"
    dark_matter: bool
    topics: list[str]
    locations: list[str]
    strategies: list[str]
    actors: list[str]
    keywords: list[str]
    fund_type: Optional[str]
    commitment_status: Optional[str]
    last_updated: str


@dataclass
class WikiPage:
    page_type: Literal["actor", "initiative", "funding-event", "technology",
                       "location", "meeting", "framing", "political-event", "contradiction", "mechanism"]
    slug: str         # e.g. "actors/missy-stults"
    frontmatter: dict
    body: str


REQUIRED_QUAD_FIELDS = [
    "id", "date", "date_precision", "subject", "relation", "object",
    "sources", "source_types", "confidence", "status", "dark_matter",
    "topics", "locations", "strategies", "actors", "keywords",
    "fund_type", "commitment_status", "last_updated",
]

VALID_DATE_PRECISIONS = {"year", "month", "day"}
VALID_STATUSES = {"confirmed", "unverified"}
VALID_CONFIDENCES = {1, 2}


def make_quad_id(subject: str, relation: str, obj: str, date: str) -> str:
    raw = f"{subject}|{relation}|{obj}|{date}"
    return "sha256-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def validate_quad(quad: dict) -> list[str]:
    errors = []
    for key in REQUIRED_QUAD_FIELDS:
        if key not in quad:
            errors.append(f"missing required field: {key}")
    if "confidence" in quad and quad["confidence"] not in VALID_CONFIDENCES:
        errors.append(f"confidence must be 1 or 2, got: {quad['confidence']}")
    if "status" in quad and quad["status"] not in VALID_STATUSES:
        errors.append(f"status must be 'confirmed' or 'unverified', got: {quad['status']}")
    if "date_precision" in quad and quad["date_precision"] not in VALID_DATE_PRECISIONS:
        errors.append(f"date_precision must be year/month/day, got: {quad['date_precision']}")
    return errors
