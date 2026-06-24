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
        "page_type": "initiative",
        "slug": "initiatives/community-choice-aggregation",
        "frontmatter": {
            "type": "initiative",
            "title": "Community Choice Aggregation",
            "parent-strategy": "[[strategies/strategy-1-renewable-grid]]",
            "related-strategies": [],
            "party-responsible": "[[actors/osi]]",
            "partners": [],
            "status": "committed",
            "launched": None,
            "locations": [],
            "funding-events": [],
            "milestones": [
                {
                    "year": 2027,
                    "target": "CCA program launched",
                    "status": "unverified",
                    "source": "[[sources/cap/cap-2020]]",
                }
            ],
            "tags": ["cca", "renewable-energy", "strategy-1"],
            "source-first-seen": "[[sources/cap/cap-2020]]",
            "last-updated": "2026-06-23",
        },
        "body": "Community Choice Aggregation allows Ann Arbor to procure renewable electricity for all residents. ([[sources/cap/cap-2020|cap-2020]])",
    },
    {
        "page_type": "actor",
        "slug": "actors/osi",
        "frontmatter": {
            "type": "actor",
            "title": "Office of Sustainability and Innovations",
            "actor-type": "government-office",
            "role": "Lead implementer of A2Zero programs",
            "affiliation": "[[actors/city-of-ann-arbor]]",
            "elected": None,
            "active-years": [2020],
            "programs-involved": ["[[initiatives/community-choice-aggregation]]"],
            "tags": ["osi", "city-staff", "leadership"],
            "source-first-seen": "[[sources/cap/cap-2020]]",
            "last-updated": "2026-06-23",
        },
        "body": "OSI is the primary city department responsible for implementing A2Zero. ([[sources/cap/cap-2020|cap-2020]])",
    },
]


def test_parse_llm_pages_response_returns_list():
    from pipeline.wiki_writer import parse_llm_pages_response
    raw = json.dumps(MOCK_PAGES)
    pages = parse_llm_pages_response(raw)
    assert len(pages) == 2
    assert pages[0]["page_type"] == "initiative"


def test_parse_llm_pages_response_handles_markdown_fence():
    from pipeline.wiki_writer import parse_llm_pages_response
    raw = f"```json\n{json.dumps(MOCK_PAGES)}\n```"
    pages = parse_llm_pages_response(raw)
    assert len(pages) == 2


def test_parse_llm_pages_response_returns_empty_list():
    from pipeline.wiki_writer import parse_llm_pages_response
    pages = parse_llm_pages_response("[]")
    assert pages == []


def test_validate_page_spec_accepts_valid_initiative():
    from pipeline.wiki_writer import validate_page_spec
    errors = validate_page_spec(MOCK_PAGES[0])
    assert errors == []


def test_validate_page_spec_rejects_missing_fields():
    from pipeline.wiki_writer import validate_page_spec
    bad = {"page_type": "initiative"}
    errors = validate_page_spec(bad)
    assert any("slug" in e for e in errors)
    assert any("frontmatter" in e for e in errors)
    assert any("body" in e for e in errors)


def test_validate_page_spec_rejects_invalid_page_type():
    from pipeline.wiki_writer import validate_page_spec
    bad = {**MOCK_PAGES[0], "page_type": "unknown-type"}
    errors = validate_page_spec(bad)
    assert any("page_type" in e for e in errors)


def test_validate_page_spec_rejects_funding_legacy_name():
    """The old 'funding' type is gone — must use 'funding-event'."""
    from pipeline.wiki_writer import validate_page_spec
    bad = {**MOCK_PAGES[0], "page_type": "funding"}
    errors = validate_page_spec(bad)
    assert any("page_type" in e for e in errors)


def test_validate_page_spec_rejects_forbidden_types():
    """Plan, topic, mechanism, synthesis must never be created by Pass 3."""
    from pipeline.wiki_writer import validate_page_spec
    for forbidden in ("plan", "topic", "synthesis", "mechanism"):
        spec = {**MOCK_PAGES[0], "page_type": forbidden}
        errors = validate_page_spec(spec)
        assert any("forbidden" in e for e in errors), (
            f"Expected forbidden error for page_type={forbidden!r}, got: {errors}"
        )


def test_validate_page_spec_accepts_all_llm_writable_types():
    """All 10 LLM-writable types pass type validation (commitment removed, strategy added)."""
    from pipeline.wiki_writer import validate_page_spec
    for pt in ("strategy", "initiative", "actor", "funding-event",
               "technology", "location", "meeting", "framing",
               "political-event", "contradiction"):
        spec = {
            "page_type": pt,
            "slug": f"test/{pt}-slug",
            "frontmatter": {"type": pt},
            "body": "Test body. ([[sources/cap/cap-2020|cap-2020]])",
        }
        errors = validate_page_spec(spec)
        type_errors = [e for e in errors if "page_type" in e or "forbidden" in e]
        assert type_errors == [], f"Unexpected type error for {pt!r}: {type_errors}"


def test_validate_page_spec_rejects_commitment_type():
    """The 'commitment' type is eliminated in V2 — all actions are initiatives."""
    from pipeline.wiki_writer import validate_page_spec
    spec = {**MOCK_PAGES[0], "page_type": "commitment"}
    errors = validate_page_spec(spec)
    assert any("page_type" in e for e in errors), (
        f"Expected invalid page_type error for 'commitment', got: {errors}"
    )


def test_write_or_append_page_creates_new_file(tmp_path):
    from pipeline.wiki_writer import write_or_append_page
    write_or_append_page(MOCK_PAGES[0], wiki_root=str(tmp_path), source_uuid="cap-2020")
    out = tmp_path / "initiatives" / "community-choice-aggregation.md"
    assert out.exists()
    content = out.read_text()
    assert "Community Choice Aggregation" in content
    assert "---" in content


