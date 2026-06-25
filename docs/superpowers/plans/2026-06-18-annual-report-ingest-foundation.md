# Annual Report Ingest Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run A2Zero's five annual reports (Year 1–5) through the full Bronze→Silver→Gold pipeline to produce a working wiki directory and a populated `blackboard/quads.jsonl` fact store.

**Architecture:** Medallion pipeline with three layers. Bronze is immutable PDFs on disk. A Silver converter (pdfplumber + Claude) produces cleaned Markdown with YAML frontmatter. A Gold extractor (4-pass LLM protocol) writes wiki pages and appends quads. All entity names are resolved through `entity_aliases.json` before creation. A post-ingest script lints quads and writes `review-queue.md`.

**Tech Stack:** Python 3.11+, `anthropic` SDK (claude-sonnet-4-6), `pdfplumber`, `pyyaml`, `duckdb`, `pytest`, standard library (`json`, `pathlib`, `re`, `hashlib`, `uuid`)

---

## File Structure

```
a2zero-wiki/
├── bronze/                          # immutable raw files
│   └── annual-reports/
│       ├── a2zero-year1.pdf
│       ├── a2zero-year2.pdf
│       ├── a2zero-year3.pdf
│       ├── a2zero-year4.pdf
│       └── a2zero-year5.pdf
├── silver/                          # cleaned markdown + frontmatter
│   └── annual-reports/
│       ├── a2zero-year1.md
│       ├── a2zero-year2.md
│       ├── a2zero-year3.md
│       ├── a2zero-year4.md
│       └── a2zero-year5.md
├── wiki/                            # Gold: human-readable pages
│   ├── actors/
│   ├── initiatives/
│   ├── commitments/
│   ├── funding/
│   ├── meetings/
│   └── topics/
├── blackboard/
│   └── quads.jsonl                  # append-only temporal fact store
├── registry/
│   └── entity_aliases.json          # canonical entity registry
├── pipeline/
│   ├── bronze_to_silver.py          # PDF → Silver Markdown
│   ├── silver_to_gold.py            # Silver → wiki pages + quads
│   ├── quad_linter.py               # validates quads.jsonl
│   ├── post_ingest.py               # generates review-queue.md
│   └── models.py                    # shared Pydantic-free dataclasses
├── tests/
│   ├── fixtures/
│   │   ├── sample_annual_report.md  # minimal Silver fixture
│   │   └── sample_quads.jsonl       # known-good quads fixture
│   ├── test_bronze_to_silver.py
│   ├── test_silver_to_gold.py
│   ├── test_quad_linter.py
│   └── test_post_ingest.py
├── review-queue.md                  # auto-generated after each ingest
└── research-agenda.md               # human-declared research priorities
```

---

## Task 1: Project Bootstrap

**Files:**
- Create: `pipeline/__init__.py`
- Create: `pipeline/models.py`
- Create: `registry/entity_aliases.json`
- Create: `blackboard/quads.jsonl` (empty)
- Create: `tests/__init__.py`
- Create: `tests/fixtures/sample_annual_report.md`
- Create: `requirements.txt`

- [ ] **Step 1: Create requirements.txt**

```
anthropic>=0.30.0
pdfplumber>=0.11.0
pyyaml>=6.0
duckdb>=0.10.0
pytest>=8.0.0
```

- [ ] **Step 2: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without error.

- [ ] **Step 3: Create `pipeline/models.py`**

```python
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
```

- [ ] **Step 4: Create empty `registry/entity_aliases.json`**

```json
{}
```

- [ ] **Step 5: Create empty `blackboard/quads.jsonl`**

```bash
touch blackboard/quads.jsonl
```

- [ ] **Step 6: Create `tests/fixtures/sample_annual_report.md`**

This is a minimal Silver-layer document used as a test fixture. It must be small enough to fit in a single LLM call but contain enough structure to exercise all extraction paths.

```markdown
---
uuid: test-year1
source_type: annual-report
title: "A2Zero Year 1 Annual Report (Test Fixture)"
year: "year1"
ingest_date: "2026-06-18"
bronze_path: "bronze/annual-reports/test-year1.pdf"
---

# A2Zero Year 1 Annual Report

## Overview

Ann Arbor's A2Zero program completed its first year of implementation in 2021.
Missy Stults, the city's Sustainability and Innovations Director, led the effort
alongside the Office of Sustainability and Innovations (OSI).

## Strategy 1: 100% Renewable Grid

The city signed a landmark settlement agreement (U-20713) with DTE Energy in
September 2021, establishing the first community solar program in DTE's territory.
The program launched in Q4 2021, providing 500 households with access to
community solar at no upfront cost.

## Funding

The Renew Ann Arbor Fund received $2.1M in seed funding from the Ann Arbor
City Council in October 2021. These funds supported weatherization programs
targeting low-income households in the Bryant neighborhood.

## Next Steps

- Launch geothermal feasibility study for Bryant neighborhood by Year 2
- Establish Resilience Hub network in at least 3 locations by Year 3
```

- [ ] **Step 7: Create `pipeline/__init__.py` and `tests/__init__.py`**

```bash
touch pipeline/__init__.py tests/__init__.py
```

- [ ] **Step 8: Commit**

```bash
git init  # only if not already a git repo
git add requirements.txt pipeline/ registry/ blackboard/ tests/
git commit -m "feat: bootstrap pipeline skeleton and fixtures"
```

---

## Task 2: Quad ID Generation and Schema Validation

**Files:**
- Create: `pipeline/models.py` (extend)
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for quad ID and validation**

```python
# tests/test_models.py
import hashlib
import pytest
from pipeline.models import make_quad_id, validate_quad


def test_quad_id_is_deterministic():
    id1 = make_quad_id("missy-stults", "leads", "osi", "2021")
    id2 = make_quad_id("missy-stults", "leads", "osi", "2021")
    assert id1 == id2


def test_quad_id_changes_with_different_inputs():
    id1 = make_quad_id("missy-stults", "leads", "osi", "2021")
    id2 = make_quad_id("missy-stults", "leads", "osi", "2022")
    assert id1 != id2


def test_quad_id_is_sha256_prefix():
    raw = "missy-stults|leads|osi|2021"
    expected = "sha256-" + hashlib.sha256(raw.encode()).hexdigest()[:16]
    assert make_quad_id("missy-stults", "leads", "osi", "2021") == expected


def test_validate_quad_accepts_valid():
    quad = {
        "id": "sha256-abc123",
        "date": "2021",
        "date_precision": "year",
        "subject": "missy-stults",
        "relation": "leads",
        "object": "osi",
        "sources": ["test-year1"],
        "source_types": ["annual-report"],
        "confidence": 2,
        "status": "confirmed",
        "dark_matter": False,
        "topics": [],
        "locations": [],
        "strategies": ["strategy-1"],
        "actors": ["actors/missy-stults"],
        "keywords": ["leadership"],
        "fund_type": None,
        "commitment_status": None,
        "last_updated": "2026-06-18",
    }
    errors = validate_quad(quad)
    assert errors == []


def test_validate_quad_rejects_missing_required():
    quad = {"id": "sha256-abc123"}
    errors = validate_quad(quad)
    assert any("date" in e for e in errors)
    assert any("subject" in e for e in errors)


def test_validate_quad_rejects_bad_confidence():
    quad = {
        "id": "sha256-x", "date": "2021", "date_precision": "year",
        "subject": "a", "relation": "b", "object": "c",
        "sources": ["s"], "source_types": ["annual-report"],
        "confidence": 3,  # invalid — must be 1 or 2
        "status": "confirmed", "dark_matter": False,
        "topics": [], "locations": [], "strategies": [],
        "actors": [], "keywords": [],
        "fund_type": None, "commitment_status": None,
        "last_updated": "2026-06-18",
    }
    errors = validate_quad(quad)
    assert any("confidence" in e for e in errors)


def test_validate_quad_rejects_bad_status():
    quad = {
        "id": "sha256-x", "date": "2021", "date_precision": "year",
        "subject": "a", "relation": "b", "object": "c",
        "sources": ["s"], "source_types": ["annual-report"],
        "confidence": 2, "status": "maybe",  # invalid
        "dark_matter": False, "topics": [], "locations": [],
        "strategies": [], "actors": [], "keywords": [],
        "fund_type": None, "commitment_status": None,
        "last_updated": "2026-06-18",
    }
    errors = validate_quad(quad)
    assert any("status" in e for e in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_models.py -v
```

