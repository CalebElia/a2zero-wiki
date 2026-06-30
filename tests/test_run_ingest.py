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


@patch("pipeline.run_ingest.synthesize_source")
@patch("pipeline.run_ingest.run_ldp_ingest")
@patch("pipeline.run_ingest.extract_quads_from_source")
@patch("pipeline.run_ingest.rebuild_index")
@patch("pipeline.run_ingest.wiki_append_log")
@patch("pipeline.run_ingest.run_post_ingest")
@patch("pipeline.comprehend.chat")
def test_run_source_ingest_calls_comprehend_when_digest_exists(
    mock_comprehend_chat, mock_post, mock_log, mock_rebuild, mock_extract, mock_ldp, mock_synth, tmp_path
):
    """Digest present → Comprehend fires → plan persisted → synthesize_source receives plan."""
    import json as _json

    # Stage wiki with a digest
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "digest.md").write_text("---\nlast-rebuilt: '2026-06-29'\n---\n# Digest\nBody.\n", encoding="utf-8")
    (wiki / "meta").mkdir()
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "test.md"
    src_path.write_text("---\nuuid: test\nsource_type: annual-report\n---\nSource body.\n", encoding="utf-8")

    # Mock Comprehend to return a valid plan
    mock_comprehend_chat.return_value = _json.dumps({
        "strategies-touched": ["strategies/strategy-1-renewable-grid"],
        "extends": [],
        "new-entities": [],
        "retrieve-for-context": [],
        "theme-connections": [],
    })
    mock_synth.return_value = {"stub_pages": []}
    mock_extract.return_value = []
    mock_post.return_value = type("R", (), {"total_quads": 0, "schema_errors": [], "dark_matter_ids": []})()

    from pipeline.run_ingest import run_source_ingest
    with patch("pipeline.wiki_writer.chat", return_value="[]"):
        run_source_ingest(
            source_path=str(src_path),
            uuid="test",
            title="Test",
            quads_path=str(tmp_path / "quads.jsonl"),
            wiki_root=str(wiki),
            review_queue_path=str(tmp_path / "queue.md"),
            run_date="2026-06-29",
        )

    # Comprehend was called
    assert mock_comprehend_chat.call_count == 1
    # Plan was persisted
    assert (wiki / "integration-plans" / "test.json").exists()
    # Stats line was appended
    assert (wiki / "meta" / "ingest-stats.jsonl").exists()
    # synthesize_source received the plan + digest
    synth_kwargs = mock_synth.call_args.kwargs
    assert synth_kwargs.get("integration_plan") is not None
    assert synth_kwargs.get("digest_content") is not None


@patch("pipeline.run_ingest.synthesize_source")
@patch("pipeline.run_ingest.rebuild_index")
@patch("pipeline.run_ingest.wiki_append_log")
@patch("pipeline.run_ingest.run_post_ingest")
@patch("pipeline.comprehend.chat")
def test_run_source_ingest_hard_fails_when_comprehend_errors_with_digest(
    mock_comprehend_chat, mock_post, mock_log, mock_rebuild, mock_synth, tmp_path
):
    """Digest present + Comprehend raises → ingest halts before any downstream work."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "digest.md").write_text("---\nlast-rebuilt: '2026-06-29'\n---\n# Digest\n", encoding="utf-8")
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "test.md"
    src_path.write_text("---\nuuid: test\n---\nBody\n", encoding="utf-8")

    mock_comprehend_chat.side_effect = Exception("API down")

    from pipeline.run_ingest import run_source_ingest
    with pytest.raises(Exception, match="API down"):
        run_source_ingest(
            source_path=str(src_path),
            uuid="test", title="T", quads_path=str(tmp_path / "q.jsonl"),
            wiki_root=str(wiki), review_queue_path=str(tmp_path / "queue.md"),
            run_date="2026-06-29",
        )
    # Downstream calls never fired
    assert mock_synth.call_count == 0
    assert mock_rebuild.call_count == 0


@patch("pipeline.run_ingest.synthesize_source")
@patch("pipeline.run_ingest.run_ldp_ingest")
@patch("pipeline.run_ingest.extract_quads_from_source")
@patch("pipeline.run_ingest.rebuild_index")
@patch("pipeline.run_ingest.wiki_append_log")
@patch("pipeline.run_ingest.run_post_ingest")
@patch("pipeline.comprehend.chat")
def test_run_source_ingest_skips_comprehend_when_no_digest(
    mock_comprehend_chat, mock_post, mock_log, mock_rebuild, mock_extract, mock_ldp, mock_synth, tmp_path
):
    """First ingest: no digest → graceful fallback, no LLM call, empty plan."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    # NOTE: no digest.md
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "test.md"
    src_path.write_text("---\nuuid: test\n---\nBody\n", encoding="utf-8")

    mock_synth.return_value = {"stub_pages": []}
    mock_extract.return_value = []
    mock_post.return_value = type("R", (), {"total_quads": 0, "schema_errors": [], "dark_matter_ids": []})()

    from pipeline.run_ingest import run_source_ingest
    with patch("pipeline.wiki_writer.chat", return_value="[]"):
        run_source_ingest(
            source_path=str(src_path),
            uuid="test", title="T", quads_path=str(tmp_path / "q.jsonl"),
            wiki_root=str(wiki), review_queue_path=str(tmp_path / "queue.md"),
            run_date="2026-06-29",
        )

    # No LLM call (graceful fallback)
    assert mock_comprehend_chat.call_count == 0
    # An empty plan was still written for the audit trail
    assert (wiki / "integration-plans" / "test.json").exists()
    # synthesize_source received digest_content=None
    synth_kwargs = mock_synth.call_args.kwargs
    assert synth_kwargs.get("digest_content") is None
