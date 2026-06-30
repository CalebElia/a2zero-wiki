# tests/test_ldp.py
import json
import pytest
import re
from pathlib import Path
from unittest.mock import MagicMock, patch


SAMPLE_SILVER = """\
---
uuid: test-cap
source_type: cap
title: "Test CAP"
ldp: true
---

# WELCOME LETTER

Friends, we face climate change.

## Strategy 1: Renewable Grid

The city will power its grid with 100% renewable energy.

### Implement Community Choice Aggregation

Community Choice Aggregation (CCA) will allow residents to choose
renewable energy sources.

**Party Responsible for Implementation:** Office of Sustainability

**Timeline and Initial Actions:** Launch by 2021.

## Strategy 2: Electrification

Switch appliances from fossil fuels to electric.

### Promote Home Electrification

Residents can replace gas appliances with heat pumps.

# Closing

Thank you for your commitment.
"""


def test_parse_section_map_finds_top_level_sections():
    from pipeline.pass2a_chunk_loop import parse_section_map
    sm = parse_section_map(SAMPLE_SILVER, "test-cap")
    titles = [s["title"] for s in sm["sections"]]
    assert "WELCOME LETTER" in titles
    assert "Closing" in titles


def test_parse_section_map_finds_strategy_sections():
    from pipeline.pass2a_chunk_loop import parse_section_map
    sm = parse_section_map(SAMPLE_SILVER, "test-cap")
    titles = [s["title"] for s in sm["sections"]]
    assert "Strategy 1: Renewable Grid" in titles
    assert "Strategy 2: Electrification" in titles


def test_parse_section_map_records_depth():
    from pipeline.pass2a_chunk_loop import parse_section_map
    sm = parse_section_map(SAMPLE_SILVER, "test-cap")
    strat1 = next(s for s in sm["sections"] if s["title"] == "Strategy 1: Renewable Grid")
    assert strat1["depth"] == 2
    welcome = next(s for s in sm["sections"] if s["title"] == "WELCOME LETTER")
    assert welcome["depth"] == 1


def test_parse_section_map_has_line_ranges():
    from pipeline.pass2a_chunk_loop import parse_section_map
    sm = parse_section_map(SAMPLE_SILVER, "test-cap")
    for section in sm["sections"]:
        assert "line_start" in section
        assert "line_end" in section
        assert section["line_end"] >= section["line_start"]


def test_parse_section_map_metadata():
    from pipeline.pass2a_chunk_loop import parse_section_map
    sm = parse_section_map(SAMPLE_SILVER, "test-cap")
    assert sm["document_uuid"] == "test-cap"
    assert sm["ldp_version"] == "1.1"
    assert sm["total_lines"] > 0


def test_save_section_map_writes_json(tmp_path):
    from pipeline.pass2a_chunk_loop import parse_section_map, save_section_map
    sm = parse_section_map(SAMPLE_SILVER, "test-cap")
    path = save_section_map(sm, str(tmp_path))
    assert Path(path).exists()
    loaded = json.loads(Path(path).read_text())
    assert loaded["document_uuid"] == "test-cap"
    assert Path(path).name == "test-cap_structure.json"


def test_build_chunk_context_header_contains_section_title():
    from pipeline.pass2a_chunk_loop import build_chunk_context_header
    header = build_chunk_context_header(
        document_title="Ann Arbor A2Zero CAP",
        document_uuid="cap-2020",
        section={"id": "strategy-1", "title": "Strategy 1: Renewable Grid", "depth": 2},
        section_index=3,
        total_sections=15,
        parent_title="The Living Carbon Neutrality Strategy",
    )
    assert "Strategy 1: Renewable Grid" in header
    assert "cap-2020" in header
    assert "Ann Arbor A2Zero CAP" in header
    assert "4 of 15" in header
    assert "Living Carbon Neutrality" in header


def test_build_chunk_context_header_no_parent():
    from pipeline.pass2a_chunk_loop import build_chunk_context_header
    header = build_chunk_context_header(
        document_title="Test Doc",
        document_uuid="test",
        section={"id": "intro", "title": "Introduction", "depth": 1},
        section_index=0,
        total_sections=5,
        parent_title=None,
    )
    assert "Introduction" in header
    assert "[END CONTEXT]" in header


def test_get_chunks_returns_depth1_and_depth2_only():
    from pipeline.pass2a_chunk_loop import parse_section_map, get_chunks
    sm = parse_section_map(SAMPLE_SILVER, "test-cap")
    chunks = get_chunks(sm)
    depths = {c["depth"] for c in chunks}
    assert depths.issubset({1, 2})  # only chunk at # and ## level


def test_extract_chunk_lines_returns_correct_text():
    from pipeline.pass2a_chunk_loop import extract_chunk_lines
    lines = SAMPLE_SILVER.splitlines()
    # grab a known range
    text = extract_chunk_lines(lines, line_start=1, line_end=3)
    assert "---" in text