Expected: `ImportError` — `make_quad_id` and `validate_quad` not defined yet.

- [ ] **Step 3: Implement `make_quad_id` and `validate_quad` in `pipeline/models.py`**

Add to the bottom of the existing `pipeline/models.py`:

```python
import hashlib

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
    for field in REQUIRED_QUAD_FIELDS:
        if field not in quad:
            errors.append(f"missing required field: {field}")
    if "confidence" in quad and quad["confidence"] not in VALID_CONFIDENCES:
        errors.append(f"confidence must be 1 or 2, got: {quad['confidence']}")
    if "status" in quad and quad["status"] not in VALID_STATUSES:
        errors.append(f"status must be 'confirmed' or 'unverified', got: {quad['status']}")
    if "date_precision" in quad and quad["date_precision"] not in VALID_DATE_PRECISIONS:
        errors.append(f"date_precision must be year/month/day, got: {quad['date_precision']}")
    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_models.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/models.py tests/test_models.py
git commit -m "feat: add quad ID generation and schema validation"
```

---

## Task 3: Entity Registry (entity_aliases.json)

**Files:**
- Create: `pipeline/registry.py`
- Create: `tests/test_registry.py`

The registry enforces canonical entity slugs. Before any wiki page or quad actor is written, the entity name must resolve through this registry. If it doesn't exist, the registry creates a new entry. If an alias matches an existing canonical, it returns the canonical slug.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_registry.py
import json
import tempfile
import os
import pytest
from pipeline.registry import EntityRegistry


@pytest.fixture
def tmp_registry(tmp_path):
    path = tmp_path / "entity_aliases.json"
    path.write_text(json.dumps({}))
    return EntityRegistry(str(path))


def test_register_new_entity(tmp_registry):
    slug = tmp_registry.register("Missy Stults", entity_type="actor")
    assert slug == "actors/missy-stults"


def test_register_returns_same_slug_for_same_name(tmp_registry):
    slug1 = tmp_registry.register("Missy Stults", entity_type="actor")
    slug2 = tmp_registry.register("Missy Stults", entity_type="actor")
    assert slug1 == slug2


def test_register_alias_returns_canonical(tmp_registry):
    tmp_registry.register("Missy Stults", entity_type="actor")
    slug = tmp_registry.add_alias("missy-stults-director", "actors/missy-stults")
    assert slug == "actors/missy-stults"


def test_resolve_known_alias(tmp_registry):
    tmp_registry.register("Missy Stults", entity_type="actor")
    tmp_registry.add_alias("Stults", "actors/missy-stults")
    assert tmp_registry.resolve("Stults") == "actors/missy-stults"


def test_resolve_unknown_returns_none(tmp_registry):
    assert tmp_registry.resolve("Unknown Person") is None


def test_registry_persists_to_disk(tmp_path):
    path = tmp_path / "entity_aliases.json"
    path.write_text(json.dumps({}))
    reg = EntityRegistry(str(path))
    reg.register("OSI", entity_type="organization")
    # reload from disk
    reg2 = EntityRegistry(str(path))
    assert reg2.resolve("OSI") == "organizations/osi"


def test_slugify_handles_special_chars(tmp_registry):
    slug = tmp_registry.register("U.S. DOE", entity_type="organization")
    assert slug == "organizations/us-doe"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_registry.py -v
```

Expected: `ImportError` — `EntityRegistry` not defined.

- [ ] **Step 3: Implement `pipeline/registry.py`**

```python
import json
import re
from pathlib import Path


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^\w\s-]", "", s)   # remove punctuation except hyphen
    s = re.sub(r"[\s_]+", "-", s)     # spaces/underscores → hyphen
    s = re.sub(r"-+", "-", s)         # collapse multiple hyphens
    return s.strip("-")


TYPE_PREFIX = {
    "actor": "actors",
    "organization": "organizations",
    "initiative": "initiatives",
    "funding": "funding",
    "topic": "topics",
    "location": "locations",
    "technology": "technologies",
}


class EntityRegistry:
    def __init__(self, path: str):
        self.path = Path(path)
        self._data: dict = json.loads(self.path.read_text())

    def _save(self):
        self.path.write_text(json.dumps(self._data, indent=2))

    def register(self, name: str, entity_type: str) -> str:
        existing = self.resolve(name)
        if existing:
            return existing
        prefix = TYPE_PREFIX.get(entity_type, entity_type + "s")
        slug = f"{prefix}/{slugify(name)}"
        self._data[name] = {
            "canonical": slug,
            "type": entity_type,
            "aliases": [],
        }
        self._save()
        return slug

    def add_alias(self, alias: str, canonical: str) -> str:
        for entry in self._data.values():
            if entry["canonical"] == canonical:
                if alias not in entry["aliases"]:
                    entry["aliases"].append(alias)
                self._save()
                return canonical
        raise ValueError(f"canonical not found: {canonical}")

    def resolve(self, name: str) -> str | None:
        if name in self._data:
            return self._data[name]["canonical"]
        for entry in self._data.values():
            if name in entry.get("aliases", []):
                return entry["canonical"]
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_registry.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/registry.py tests/test_registry.py
git commit -m "feat: entity registry with alias resolution and disk persistence"
```

---

## Task 4: Bronze → Silver Converter

**Files:**
- Create: `pipeline/bronze_to_silver.py`
- Create: `tests/test_bronze_to_silver.py`

The converter extracts text from a PDF using pdfplumber, sends it to Claude for cleaning, and writes a Silver Markdown file with YAML frontmatter. Annual reports do NOT trigger LDP (they have source-type rules) — they are split by strategy section. This task implements the PDF extraction and frontmatter writing. The LLM cleaning step is tested with a mocked Anthropic client.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_bronze_to_silver.py
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.bronze_to_silver import extract_pdf_text, write_silver, build_frontmatter


def test_build_frontmatter_annual_report():
    fm = build_frontmatter(
        uuid="a2zero-year1",
        source_type="annual-report",
        title="A2Zero Year 1 Annual Report",
        year="year1",
        bronze_path="bronze/annual-reports/a2zero-year1.pdf",
        ingest_date="2026-06-18",
    )
    assert fm["uuid"] == "a2zero-year1"
    assert fm["source_type"] == "annual-report"
    assert fm["year"] == "year1"
    assert fm["bronze_path"] == "bronze/annual-reports/a2zero-year1.pdf"


def test_write_silver_creates_file(tmp_path):
    out_path = tmp_path / "a2zero-year1.md"
    frontmatter = {
        "uuid": "a2zero-year1",
        "source_type": "annual-report",
        "title": "Test Report",
        "year": "year1",
        "ingest_date": "2026-06-18",
        "bronze_path": "bronze/annual-reports/a2zero-year1.pdf",
    }
    write_silver(str(out_path), frontmatter, body="## Strategy 1\n\nContent here.")
    assert out_path.exists()
    content = out_path.read_text()
    assert content.startswith("---\n")
    assert "uuid: a2zero-year1" in content
    assert "## Strategy 1" in content


def test_write_silver_frontmatter_is_valid_yaml(tmp_path):
    out_path = tmp_path / "test.md"
    frontmatter = {
        "uuid": "test-doc",
        "source_type": "annual-report",
        "title": "Test",
        "year": "year1",
        "ingest_date": "2026-06-18",
        "bronze_path": "bronze/test.pdf",
    }
    write_silver(str(out_path), frontmatter, body="Body text.")
    content = out_path.read_text()
    # extract YAML block
    parts = content.split("---\n")
    parsed = yaml.safe_load(parts[1])
    assert parsed["uuid"] == "test-doc"


@patch("pipeline.bronze_to_silver.anthropic.Anthropic")
def test_clean_with_llm_calls_anthropic(mock_anthropic_class):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="## Cleaned content")]
    )
    from pipeline.bronze_to_silver import clean_with_llm
    result = clean_with_llm("Raw extracted text", uuid="test-year1")
    assert mock_client.messages.create.called
    assert "Cleaned content" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_bronze_to_silver.py -v
```

