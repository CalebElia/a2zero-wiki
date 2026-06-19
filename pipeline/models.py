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
    page_type: Literal["actor", "initiative", "commitment", "funding", "meeting", "framing", "political-event", "technology"]
    slug: str         # e.g. "actors/missy-stults"
    frontmatter: dict
    body: str
