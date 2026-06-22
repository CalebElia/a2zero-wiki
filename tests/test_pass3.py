import json
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch


SAMPLE_CHUNK = """
## Strategy 1: Power Our Electrical Grid with 100% Renewable Energy

### Implement Community Choice Aggregation

**Vision:** Community Choice Aggregation (CCA) allows the City of Ann Arbor to
procure renewable electricity on behalf of all residents and businesses, achieving
100% renewable grid power by 2025.

**Party Responsible for Implementation:** Office of Sustainability and Innovations (OSI)

**Collaborators:** DTE Energy, Michigan Public Service Commission

**Timeline and Initial Actions:** Launch CCA program by end of Year 1 (2021).
Partner with other municipalities to expand reach.

**Equity Impacts:** Low-income households receive bill credits; no opt-out required.

**Indicators of Success:** 100% renewable electricity for 90% of residents by 2025.
Total cost: $3,245,000. GHG reduction: 784,000 metric tons CO2e. Cost: $4/ton.
"""

MOCK_PAGES = [
    {
        "page_type": "commitment",
        "slug": "commitments/implement-community-choice-aggregation",
        "frontmatter": {
            "type": "commitment",
            "title": "Implement Community Choice Aggregation",
            "made-in": "cap-2020",
            "made-in-section": "CAP Actions",
            "target-year": "year1",
            "status": "unverified",
            "confidence": "high",
            "fulfilled-in": None,
            "fulfilled-evidence": None,
            "tags": ["cca", "renewable-energy", "strategy-1"],
            "source-first-seen": "cap-2020",
            "last-updated": "2026-06-22",
        },
        "body": "The A2Zero CAP commits to implementing Community Choice Aggregation (CCA), allowing the City to procure renewable electricity for all residents. Projected to reduce 784,000 metric tons CO2e annually at $4/ton.",
    },
    {
        "page_type": "actor",
        "slug": "actors/osi",
        "frontmatter": {
            "type": "actor",
            "title": "Office of Sustainability and Innovations",
            "role": "Lead implementer of A2Zero programs",
            "organization": "actors/city-of-ann-arbor",
            "first-seen": "cap-2020",
            "last-updated": "2026-06-22",
            "tags": ["osi", "city-staff", "leadership"],
        },
        "body": "The Office of Sustainability and Innovations (OSI) is the primary city department responsible for implementing A2Zero. OSI leads or co-leads the majority of the 44 actions across all seven strategies.",
    },
]


def test_parse_llm_pages_response_returns_list():
    from pipeline.pass3 import parse_llm_pages_response
    raw = json.dumps(MOCK_PAGES)
    pages = parse_llm_pages_response(raw)
    assert len(pages) == 2
    assert pages[0]["page_type"] == "commitment"


def test_parse_llm_pages_response_handles_markdown_fence():
    from pipeline.pass3 import parse_llm_pages_response
    raw = f"```json\n{json.dumps(MOCK_PAGES)}\n```"
    pages = parse_llm_pages_response(raw)
    assert len(pages) == 2


def test_parse_llm_pages_response_returns_empty_list():
    from pipeline.pass3 import parse_llm_pages_response
    pages = parse_llm_pages_response("[]")
    assert pages == []


def test_validate_page_spec_accepts_valid_commitment():
    from pipeline.pass3 import validate_page_spec
    errors = validate_page_spec(MOCK_PAGES[0])
    assert errors == []


def test_validate_page_spec_rejects_missing_fields():
    from pipeline.pass3 import validate_page_spec
    bad = {"page_type": "commitment"}
    errors = validate_page_spec(bad)
    assert any("slug" in e for e in errors)
    assert any("frontmatter" in e for e in errors)
    assert any("body" in e for e in errors)


def test_validate_page_spec_rejects_invalid_page_type():
    from pipeline.pass3 import validate_page_spec
    bad = {**MOCK_PAGES[0], "page_type": "unknown-type"}
    errors = validate_page_spec(bad)
    assert any("page_type" in e for e in errors)


def test_write_or_append_page_creates_new_file(tmp_path):
    from pipeline.pass3 import write_or_append_page
    write_or_append_page(MOCK_PAGES[0], wiki_root=str(tmp_path), source_uuid="cap-2020")
    out = tmp_path / "commitments" / "implement-community-choice-aggregation.md"
    assert out.exists()
    content = out.read_text()
    assert "Community Choice Aggregation" in content
    assert "---" in content  # has frontmatter


def test_write_or_append_page_appends_to_existing(tmp_path):
    from pipeline.pass3 import write_or_append_page
    # write initial page
    write_or_append_page(MOCK_PAGES[0], wiki_root=str(tmp_path), source_uuid="cap-2020")
    original_path = tmp_path / "commitments" / "implement-community-choice-aggregation.md"
    original_content = original_path.read_text()

    # append with new content
    updated_spec = {**MOCK_PAGES[0], "body": "Additional context from year1 report."}
    write_or_append_page(updated_spec, wiki_root=str(tmp_path), source_uuid="a2zero-year1")

    new_content = original_path.read_text()
    assert "commits to implementing" in new_content   # original preserved
    assert "Additional context from year1" in new_content  # new content added
    assert new_content.startswith(original_content[:50])  # frontmatter unchanged


def test_write_or_append_page_frontmatter_is_valid_yaml(tmp_path):
    from pipeline.pass3 import write_or_append_page
    write_or_append_page(MOCK_PAGES[1], wiki_root=str(tmp_path), source_uuid="cap-2020")
    out = tmp_path / "actors" / "osi.md"
    content = out.read_text()
    parts = content.split("---\n")
    parsed = yaml.safe_load(parts[1])
    assert parsed["type"] == "actor"


@patch("pipeline.pass3.anthropic.Anthropic")
def test_extract_wiki_pages_from_chunk_calls_llm(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps(MOCK_PAGES))]
    )
    from pipeline.pass3 import extract_wiki_pages_from_chunk
    pages = extract_wiki_pages_from_chunk(
        chunk_text=SAMPLE_CHUNK,
        source_uuid="cap-2020",
        context_header="[DOCUMENT CONTEXT]\nDocument: Test CAP\n[END CONTEXT]",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-22",
    )
    assert mock_client.messages.create.called
    assert len(pages) == 2
    # files should be written to disk
    assert (tmp_path / "commitments" / "implement-community-choice-aggregation.md").exists()
    assert (tmp_path / "actors" / "osi.md").exists()


@patch("pipeline.pass3.anthropic.Anthropic")
def test_extract_wiki_pages_from_chunk_handles_llm_failure(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API error")
    from pipeline.pass3 import extract_wiki_pages_from_chunk
    # should warn and return empty list, not crash
    pages = extract_wiki_pages_from_chunk(
        chunk_text=SAMPLE_CHUNK,
        source_uuid="cap-2020",
        context_header="",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-22",
    )
    assert pages == []