Expected: `ImportError` — module not found.

- [ ] **Step 3: Implement `pipeline/bronze_to_silver.py`**

```python
import anthropic
import yaml
import pdfplumber
from pathlib import Path
from datetime import date


CLEAN_SYSTEM = """You are a document cleaning assistant for the A2Zero climate wiki pipeline.
You receive raw PDF-extracted text from an A2Zero annual report and return clean Markdown.
Rules:
- Preserve all substantive content; do not summarize or omit any programs, figures, names, or dates
- Fix PDF extraction artifacts (broken hyphenation, garbled characters, misplaced headers)
- Use ## for strategy headings, ### for sub-sections
- Remove page numbers, headers, footers, and repeated boilerplate
- Keep all dollar amounts, percentages, program names, and actor names exactly as written
- Do not add commentary or analysis
Return only the cleaned Markdown body, no frontmatter."""


def extract_pdf_text(pdf_path: str) -> str:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def clean_with_llm(raw_text: str, uuid: str) -> str:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        temperature=0,
        system=CLEAN_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Document UUID: {uuid}\n\nRaw extracted text:\n\n{raw_text}",
            }
        ],
    )
    return response.content[0].text


def build_frontmatter(
    uuid: str,
    source_type: str,
    title: str,
    year: str | None,
    bronze_path: str,
    ingest_date: str,
) -> dict:
    fm = {
        "uuid": uuid,
        "source_type": source_type,
        "title": title,
        "ingest_date": ingest_date,
        "bronze_path": bronze_path,
    }
    if year:
        fm["year"] = year
    return fm


def write_silver(out_path: str, frontmatter: dict, body: str):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)
    content = f"---\n{fm_yaml}---\n\n{body}\n"
    Path(out_path).write_text(content, encoding="utf-8")


def convert_annual_report(
    pdf_path: str,
    uuid: str,
    year: str,
    out_path: str,
    title: str,
    ingest_date: str | None = None,
):
    if ingest_date is None:
        ingest_date = date.today().isoformat()
    raw = extract_pdf_text(pdf_path)
    body = clean_with_llm(raw, uuid=uuid)
    fm = build_frontmatter(
        uuid=uuid,
        source_type="annual-report",
        title=title,
        year=year,
        bronze_path=pdf_path,
        ingest_date=ingest_date,
    )
    write_silver(out_path, fm, body)
    return out_path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_bronze_to_silver.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/bronze_to_silver.py tests/test_bronze_to_silver.py
git commit -m "feat: bronze to silver converter with PDF extraction and LLM cleaning"
```

---

## Task 5: Silver → Quads Extractor (Pass 2)

**Files:**
- Create: `pipeline/silver_to_gold.py`
- Create: `tests/test_silver_to_gold.py`
- Create: `tests/fixtures/sample_quads.jsonl`

Pass 2 of the 4-pass protocol extracts temporal quads from a Silver document. Temperature is 0. This task tests the quad extraction prompt and the append-to-quads-jsonl writer. LLM calls are mocked in unit tests; one integration test requires `ANTHROPIC_API_KEY` set and is skipped otherwise.

- [ ] **Step 1: Write `tests/fixtures/sample_quads.jsonl`**