@patch("pipeline.pass2b_extract.extract_wiki_pages_from_chunk")
@patch("pipeline.pass2a_chunk_loop.chat")
def test_extract_quads_chunked_calls_llm_per_chunk(mock_chat, mock_wiki_writer_extract):
    import json
    valid_quad = {
        "id": "sha256-abc001",
        "date": "2021",
        "date_precision": "year",
        "subject": "cca-program",
        "relation": "planned to launch",
        "object": "community choice aggregation by 2021",
        "sources": ["test-cap"],
        "source_types": ["cap"],
        "confidence": 2,
        "status": "confirmed",
        "dark_matter": False,
        "topics": [],
        "locations": [],
        "strategies": ["strategy-1"],
        "actors": [],
        "keywords": ["cca", "renewable-energy"],
        "fund_type": None,
        "commitment_status": "unverified",
        "last_updated": "2026-06-22",
    }
    mock_chat.return_value = json.dumps([valid_quad])
    # Pass 3 is stubbed out entirely — not under test here
    mock_wiki_writer_extract.return_value = []
    from pipeline.pass2a_chunk_loop import parse_section_map, extract_quads_chunked
    sm = parse_section_map(SAMPLE_SILVER, "test-cap")
    quads, pages_written = extract_quads_chunked(
        source_content=SAMPLE_SILVER,
        section_map=sm,
        source_uuid="test-cap",
        document_title="Test CAP",
    )
    assert mock_chat.call_count >= 1
    assert len(quads) >= 1
    assert isinstance(pages_written, int)


@patch("pipeline.pass2b_extract.extract_wiki_pages_from_chunk")
@patch("pipeline.pass2a_chunk_loop.chat")
def test_extract_quads_chunked_passes_plan_context_to_writer(mock_chat, mock_wiki_writer_extract, tmp_path):
    """When integration_plan + retrieved_bodies are supplied, they appear in the chunk's context_header."""
    section_map = {
        "uuid": "test", "sections": [
            {"id": "strategy-1", "depth": 1, "title": "Strategy 1", "line_start": 1, "line_end": 5, "section_num": "1"}
        ]
    }
    source = "# Strategy 1\nSome chunk content.\n"
    mock_chat.return_value = "[]"
    mock_wiki_writer_extract.return_value = []

    plan = {"strategies-touched": ["strategies/strategy-1-x"], "extends": [{"slug": "initiatives/x", "new-data": "y"}], "new-entities": [], "retrieve-for-context": ["initiatives/x"], "theme-connections": []}
    bodies = {"initiatives/x": "Existing body text for X"}

    from pipeline.pass2a_chunk_loop import extract_quads_chunked
    extract_quads_chunked(
        source_content=source,
        section_map=section_map,
        source_uuid="test", document_title="T",
        wiki_root=str(tmp_path),
        run_date="2026-06-29",
        integration_plan=plan,
        retrieved_bodies=bodies,
    )
    # The wiki_writer call should have received a context_header containing the plan + body
    assert mock_wiki_writer_extract.called
    context_header = mock_wiki_writer_extract.call_args.kwargs["context_header"]
    assert "INTEGRATION PLAN" in context_header
    assert "Existing body text for X" in context_header


def test_run_source_ingest_routes_to_ldp_when_flagged(tmp_path):
    from unittest.mock import patch, MagicMock
    source_file = tmp_path / "cap-2020.md"
    source_file.write_text(SAMPLE_SILVER)
    quads_file = tmp_path / "quads.jsonl"
    queue_file = tmp_path / "review-queue.md"

    with patch("pipeline.orchestrator.synthesize_source") as mock_synth, \
         patch("pipeline.orchestrator.run_ldp_ingest") as mock_ldp, \
         patch("pipeline.orchestrator.rebuild_index") as mock_rebuild, \
         patch("pipeline.orchestrator.wiki_append_log") as mock_log, \
         patch("pipeline.orchestrator.run_post_ingest") as mock_post:
        mock_synth.return_value = {"stub_pages": []}
        mock_post.return_value = MagicMock(
            total_quads=0, schema_errors=[], dark_matter_ids=[]
        )
        from pipeline.orchestrator import run_source_ingest
        run_source_ingest(
            source_path=str(source_file),
            uuid="test-cap",
            title="Test CAP",
            quads_path=str(quads_file),
            wiki_root=str(tmp_path / "wiki"),
            review_queue_path=str(queue_file),
        )
        mock_synth.assert_called_once()
        mock_ldp.assert_called_once()
        mock_rebuild.assert_called_once()
        mock_log.assert_called_once()


def test_run_source_ingest_uses_single_pass_without_ldp_flag(tmp_path):
    source_content = "## Short doc\n\nJust a few lines.\n"
    source_file = tmp_path / "short.md"
    source_file.write_text(source_content)
    quads_file = tmp_path / "quads.jsonl"
    queue_file = tmp_path / "review-queue.md"

    with patch("pipeline.orchestrator.synthesize_source") as mock_synth, \
         patch("pipeline.orchestrator.extract_quads_from_source") as mock_extract, \
         patch("pipeline.orchestrator.rebuild_index") as mock_rebuild, \
         patch("pipeline.orchestrator.wiki_append_log") as mock_log, \
         patch("pipeline.orchestrator.run_post_ingest") as mock_post, \
         patch("pipeline.pass2b_extract.chat") as mock_wiki_writer_chat:
        mock_synth.return_value = {"stub_pages": []}
        mock_extract.return_value = []
        mock_post.return_value = MagicMock(
            total_quads=0, schema_errors=[], dark_matter_ids=[]
        )
        mock_wiki_writer_chat.return_value = "[]"
        from pipeline.orchestrator import run_source_ingest
        run_source_ingest(
            source_path=str(source_file),
            uuid="short-doc",
            title="Short Doc",
            quads_path=str(quads_file),
            wiki_root=str(tmp_path / "wiki"),
            review_queue_path=str(queue_file),
        )
        mock_synth.assert_called_once()
        mock_extract.assert_called_once()
        mock_rebuild.assert_called_once()
        mock_log.assert_called_once()
