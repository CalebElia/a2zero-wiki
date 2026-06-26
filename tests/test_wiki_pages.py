import json
import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.wiki_pages import (
    append_quads,
    parse_llm_quads_response,
    build_quads_prompt,
)
from pipeline.models import validate_quad


FIXTURE_SOURCE = (Path(__file__).parent / "fixtures" / "sample_annual_report.md").read_text()


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
    prompt = build_quads_prompt(source_body="Some text.", source_uuid="a2zero-year1")
    assert "a2zero-year1" in prompt


def test_parse_llm_quads_response_raises_on_prose_prefix():
    raw = "Here are the quads you requested:\n[{\"id\": \"sha256-x\"}]"
    with pytest.raises(ValueError):
        parse_llm_quads_response(raw)


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY",
)
def test_integration_extract_quads_from_fixture(tmp_path):
    from pipeline.wiki_pages import extract_quads_from_source
    out_file = tmp_path / "quads.jsonl"
    quads = extract_quads_from_source(FIXTURE_SOURCE, source_uuid="test-year1", out_path=str(out_file))
    assert len(quads) >= 1
    for q in quads:
        errors = validate_quad(q)
        assert errors == [], f"invalid quad: {q}\nerrors: {errors}"