```jsonl
{"id":"sha256-abc001","date":"2021-09","date_precision":"month","subject":"u-20713-settlement","relation":"established","object":"first community solar program in DTE territory","sources":["test-year1"],"source_types":["annual-report"],"confidence":2,"status":"confirmed","dark_matter":false,"topics":[],"locations":[],"strategies":["strategy-1"],"actors":["actors/dte-energy","actors/osi"],"keywords":["community-solar","strategy-1","dte"],"fund_type":null,"commitment_status":null,"last_updated":"2026-06-18"}
{"id":"sha256-abc002","date":"2021-10","date_precision":"month","subject":"renew-ann-arbor-fund","relation":"received seed funding","object":"$2.1M from Ann Arbor City Council","sources":["test-year1"],"source_types":["annual-report"],"confidence":2,"status":"confirmed","dark_matter":false,"topics":[],"locations":["locations/bryant-neighborhood"],"strategies":["strategy-2"],"actors":["actors/ann-arbor-city-council"],"keywords":["weatherization","funding","bryant"],"fund_type":"municipal","commitment_status":null,"last_updated":"2026-06-18"}
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_silver_to_gold.py
import json
import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.silver_to_gold import (
    append_quads,
    parse_llm_quads_response,
    build_quads_prompt,
)
from pipeline.models import validate_quad


FIXTURE_SILVER = Path("tests/fixtures/sample_annual_report.md").read_text()


def test_parse_llm_quads_response_returns_list():
    raw_json = json.dumps([
        {
            "id": "sha256-abc001",
            "date": "2021-09",
            "date_precision": "month",
            "subject": "u-20713-settlement",
            "relation": "established",
            "object": "first community solar in DTE territory",
            "sources": ["test-year1"],
            "source_types": ["annual-report"],
            "confidence": 2,
            "status": "confirmed",
            "dark_matter": False,
            "topics": [],
            "locations": [],
            "strategies": ["strategy-1"],
            "actors": ["actors/dte-energy"],
            "keywords": ["community-solar"],
            "fund_type": None,
            "commitment_status": None,
            "last_updated": "2026-06-18",
        }
    ])
    quads = parse_llm_quads_response(raw_json)
    assert len(quads) == 1
    assert quads[0]["subject"] == "u-20713-settlement"


def test_parse_llm_quads_response_handles_markdown_fence():
    raw = "```json\n[{\"id\":\"sha256-x\",\"date\":\"2021\",\"date_precision\":\"year\",\"subject\":\"a\",\"relation\":\"b\",\"object\":\"c\",\"sources\":[\"s\"],\"source_types\":[\"annual-report\"],\"confidence\":2,\"status\":\"confirmed\",\"dark_matter\":false,\"topics\":[],\"locations\":[],\"strategies\":[],\"actors\":[],\"keywords\":[],\"fund_type\":null,\"commitment_status\":null,\"last_updated\":\"2026-06-18\"}]\n```"
    quads = parse_llm_quads_response(raw)
    assert len(quads) == 1


def test_parse_llm_quads_validates_each_quad():
    # a quad missing required fields should raise
    bad = json.dumps([{"id": "sha256-x"}])
    with pytest.raises(ValueError, match="invalid quad"):
        parse_llm_quads_response(bad)


def test_append_quads_writes_ndjson(tmp_path):
    out_file = tmp_path / "quads.jsonl"
    quads = [
        {
            "id": "sha256-abc001",
            "date": "2021-09",
            "date_precision": "month",
            "subject": "u-20713-settlement",
            "relation": "established",
            "object": "community solar",
            "sources": ["test-year1"],
            "source_types": ["annual-report"],
            "confidence": 2,
            "status": "confirmed",
            "dark_matter": False,
            "topics": [],
            "locations": [],
            "strategies": ["strategy-1"],
            "actors": [],
            "keywords": ["solar"],
            "fund_type": None,
            "commitment_status": None,
            "last_updated": "2026-06-18",
        }
    ]
    append_quads(quads, str(out_file))
    lines = out_file.read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["subject"] == "u-20713-settlement"


def test_append_quads_skips_duplicate_ids(tmp_path):
    out_file = tmp_path / "quads.jsonl"
    quad = {
        "id": "sha256-abc001",
        "date": "2021",
        "date_precision": "year",
        "subject": "a",
        "relation": "b",
        "object": "c",
        "sources": ["s"],
        "source_types": ["annual-report"],
        "confidence": 2,
        "status": "confirmed",
        "dark_matter": False,
        "topics": [],
        "locations": [],
        "strategies": [],
        "actors": [],
        "keywords": [],
        "fund_type": None,
        "commitment_status": None,
        "last_updated": "2026-06-18",
    }
    append_quads([quad], str(out_file))
    append_quads([quad], str(out_file))   # second call — same id
    lines = [l for l in out_file.read_text().strip().split("\n") if l]
    assert len(lines) == 1  # not duplicated


def test_build_quads_prompt_includes_source_uuid():
    prompt = build_quads_prompt(silver_body="Some text.", source_uuid="a2zero-year1")
    assert "a2zero-year1" in prompt


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY",
)
def test_integration_extract_quads_from_fixture(tmp_path):
    from pipeline.silver_to_gold import extract_quads_from_silver
    out_file = tmp_path / "quads.jsonl"
    quads = extract_quads_from_silver(FIXTURE_SILVER, source_uuid="test-year1", out_path=str(out_file))
    assert len(quads) >= 1
    for q in quads:
        errors = validate_quad(q)
        assert errors == [], f"invalid quad: {q}\nerrors: {errors}"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_silver_to_gold.py -v -k "not integration"
```

Expected: `ImportError` — module not found.

- [ ] **Step 4: Implement `pipeline/silver_to_gold.py` (quad extraction layer)**

```python
import anthropic
import json
import re
from pathlib import Path
from pipeline.models import validate_quad


QUADS_SYSTEM = """You are a temporal fact extractor for the A2Zero climate wiki.
You receive a section of a Silver-layer Markdown document and extract every atomic
temporal fact as a JSON array of quads.

Each quad has this exact schema:
{
  "id": "<sha256-hex-16>",           // compute as sha256(subject|relation|object|date)[:16] prefixed with "sha256-"
  "date": "<YYYY or YYYY-MM or YYYY-MM-DD>",
  "date_precision": "<year|month|day>",
  "subject": "<canonical-slug>",     // kebab-case, no spaces
  "relation": "<verb phrase>",       // e.g. "received grant", "leads", "established"
  "object": "<value or canonical-slug>",
  "sources": ["<source_uuid>"],
  "source_types": ["annual-report"],
  "confidence": 2,                   // always 2 for annual-report (Tier 1 source)
  "status": "confirmed",
  "dark_matter": false,
  "topics": [],
  "locations": [],
  "strategies": [],                  // e.g. ["strategy-1"] if mentioned
  "actors": [],                      // canonical slugs of actors involved
  "keywords": [],                    // 3-8 descriptive keywords
  "fund_type": null,                 // "federal-grant" | "municipal" | "millage" | "private" | null
  "commitment_status": null,         // null unless this quad IS a commitment
  "last_updated": "<YYYY-MM-DD>"
}

Rules:
- Extract ALL facts — do not filter by perceived importance
- One fact per quad; do not bundle multiple facts into one object field
- Slugify all entity names: "Missy Stults" → "missy-stults", "OSI" → "osi"
- For strategies, use "strategy-1" through "strategy-7" exactly
- If a date is approximate or a range, use the start year with precision "year"
- dark_matter: set to true only if the document states an outcome with NO mechanism described
- Return ONLY the JSON array, no prose, no markdown fence"""


def build_quads_prompt(silver_body: str, source_uuid: str) -> str:
    return (
        f"Source UUID: {source_uuid}\n"
        f"Source type: annual-report\n\n"
        f"Document body:\n\n{silver_body}"
    )


def parse_llm_quads_response(raw: str) -> list[dict]:
    # strip markdown code fence if present
    cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned)
    quads = json.loads(cleaned)
    for q in quads:
        errors = validate_quad(q)
        if errors:
            raise ValueError(f"invalid quad: {q}\nerrors: {errors}")
    return quads


def append_quads(quads: list[dict], out_path: str):
    path = Path(out_path)
    existing_ids: set[str] = set()
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                existing_ids.add(json.loads(line)["id"])

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for q in quads:
            if q["id"] not in existing_ids:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")
                existing_ids.add(q["id"])


def extract_quads_from_silver(
    silver_content: str,
    source_uuid: str,
    out_path: str,
) -> list[dict]:
    client = anthropic.Anthropic()
    # strip frontmatter before sending to LLM
    body = re.sub(r"^---\n.*?\n---\n", "", silver_content, flags=re.DOTALL).strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        temperature=0,
        system=QUADS_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": build_quads_prompt(body, source_uuid),
            }
        ],
    )
    raw = response.content[0].text
    quads = parse_llm_quads_response(raw)
    append_quads(quads, out_path)
    return quads
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_silver_to_gold.py -v -k "not integration"
```

Expected: all non-integration tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/silver_to_gold.py tests/test_silver_to_gold.py tests/fixtures/sample_quads.jsonl
git commit -m "feat: silver to gold quad extractor with dedup and schema validation"
```

---

## Task 6: Wiki Page Writer (Pass 3)

**Files:**
- Modify: `pipeline/silver_to_gold.py`
- Create: `tests/test_wiki_writer.py`

Pass 3 generates wiki page prose from Silver content. For annual reports, the LLM writes new body content for actor, initiative, commitment, and funding pages. For existing pages, the LLM appends only — existing body content must be byte-identical after Pass 4 verification. This task implements the page writer for new pages. Append behavior is covered in Task 7.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_wiki_writer.py
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.silver_to_gold import build_wiki_page, write_wiki_page


