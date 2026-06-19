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
