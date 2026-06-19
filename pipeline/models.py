from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SilverDoc:
    uuid: str          # e.g. "a2zero-year1"
    source_type: str   # e.g. "annual-report"
    title: str
    year: Optional[str]
    path: str          # path to .md file


@dataclass
class Quad:
    id: str
    date: str
    date_precision: str          # "year" | "month" | "day"
    subject: str                 # canonical slug
    relation: str
    object: str
    sources: list[str]
    source_types: list[str]
    confidence: int              # 1 | 2
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
    page_type: str    # "actor" | "initiative" | "commitment" | "funding" | "meeting"
    slug: str         # e.g. "actors/missy-stults"
    frontmatter: dict
    body: str