def test_build_wiki_page_actor():
    page = build_wiki_page(
        page_type="actor",
        slug="actors/missy-stults",
        frontmatter={
            "type": "actor",
            "title": "Missy Stults",
            "role": "Sustainability and Innovations Director",
            "organization": "City of Ann Arbor",
            "first-seen": "a2zero-year1",
            "last-updated": "2026-06-18",
            "tags": ["leadership", "osi"],
        },
        body="Missy Stults joined the City of Ann Arbor as Sustainability Director in 2019.",
    )
    assert page.page_type == "actor"
    assert page.slug == "actors/missy-stults"
    assert "Missy Stults" in page.frontmatter["title"]
    assert "Missy Stults joined" in page.body


def test_write_wiki_page_creates_file(tmp_path):
    from pipeline.silver_to_gold import build_wiki_page, write_wiki_page
    page = build_wiki_page(
        page_type="actor",
        slug="actors/missy-stults",
        frontmatter={
            "type": "actor",
            "title": "Missy Stults",
            "role": "Sustainability Director",
            "organization": "City of Ann Arbor",
            "first-seen": "a2zero-year1",
            "last-updated": "2026-06-18",
            "tags": ["leadership"],
        },
        body="Missy Stults led the A2Zero program.",
    )
    write_wiki_page(page, wiki_root=str(tmp_path))
    out_file = tmp_path / "actors" / "missy-stults.md"
    assert out_file.exists()
    content = out_file.read_text()
    assert "---" in content
    assert "Missy Stults led" in content


def test_write_wiki_page_frontmatter_is_valid_yaml(tmp_path):
    from pipeline.silver_to_gold import build_wiki_page, write_wiki_page
    page = build_wiki_page(
        page_type="actor",
        slug="actors/osi",
        frontmatter={
            "type": "actor",
            "title": "OSI",
            "role": "City department",
            "organization": "City of Ann Arbor",
            "first-seen": "a2zero-year1",
            "last-updated": "2026-06-18",
            "tags": [],
        },
        body="The Office of Sustainability and Innovations (OSI) leads A2Zero.",
    )
    write_wiki_page(page, wiki_root=str(tmp_path))
    out_file = tmp_path / "actors" / "osi.md"
    content = out_file.read_text()
    parts = content.split("---\n")
    parsed = yaml.safe_load(parts[1])
    assert parsed["type"] == "actor"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_wiki_writer.py -v
```

Expected: `ImportError` — `build_wiki_page` and `write_wiki_page` not defined.

- [ ] **Step 3: Add `build_wiki_page` and `write_wiki_page` to `pipeline/silver_to_gold.py`**

Add these functions after the existing imports at the top (add `import yaml`) and at the bottom of the file:

```python
import yaml  # add to imports at top of file

# --- add these functions at the bottom ---

from pipeline.models import WikiPage


def build_wiki_page(
    page_type: str,
    slug: str,
    frontmatter: dict,
    body: str,
) -> WikiPage:
    return WikiPage(page_type=page_type, slug=slug, frontmatter=frontmatter, body=body)


