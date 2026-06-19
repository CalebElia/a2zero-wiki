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


@patch("pipeline.bronze_to_silver.extract_pdf_text", return_value="Raw PDF text")
@patch("anthropic.Anthropic")
def test_run_ingest_creates_silver_file(
    mock_anthropic_class, mock_extract, tmp_path
):
    import json
    import pipeline.bronze_to_silver as b2s
    b2s._DEFAULT_CLIENT = None

    mock_silver_client = MagicMock()
    mock_silver_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=MOCK_SILVER_BODY)]
    )
    mock_gold_client = MagicMock()
    mock_gold_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps(MOCK_QUADS))]
    )
    # First Anthropic() call → silver client (bronze_to_silver); second → gold client (silver_to_gold)
    mock_anthropic_class.side_effect = [mock_silver_client, mock_gold_client]

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
