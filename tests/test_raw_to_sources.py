import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.raw_to_sources import write_source, build_frontmatter


def test_build_frontmatter_annual_report():
    fm = build_frontmatter(
        uuid="a2zero-year1",
        source_type="annual-report",
        title="A2Zero Year 1 Annual Report",
        year="year1",
        raw_path="raw/annual-reports/a2zero-year1.pdf",
        ingest_date="2026-06-18",
    )
    assert fm["uuid"] == "a2zero-year1"
    assert fm["source_type"] == "annual-report"
    assert fm["year"] == "year1"
    assert fm["raw_path"] == "raw/annual-reports/a2zero-year1.pdf"


def test_write_source_creates_file(tmp_path):
    out_path = tmp_path / "a2zero-year1.md"
    frontmatter = {
        "uuid": "a2zero-year1",
        "source_type": "annual-report",
        "title": "Test Report",
        "year": "year1",
        "ingest_date": "2026-06-18",
        "raw_path": "raw/annual-reports/a2zero-year1.pdf",
    }
    write_source(str(out_path), frontmatter, body="## Strategy 1\n\nContent here.")
    assert out_path.exists()
    content = out_path.read_text()
    assert content.startswith("---\n")
    assert "uuid: a2zero-year1" in content
    assert "## Strategy 1" in content


def test_write_source_frontmatter_is_valid_yaml(tmp_path):
    out_path = tmp_path / "test.md"
    frontmatter = {
        "uuid": "test-doc",
        "source_type": "annual-report",
        "title": "Test",
        "year": "year1",
        "ingest_date": "2026-06-18",
        "raw_path": "raw/test.pdf",
    }
    write_source(str(out_path), frontmatter, body="Body text.")
    content = out_path.read_text()
    # extract YAML block
    parts = content.split("---\n")
    parsed = yaml.safe_load(parts[1])
    assert parsed["uuid"] == "test-doc"


@patch("pipeline.raw_to_sources.anthropic.Anthropic")
def test_clean_with_llm_calls_anthropic(mock_anthropic_class):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="## Cleaned content")]
    )
    import pipeline.raw_to_sources as rts
    from pipeline.raw_to_sources import clean_with_llm
    rts._DEFAULT_CLIENT = None  # reset singleton so mock is picked up
    result = clean_with_llm("Raw extracted text", uuid="test-year1")
    assert mock_client.messages.create.called
    assert "Cleaned content" in result
