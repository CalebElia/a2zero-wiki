import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


MOCK_SOURCE_BODY = """## Strategy 1: 100% Renewable Grid

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


@patch("pipeline.raw_to_sources.extract_pdf_text", return_value="Raw PDF text")
@patch("pipeline.wiki_pages.stream_chat", return_value=None)
@patch("pipeline.raw_to_sources.chat", return_value=MOCK_SOURCE_BODY)
def test_run_ingest_creates_source_file(
    mock_chat, mock_stream_chat, mock_extract, tmp_path
):
    mock_stream_chat.return_value = json.dumps(MOCK_QUADS)

    source_dir = tmp_path / "sources" / "annual-reports"
    quads_file = tmp_path / "blackboard" / "quads.jsonl"
    wiki_root = tmp_path / "wiki"
    queue_file = tmp_path / "review-queue.md"

    from pipeline.run_ingest import run_annual_report_ingest
    run_annual_report_ingest(
        pdf_path="raw/annual-reports/a2zero-year1.pdf",
        uuid="a2zero-year1",
        year="year1",
        title="A2Zero Year 1 Annual Report",
        source_dir=str(source_dir),
        quads_path=str(quads_file),
        wiki_root=str(wiki_root),
        review_queue_path=str(queue_file),
        run_date="2026-06-18",
    )

    source_file = source_dir / "a2zero-year1.md"
    assert source_file.exists(), "Source file not created"
    assert quads_file.exists(), "quads.jsonl not created"
    lines = [l for l in quads_file.read_text().splitlines() if l.strip()]
    assert len(lines) >= 1, "No quads written"
    assert queue_file.exists(), "review-queue.md not created"
