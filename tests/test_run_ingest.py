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


@patch("pipeline._legacy.raw_to_sources.extract_pdf_text", return_value="Raw PDF text")
@patch("pipeline._pages.stream_chat", return_value=None)
@patch("pipeline._legacy.raw_to_sources.chat", return_value=MOCK_SOURCE_BODY)
def test_run_ingest_creates_source_file(
    mock_chat, mock_stream_chat, mock_extract, tmp_path
):
    mock_stream_chat.return_value = json.dumps(MOCK_QUADS)

    source_dir = tmp_path / "sources" / "annual-reports"
    quads_file = tmp_path / "blackboard" / "quads.jsonl"
    wiki_root = tmp_path / "wiki"
    queue_file = tmp_path / "review-queue.md"

    from pipeline.orchestrator import run_annual_report_ingest
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


@patch("pipeline.orchestrator.synthesize_source")
@patch("pipeline.orchestrator.run_ldp_ingest")
@patch("pipeline.orchestrator.extract_quads_from_source")
@patch("pipeline.orchestrator.rebuild_index")
@patch("pipeline.orchestrator.wiki_append_log")
@patch("pipeline.orchestrator.run_post_ingest")
@patch("pipeline.pass1a_comprehend.chat")
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

    from pipeline.orchestrator import run_source_ingest
    with patch("pipeline.pass2b_extract.chat", return_value="[]"):
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


@patch("pipeline.orchestrator.synthesize_source")
@patch("pipeline.orchestrator.rebuild_index")
@patch("pipeline.orchestrator.wiki_append_log")
@patch("pipeline.orchestrator.run_post_ingest")
@patch("pipeline.pass1a_comprehend.chat")
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

    from pipeline.orchestrator import run_source_ingest
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


@patch("pipeline.orchestrator.synthesize_source")
@patch("pipeline.orchestrator.run_ldp_ingest")
@patch("pipeline.orchestrator.extract_quads_from_source")
@patch("pipeline.orchestrator.rebuild_index")
@patch("pipeline.orchestrator.wiki_append_log")
@patch("pipeline.orchestrator.run_post_ingest")
@patch("pipeline.pass1a_comprehend.chat")
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

    from pipeline.orchestrator import run_source_ingest
    with patch("pipeline.pass2b_extract.chat", return_value="[]"):
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


@patch("pipeline.orchestrator.synthesize_source")
@patch("pipeline.orchestrator.run_ldp_ingest")
@patch("pipeline.orchestrator.rebuild_index")
@patch("pipeline.orchestrator.wiki_append_log")
def test_run_source_ingest_hard_fails_when_pass1b_writer_fails(
    mock_log, mock_rebuild, mock_ldp, mock_synth, tmp_path
):
    """Pass 1B returns None (Writer failed after retries) → ingest halts before
    Pass 2 LDP extraction rather than continuing with empty entity context.
    Regression test for a real failure: an unguarded Azure streaming bug
    crashed the Writer, but LDP ran anyway on empty context and would have
    produced ungrounded/duplicate entity pages costing real tokens to fix."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    # No digest.md — first-ingest path, Comprehend is skipped, keeps this
    # test focused on the Pass 1B failure only.
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "test.md"
    src_path.write_text("---\nuuid: test\n---\nBody\n", encoding="utf-8")

    mock_synth.return_value = None  # Writer failed after retries

    from pipeline.orchestrator import run_source_ingest
    with pytest.raises(RuntimeError, match="Pass 1B holistic synthesis failed"):
        run_source_ingest(
            source_path=str(src_path),
            uuid="test", title="T", quads_path=str(tmp_path / "q.jsonl"),
            wiki_root=str(wiki), review_queue_path=str(tmp_path / "queue.md"),
            run_date="2026-07-02",
        )
    # Pass 2 (LDP) never fired
    assert mock_ldp.call_count == 0
    assert mock_rebuild.call_count == 0


def test_source_ingest_refuses_without_approved_map(tmp_path):
    import pytest
    from unittest.mock import patch
    # Stage a wiki + source that would route to LDP
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "t.md"
    # Long enough to route to LDP: 150+ lines, 5+ headings
    headings_and_body = "\n".join([f"# H{i}\nbody{i}" for i in range(10)]) + ("\nfiller\n" * 200)
    src_path.write_text(f"---\nuuid: t\n---\n{headings_and_body}", encoding="utf-8")

    from pipeline.orchestrator import run_source_ingest
    with patch("pipeline.orchestrator.synthesize_source", return_value={"stub_pages": []}), \
         pytest.raises(RuntimeError, match="approved section map"):
        run_source_ingest(
            source_path=str(src_path),
            uuid="t", title="T",
            quads_path=str(tmp_path / "q.jsonl"),
            wiki_root=str(wiki),
            review_queue_path=str(tmp_path / "queue.md"),
            section_maps_dir=str(tmp_path / "maps"),
            run_date="2026-06-30",
            wiki_only=True,
            auto_approve_chunks=False,  # gate ON
        )


def test_source_ingest_small_doc_bypasses_gate(tmp_path):
    """Small docs route to the non-LDP path and don't need approval."""
    from unittest.mock import patch
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "tiny.md"
    src_path.write_text("---\nuuid: tiny\n---\n# Just one heading\nBrief.\n", encoding="utf-8")

    with patch("pipeline.orchestrator.synthesize_source", return_value={"stub_pages": []}), \
         patch("pipeline.pass2b_extract.extract_wiki_pages_from_chunk", return_value=[]), \
         patch("pipeline.pass2b_extract.chat", return_value="[]"), \
         patch("pipeline.pass1a_comprehend.chat") as mock_comprehend:
        # No digest exists → comprehend graceful fallback (no LLM)
        from pipeline.orchestrator import run_source_ingest
        run_source_ingest(
            source_path=str(src_path),
            uuid="tiny", title="T",
            quads_path=str(tmp_path / "q.jsonl"),
            wiki_root=str(wiki),
            review_queue_path=str(tmp_path / "queue.md"),
            run_date="2026-06-30",
            wiki_only=True,
            auto_approve_chunks=False,  # gate ON but irrelevant for small docs
        )
        # No exception — gate was bypassed because LDP wasn't used