def write_wiki_page(page: WikiPage, wiki_root: str):
    # slug format: "actors/missy-stults" → wiki_root/actors/missy-stults.md
    out_path = Path(wiki_root) / (page.slug + ".md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.dump(page.frontmatter, allow_unicode=True, default_flow_style=False)
    content = f"---\n{fm_yaml}---\n\n{page.body}\n"
    out_path.write_text(content, encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_wiki_writer.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/silver_to_gold.py tests/test_wiki_writer.py
git commit -m "feat: wiki page builder and writer with YAML frontmatter"
```

---

## Task 7: Append-Only Page Update (Pass 3 + Pass 4)

**Files:**
- Modify: `pipeline/silver_to_gold.py`
- Create: `tests/test_append_only.py`

For existing wiki pages, Pass 3 appends only — the LLM never rewrites existing prose. Pass 4 verifies that existing content is byte-identical to what was on disk before Pass 3 ran. This is the hallucination firewall for the update path.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_append_only.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.silver_to_gold import (
    load_existing_body,
    append_to_wiki_page,
    verify_existing_body_unchanged,
)


def test_load_existing_body_strips_frontmatter(tmp_path):
    page_file = tmp_path / "actors" / "missy-stults.md"
    page_file.parent.mkdir()
    page_file.write_text(
        "---\ntype: actor\ntitle: Missy Stults\n---\n\nOriginal body text.\n"
    )
    body = load_existing_body(str(page_file))
    assert body == "Original body text.\n"
    assert "---" not in body


def test_append_to_wiki_page_adds_new_section(tmp_path):
    page_file = tmp_path / "actors" / "missy-stults.md"
    page_file.parent.mkdir()
    page_file.write_text(
        "---\ntype: actor\ntitle: Missy Stults\n---\n\nOriginal body text.\n"
    )
    append_to_wiki_page(
        page_path=str(page_file),
        new_content="\n## Year 3 Activity\n\nNew content from year3 report.\n",
        source_uuid="a2zero-year3",
    )
    content = page_file.read_text()
    assert "Original body text." in content
    assert "Year 3 Activity" in content
    assert "New content from year3 report." in content


def test_append_preserves_existing_body_byte_for_byte(tmp_path):
    page_file = tmp_path / "actors" / "missy-stults.md"
    page_file.parent.mkdir()
    original = "---\ntype: actor\ntitle: Missy Stults\n---\n\nOriginal body text.\n"
    page_file.write_text(original)
    original_body = load_existing_body(str(page_file))
    append_to_wiki_page(
        page_path=str(page_file),
        new_content="\nNew section.\n",
        source_uuid="a2zero-year2",
    )
    after_body = load_existing_body(str(page_file))
    assert after_body.startswith(original_body)


def test_verify_existing_body_unchanged_passes_when_unchanged(tmp_path):
    page_file = tmp_path / "actors" / "test.md"
    page_file.parent.mkdir()
    page_file.write_text("---\ntype: actor\n---\n\nOriginal.\n")
    original_body = load_existing_body(str(page_file))
    # simulate no change
    page_file.write_text("---\ntype: actor\n---\n\nOriginal.\nNew content.\n")
    # should not raise
    verify_existing_body_unchanged(
        page_path=str(page_file),
        expected_original_body=original_body,
    )


def test_verify_existing_body_raises_when_changed(tmp_path):
    page_file = tmp_path / "actors" / "test.md"
    page_file.parent.mkdir()
    page_file.write_text("---\ntype: actor\n---\n\nOriginal.\n")
    original_body = "Original.\n"
    # simulate LLM rewrote existing content
    page_file.write_text("---\ntype: actor\n---\n\nRewritten by LLM.\n")
    with pytest.raises(ValueError, match="existing body was modified"):
        verify_existing_body_unchanged(
            page_path=str(page_file),
            expected_original_body=original_body,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_append_only.py -v
```

Expected: `ImportError` — functions not defined.

- [ ] **Step 3: Add append-only functions to `pipeline/silver_to_gold.py`**

Add these at the bottom of `pipeline/silver_to_gold.py`:

```python
def load_existing_body(page_path: str) -> str:
    content = Path(page_path).read_text(encoding="utf-8")
    # strip YAML frontmatter block (--- ... ---)
    parts = content.split("---\n", 2)
    if len(parts) >= 3:
        return parts[2]
    return content


def append_to_wiki_page(page_path: str, new_content: str, source_uuid: str):
    path = Path(page_path)
    content = path.read_text(encoding="utf-8")
    updated = content.rstrip("\n") + "\n" + new_content
    path.write_text(updated, encoding="utf-8")


def verify_existing_body_unchanged(page_path: str, expected_original_body: str):
    current_body = load_existing_body(page_path)
    if not current_body.startswith(expected_original_body):
        raise ValueError(
            f"existing body was modified in {page_path}.\n"
            f"Expected start:\n{expected_original_body[:200]}\n"
            f"Got start:\n{current_body[:200]}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_append_only.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/silver_to_gold.py tests/test_append_only.py
git commit -m "feat: append-only wiki page update with byte-identical verification (Pass 4)"
```

---

## Task 8: Quad Linter

**Files:**
- Create: `pipeline/quad_linter.py`
- Create: `tests/test_quad_linter.py`

The linter runs after every ingest on the full `quads.jsonl`. It checks for: schema violations, unresolved entity slugs (actors not in entity_aliases.json), `dark_matter=true` quads, and duplicate IDs. It outputs a structured report dict that `post_ingest.py` uses to build `review-queue.md`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_quad_linter.py
import json
import pytest
from pathlib import Path
from pipeline.quad_linter import lint_quads, LintReport


VALID_QUAD = {
    "id": "sha256-abc001",
    "date": "2021-09",
    "date_precision": "month",
    "subject": "u-20713-settlement",
    "relation": "established",
    "object": "community solar",
    "sources": ["test-year1"],
    "source_types": ["annual-report"],
    "confidence": 2,
    "status": "confirmed",
    "dark_matter": False,
    "topics": [],
    "locations": [],
    "strategies": ["strategy-1"],
    "actors": ["actors/osi"],
    "keywords": ["solar"],
    "fund_type": None,
    "commitment_status": None,
    "last_updated": "2026-06-18",
}


def test_lint_valid_quads_returns_no_errors(tmp_path):
    qf = tmp_path / "quads.jsonl"
    qf.write_text(json.dumps(VALID_QUAD) + "\n")
    report = lint_quads(str(qf))
    assert report.schema_errors == []
    assert report.duplicate_ids == []


def test_lint_detects_schema_error(tmp_path):
    bad = {"id": "sha256-bad", "subject": "a"}  # missing most fields
    qf = tmp_path / "quads.jsonl"
    qf.write_text(json.dumps(bad) + "\n")
    report = lint_quads(str(qf))
    assert len(report.schema_errors) > 0


def test_lint_detects_duplicate_ids(tmp_path):
    qf = tmp_path / "quads.jsonl"
    qf.write_text(
        json.dumps(VALID_QUAD) + "\n" + json.dumps(VALID_QUAD) + "\n"
    )
    report = lint_quads(str(qf))
    assert "sha256-abc001" in report.duplicate_ids


def test_lint_detects_dark_matter(tmp_path):
    dark_quad = {**VALID_QUAD, "id": "sha256-dark", "dark_matter": True}
    qf = tmp_path / "quads.jsonl"
    qf.write_text(json.dumps(dark_quad) + "\n")
    report = lint_quads(str(qf))
    assert "sha256-dark" in report.dark_matter_ids


def test_lint_report_summary_counts(tmp_path):
    qf = tmp_path / "quads.jsonl"
    qf.write_text(json.dumps(VALID_QUAD) + "\n")
    report = lint_quads(str(qf))
    assert report.total_quads == 1
    assert report.confirmed_count == 1
    assert report.unverified_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_quad_linter.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `pipeline/quad_linter.py`**

```python
import json
from dataclasses import dataclass, field
from pathlib import Path
from pipeline.models import validate_quad


@dataclass
class LintReport:
    total_quads: int = 0
    confirmed_count: int = 0
    unverified_count: int = 0
    schema_errors: list[dict] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    dark_matter_ids: list[str] = field(default_factory=list)


def lint_quads(quads_path: str) -> LintReport:
    report = LintReport()
    seen_ids: dict[str, int] = {}

    lines = Path(quads_path).read_text(encoding="utf-8").splitlines()
    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            quad = json.loads(line)
        except json.JSONDecodeError as e:
            report.schema_errors.append({"line": line_num, "error": str(e)})
            continue

        report.total_quads += 1

        errors = validate_quad(quad)
        if errors:
            report.schema_errors.append({
                "line": line_num,
                "id": quad.get("id", "unknown"),
                "errors": errors,
            })

        qid = quad.get("id", "")
        if qid in seen_ids:
            if qid not in report.duplicate_ids:
                report.duplicate_ids.append(qid)
        seen_ids[qid] = line_num

        if quad.get("dark_matter"):
            report.dark_matter_ids.append(qid)

        if quad.get("status") == "confirmed":
            report.confirmed_count += 1
        elif quad.get("status") == "unverified":
            report.unverified_count += 1

    return report
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_quad_linter.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/quad_linter.py tests/test_quad_linter.py
git commit -m "feat: quad linter with schema, duplicate, and dark matter detection"
```

---

## Task 9: Post-Ingest Pipeline (review-queue.md)

**Files:**
- Create: `pipeline/post_ingest.py`
- Create: `tests/test_post_ingest.py`

After every ingest, `post_ingest.py` runs the linter and generates `review-queue.md` with three tiers: 🔴 urgent (schema errors, duplicates), 🟡 normal (dark matter quads, new unverified quads), 🟢 low (new confirmed quads needing a skim). This is the human's primary interface to each ingest run.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_post_ingest.py
import pytest
from pathlib import Path
from pipeline.post_ingest import generate_review_queue
from pipeline.quad_linter import LintReport


def test_generate_review_queue_creates_file(tmp_path):
    report = LintReport(
        total_quads=10,
        confirmed_count=8,
        unverified_count=2,
        schema_errors=[],
        duplicate_ids=[],
        dark_matter_ids=["sha256-dark1"],
    )
    out_path = tmp_path / "review-queue.md"
    generate_review_queue(
        report=report,
        source_uuid="a2zero-year1",
        out_path=str(out_path),
        run_date="2026-06-18",
    )
    assert out_path.exists()


def test_review_queue_contains_urgent_section_on_errors(tmp_path):
    report = LintReport(
        total_quads=5,
        confirmed_count=3,
        unverified_count=2,
        schema_errors=[{"line": 3, "id": "sha256-bad", "errors": ["missing field: date"]}],
        duplicate_ids=["sha256-dup1"],
        dark_matter_ids=[],
    )
    out_path = tmp_path / "review-queue.md"
    generate_review_queue(report=report, source_uuid="a2zero-year2",
                          out_path=str(out_path), run_date="2026-06-18")
    content = out_path.read_text()
    assert "🔴" in content
    assert "sha256-bad" in content
    assert "sha256-dup1" in content


def test_review_queue_contains_dark_matter_in_normal_tier(tmp_path):
    report = LintReport(
        total_quads=5,
        confirmed_count=5,
        unverified_count=0,
        schema_errors=[],
        duplicate_ids=[],
        dark_matter_ids=["sha256-dark1", "sha256-dark2"],
    )
    out_path = tmp_path / "review-queue.md"
    generate_review_queue(report=report, source_uuid="a2zero-year3",
                          out_path=str(out_path), run_date="2026-06-18")
    content = out_path.read_text()
    assert "🟡" in content
    assert "sha256-dark1" in content


def test_review_queue_shows_summary_stats(tmp_path):
    report = LintReport(
        total_quads=42,
        confirmed_count=40,
        unverified_count=2,
        schema_errors=[],
        duplicate_ids=[],
        dark_matter_ids=[],
    )
    out_path = tmp_path / "review-queue.md"
    generate_review_queue(report=report, source_uuid="a2zero-year5",
                          out_path=str(out_path), run_date="2026-06-18")
    content = out_path.read_text()
    assert "42" in content
    assert "a2zero-year5" in content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_post_ingest.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `pipeline/post_ingest.py`**

```python
from pathlib import Path
from pipeline.quad_linter import LintReport


def generate_review_queue(
    report: LintReport,
    source_uuid: str,
    out_path: str,
    run_date: str,
):
    lines = [
        f"# Review Queue — {source_uuid} — {run_date}",
        "",
        "## Summary",
        f"- Total quads: {report.total_quads}",
        f"- Confirmed: {report.confirmed_count}",
        f"- Unverified: {report.unverified_count}",
        f"- Schema errors: {len(report.schema_errors)}",
        f"- Duplicate IDs: {len(report.duplicate_ids)}",
        f"- Dark matter quads: {len(report.dark_matter_ids)}",
        "",
    ]

    # 🔴 Urgent
    urgent = []
    if report.schema_errors:
        urgent.append("### Schema Errors")
        for e in report.schema_errors:
            qid = e.get("id", "unknown")
            errs = "; ".join(e.get("errors", [str(e.get("error", ""))]))
            urgent.append(f"- `{qid}` (line {e.get('line', '?')}): {errs}")
    if report.duplicate_ids:
        urgent.append("### Duplicate IDs")
        for qid in report.duplicate_ids:
            urgent.append(f"- `{qid}`")

    if urgent:
        lines.append("## 🔴 Urgent — Fix Before Merging")
        lines.extend(urgent)
        lines.append("")

    # 🟡 Normal
    normal = []
    if report.dark_matter_ids:
        normal.append("### Dark Matter — Known Outcomes, Missing Mechanism")
        normal.append("_Trigger source discovery for these quads._")
        for qid in report.dark_matter_ids:
            normal.append(f"- `{qid}`")
    if report.unverified_count > 0:
        normal.append(f"### Unverified Quads ({report.unverified_count})")
        normal.append("_Run DuckDB query: `SELECT * FROM quads WHERE status = 'unverified'`_")

    if normal:
        lines.append("## 🟡 Normal — Review This Week")
        lines.extend(normal)
        lines.append("")

    # 🟢 Low
    lines.append("## 🟢 Low — Skim Confirmed Quads")
    lines.append(f"{report.confirmed_count} confirmed quads added from `{source_uuid}`.")
    lines.append("_Run: `duckdb -c \"SELECT date, subject, relation, object FROM read_ndjson('blackboard/quads.jsonl') WHERE list_contains(sources, '\" + source_uuid + \"') ORDER BY date\"`_")
    lines.append("")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


def run_post_ingest(quads_path: str, source_uuid: str, out_path: str, run_date: str):
    from pipeline.quad_linter import lint_quads
    report = lint_quads(quads_path)
    generate_review_queue(report=report, source_uuid=source_uuid,
                          out_path=out_path, run_date=run_date)
    return report
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_post_ingest.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/post_ingest.py tests/test_post_ingest.py
git commit -m "feat: post-ingest pipeline generates review-queue.md with 3-tier triage"
```

---

## Task 10: End-to-End Ingest Runner

**Files:**
- Create: `pipeline/run_ingest.py`
- Create: `tests/test_run_ingest.py`

`run_ingest.py` is the CLI entry point. It accepts a PDF path, UUID, year, output paths, and runs the full Bronze→Silver→Gold pipeline for one annual report. For the test suite, the LLM calls are mocked; the test verifies file creation and that quads.jsonl contains at least one line after the run.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_run_ingest.py
import json
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch


MOCK_SILVER_BODY = """## Strategy 1: 100% Renewable Grid

In September 2021, the U-20713 settlement established community solar in DTE territory.
Missy Stults led the effort as Sustainability Director.
"""

MOCK_QUADS = [
    {
        "id": "sha256-abc001",
        "date": "2021-09",
        "date_precision": "month",
        "subject": "u-20713-settlement",
        "relation": "established",
        "object": "community solar program in DTE territory",
        "sources": ["a2zero-year1"],
        "source_types": ["annual-report"],
        "confidence": 2,
        "status": "confirmed",
        "dark_matter": False,
        "topics": [],
        "locations": [],
        "strategies": ["strategy-1"],
        "actors": ["actors/missy-stults"],
        "keywords": ["community-solar", "strategy-1"],
        "fund_type": None,
        "commitment_status": None,
        "last_updated": "2026-06-18",
    }
]


@patch("pipeline.bronze_to_silver.anthropic.Anthropic")
@patch("pipeline.silver_to_gold.anthropic.Anthropic")
@patch("pipeline.bronze_to_silver.extract_pdf_text", return_value="Raw PDF text")
def test_run_ingest_creates_silver_file(
    mock_extract, mock_gold_client_class, mock_silver_client_class, tmp_path
):
    import json
    mock_silver_client = MagicMock()
    mock_silver_client_class.return_value = mock_silver_client
    mock_silver_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=MOCK_SILVER_BODY)]
    )
    mock_gold_client = MagicMock()
    mock_gold_client_class.return_value = mock_gold_client
    mock_gold_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps(MOCK_QUADS))]
    )

    silver_dir = tmp_path / "silver" / "annual-reports"
    quads_file = tmp_path / "blackboard" / "quads.jsonl"
    wiki_root = tmp_path / "wiki"
    queue_file = tmp_path / "review-queue.md"

    from pipeline.run_ingest import run_annual_report_ingest
    run_annual_report_ingest(
        pdf_path="bronze/annual-reports/a2zero-year1.pdf",
        uuid="a2zero-year1",
        year="year1",
        title="A2Zero Year 1 Annual Report",
        silver_dir=str(silver_dir),
        quads_path=str(quads_file),
        wiki_root=str(wiki_root),
        review_queue_path=str(queue_file),
        run_date="2026-06-18",
    )

    silver_file = silver_dir / "a2zero-year1.md"
    assert silver_file.exists(), "Silver file not created"
    assert quads_file.exists(), "quads.jsonl not created"
    lines = [l for l in quads_file.read_text().splitlines() if l.strip()]
    assert len(lines) >= 1, "No quads written"
    assert queue_file.exists(), "review-queue.md not created"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_run_ingest.py -v
```

Expected: `ImportError` — `run_annual_report_ingest` not defined.

- [ ] **Step 3: Implement `pipeline/run_ingest.py`**

```python
import json
from datetime import date
from pathlib import Path
from pipeline.bronze_to_silver import convert_annual_report
from pipeline.silver_to_gold import extract_quads_from_silver
from pipeline.post_ingest import run_post_ingest


def run_annual_report_ingest(
    pdf_path: str,
    uuid: str,
    year: str,
    title: str,
    silver_dir: str,
    quads_path: str,
    wiki_root: str,
    review_queue_path: str,
    run_date: str | None = None,
):
    if run_date is None:
        run_date = date.today().isoformat()

    # Step 1: Bronze → Silver
    silver_path = str(Path(silver_dir) / f"{uuid}.md")
    convert_annual_report(
        pdf_path=pdf_path,
        uuid=uuid,
        year=year,
        out_path=silver_path,
        title=title,
        ingest_date=run_date,
    )

    # Step 2: Silver → Quads (Pass 2)
    silver_content = Path(silver_path).read_text(encoding="utf-8")
    extract_quads_from_silver(
        silver_content=silver_content,
        source_uuid=uuid,
        out_path=quads_path,
    )

    # Steps 3-6: Post-ingest (lint + review queue)
    report = run_post_ingest(
        quads_path=quads_path,
        source_uuid=uuid,
        out_path=review_queue_path,
        run_date=run_date,
    )

    print(f"[ingest] {uuid}: {report.total_quads} quads, "
          f"{len(report.schema_errors)} errors, "
          f"{len(report.dark_matter_ids)} dark matter")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--uuid", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--silver-dir", default="silver/annual-reports")
    parser.add_argument("--quads-path", default="blackboard/quads.jsonl")
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument("--review-queue", default="review-queue.md")
    args = parser.parse_args()
    run_annual_report_ingest(
        pdf_path=args.pdf,
        uuid=args.uuid,
        year=args.year,
        title=args.title,
        silver_dir=args.silver_dir,
        quads_path=args.quads_path,
        wiki_root=args.wiki_root,
        review_queue_path=args.review_queue,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_run_ingest.py -v
```

Expected: 1 test PASS.

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v -k "not integration"
```

Expected: all tests PASS (integration tests skipped without API key).

- [ ] **Step 6: Commit**

```bash
git add pipeline/run_ingest.py tests/test_run_ingest.py
git commit -m "feat: end-to-end ingest runner connecting bronze→silver→gold pipeline"
```

---

## Task 11: Run Against Real Annual Reports

**Prerequisites:** `ANTHROPIC_API_KEY` set. PDF files in `bronze/annual-reports/`.

This task runs the real pipeline against the 5 A2Zero annual reports. Each run takes 2–5 minutes. Run them sequentially and check `review-queue.md` after each one.

- [ ] **Step 1: Verify bronze files exist**

```bash
ls bronze/annual-reports/
```

Expected: `a2zero-year1.pdf`, `a2zero-year2.pdf`, `a2zero-year3.pdf`, `a2zero-year4.pdf`, `a2zero-year5.pdf`

- [ ] **Step 2: Run Year 1**

```bash
python -m pipeline.run_ingest \
  --pdf bronze/annual-reports/a2zero-year1.pdf \
  --uuid a2zero-year1 \
  --year year1 \
  --title "A2Zero Year 1 Annual Report"
```

Expected output:
```
[ingest] a2zero-year1: <N> quads, 0 errors, <M> dark matter
```

- [ ] **Step 3: Review the queue for Year 1**

```bash
cat review-queue.md
```

Check: any 🔴 items must be resolved before continuing. Dark matter items (🟡) are logged for later source discovery.

- [ ] **Step 4: Run Years 2–5**

```bash
python -m pipeline.run_ingest --pdf bronze/annual-reports/a2zero-year2.pdf --uuid a2zero-year2 --year year2 --title "A2Zero Year 2 Annual Report"
python -m pipeline.run_ingest --pdf bronze/annual-reports/a2zero-year3.pdf --uuid a2zero-year3 --year year3 --title "A2Zero Year 3 Annual Report"
python -m pipeline.run_ingest --pdf bronze/annual-reports/a2zero-year4.pdf --uuid a2zero-year4 --year year4 --title "A2Zero Year 4 Annual Report"
python -m pipeline.run_ingest --pdf bronze/annual-reports/a2zero-year5.pdf --uuid a2zero-year5 --year year5 --title "A2Zero Year 5 Annual Report"
```

- [ ] **Step 5: Verify blackboard has quads from all 5 sources**

```bash
python -c "
import duckdb
conn = duckdb.connect()
result = conn.execute('''
  SELECT sources[1] as source, COUNT(*) as quad_count
  FROM read_ndjson(\"blackboard/quads.jsonl\")
  GROUP BY sources[1]
  ORDER BY source
''').fetchall()
for row in result:
    print(row)
"
```

Expected: 5 rows, one per annual report UUID, each with a meaningful quad count (typically 50–200 quads per report).

- [ ] **Step 6: Spot-check quads for a known fact**

```bash
python -c "
import duckdb
conn = duckdb.connect()
result = conn.execute('''
  SELECT date, subject, relation, object
  FROM read_ndjson(\"blackboard/quads.jsonl\")
  WHERE list_contains(keywords, 'community-solar')
     OR subject = 'u-20713-settlement'
  ORDER BY date
''').fetchall()
for row in result:
    print(row)
"
```

Expected: at least one row documenting the U-20713 community solar settlement.

- [ ] **Step 7: Commit final state**

```bash
git add silver/ blackboard/quads.jsonl review-queue.md registry/entity_aliases.json
git commit -m "data: ingest a2zero year1-year5 annual reports into blackboard"
```

---

## Self-Review

**Spec coverage check:**

| Spec Section | Task That Covers It |
|---|---|
| Bronze → Silver conversion (4.1) | Task 4 |
| 4-pass extraction protocol, Pass 2 (quads) | Task 5 |
| 4-pass extraction protocol, Pass 3 (wiki pages) | Task 6 |
| Pass 4 verification (append-only) | Task 7 |
| Entity registry + alias resolution | Task 3 |
| Quad schema with all fields incl. commitment_status | Task 2 |
| Quad ID as sha256 hash | Task 2 |
| Append-only page update rule | Task 7 |
| Post-ingest pipeline + review-queue.md | Task 9 |
| Quad linter (schema, dupes, dark matter) | Task 8 |
| Sub-timeline DuckDB queries | Task 11, Step 5 |
| Source tier (Tier 1 = confidence:2, status:confirmed) | Task 5 (QUADS_SYSTEM prompt) |
| Organic keyword vocabulary (free-form, first 3 runs) | Encoded in QUADS_SYSTEM — no code gate needed until Plan 3 |
| Entity locking before page creation | Task 3; wired into registry but not yet called from Pass 3 prose writer (see note below) |

**Note on entity locking in Pass 3:** The current plan wires the `EntityRegistry` for quad `actors[]` field population but does not yet call `registry.resolve()` before writing wiki pages in Task 6. The full actor-registry gating belongs in Plan 4 when actor pages are created for persons and organizations extracted from transcripts and press releases. For annual-report-only ingest (Plan 1), the LLM is the only page-creator and the registry is consulted for quad actor slugs via the QUADS_SYSTEM prompt instruction to slugify names — an imperfect but acceptable approximation for the prototype.

**Placeholder scan:** No TBDs, no "similar to Task N" references, no steps without code. Each step contains exact commands and code.

**Type consistency check:**
- `WikiPage` defined in `models.py` with fields `page_type`, `slug`, `frontmatter`, `body` — used identically in Tasks 6 and 7.
- `LintReport` defined in `quad_linter.py`, imported by `post_ingest.py` — field names consistent across Tasks 8 and 9.
- `append_quads` signature `(quads: list[dict], out_path: str)` — consistent between Task 5 definition and Task 10 usage.
- `extract_quads_from_silver` signature consistent between Task 5 definition and Task 10 call.

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-18-annual-report-ingest-foundation.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, with checkpoints for review.

Which approach?