def test_write_or_append_page_appends_to_existing(tmp_path):
    from pipeline.wiki_writer import write_or_append_page
    write_or_append_page(MOCK_PAGES[0], wiki_root=str(tmp_path), source_uuid="cap-2020")
    original_path = tmp_path / "initiatives" / "community-choice-aggregation.md"
    original_content = original_path.read_text()

    updated_spec = {**MOCK_PAGES[0], "body": "Additional context from year1 report."}
    write_or_append_page(updated_spec, wiki_root=str(tmp_path), source_uuid="a2zero-year1")

    new_content = original_path.read_text()
    assert "procure renewable electricity" in new_content
    assert "Additional context from year1" in new_content
    assert new_content.startswith(original_content[:50])
    assert "<!-- source: a2zero-year1 -->" in new_content


def test_write_or_append_page_frontmatter_is_valid_yaml(tmp_path):
    from pipeline.wiki_writer import write_or_append_page
    write_or_append_page(MOCK_PAGES[1], wiki_root=str(tmp_path), source_uuid="cap-2020")
    out = tmp_path / "actors" / "osi.md"
    content = out.read_text()
    parts = content.split("---\n")
    parsed = yaml.safe_load(parts[1])
    assert parsed["type"] == "actor"
    assert parsed["actor-type"] == "government-office"


@patch("pipeline.wiki_writer.anthropic.Anthropic")
def test_extract_wiki_pages_from_chunk_calls_llm(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=json.dumps(MOCK_PAGES))]
    mock_client.messages.create.return_value = mock_response

    from pipeline.wiki_writer import extract_wiki_pages_from_chunk
    pages = extract_wiki_pages_from_chunk(
        chunk_text=SAMPLE_CHUNK,
        source_uuid="cap-2020",
        silver_relative_path="sources/cap/cap-2020",
        context_header="[DOCUMENT CONTEXT]\nDocument: Test CAP\n[END CONTEXT]",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-22",
    )
    assert mock_client.messages.create.called
    assert len(pages) == 2
    assert (tmp_path / "initiatives" / "community-choice-aggregation.md").exists()
    assert (tmp_path / "actors" / "osi.md").exists()


@patch("pipeline.wiki_writer.anthropic.Anthropic")
def test_extract_wiki_pages_from_chunk_handles_llm_failure(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API error")

    from pipeline.wiki_writer import extract_wiki_pages_from_chunk
    pages = extract_wiki_pages_from_chunk(
        chunk_text=SAMPLE_CHUNK,
        source_uuid="cap-2020",
        silver_relative_path="sources/cap/cap-2020",
        context_header="",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-22",
    )
    assert pages == []


@patch("pipeline.wiki_writer.anthropic.Anthropic")
def test_extract_wiki_pages_from_chunk_handles_max_tokens(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.stop_reason = "max_tokens"
    mock_client.messages.create.return_value = mock_response

    from pipeline.wiki_writer import extract_wiki_pages_from_chunk
    pages = extract_wiki_pages_from_chunk(
        chunk_text=SAMPLE_CHUNK,
        source_uuid="cap-2020",
        silver_relative_path="sources/cap/cap-2020",
        context_header="",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-22",
    )
    assert pages == []


def test_validate_page_spec_rejects_unknown_strategy_slug():
    """A strategy slug not in the pre-existing set must be rejected."""
    from pipeline.wiki_writer import validate_page_spec
    spec = {
        "page_type": "strategy",
        "slug": "strategies/strategy-8-invented",
        "frontmatter": {"type": "strategy"},
        "body": "This strategy does not exist. ([[sources/cap/cap-2020|cap-2020]])",
    }
    allowed = frozenset({"strategies/strategy-1-renewable-grid",
                         "strategies/strategy-2-electrification"})
    errors = validate_page_spec(spec, allowed_strategy_slugs=allowed)
    assert any("strategy" in e and "not a pre-existing" in e for e in errors), (
        f"Expected whitelist error, got: {errors}"
    )


def test_validate_page_spec_accepts_known_strategy_slug():
    """A strategy slug in the pre-existing set must be accepted."""
    from pipeline.wiki_writer import validate_page_spec
    spec = {
        "page_type": "strategy",
        "slug": "strategies/strategy-1-renewable-grid",
        "frontmatter": {"type": "strategy"},
        "body": "Strategy 1 focuses on renewable energy. ([[sources/cap/cap-2020|cap-2020]])",
    }
    allowed = frozenset({"strategies/strategy-1-renewable-grid",
                         "strategies/strategy-2-electrification"})
    errors = validate_page_spec(spec, allowed_strategy_slugs=allowed)
    type_errors = [e for e in errors if "strategy" in e and "not a pre-existing" in e]
    assert type_errors == [], f"Unexpected whitelist error: {type_errors}"


def test_validate_page_spec_skips_whitelist_when_not_provided():
    """If allowed_strategy_slugs is None, skip the whitelist check (test mode)."""
    from pipeline.wiki_writer import validate_page_spec
    spec = {
        "page_type": "strategy",
        "slug": "strategies/strategy-99-unknown",
        "frontmatter": {"type": "strategy"},
        "body": "Some strategy content. ([[sources/cap/cap-2020|cap-2020]])",
    }
    errors = validate_page_spec(spec, allowed_strategy_slugs=None)
    type_errors = [e for e in errors if "not a pre-existing" in e]
    assert type_errors == [], f"Unexpected error with no whitelist: {type_errors}"
