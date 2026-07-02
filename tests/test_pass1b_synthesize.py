import json
from unittest.mock import patch


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_context_injection_includes_progress_synthesis_regardless_of_digest(mock_stream_chat, tmp_path):
    """Existing Progress Synthesis text must be injected into the Writer prompt
    even when a digest is present — this was the root cause of a real content-loss bug."""
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    marker = "DISTINCTIVE-MARKER-PRIOR-FACT-42"
    for i in range(1, 8):
        slug = f"strategy-{i}-x"
        body = (
            "---\ntype: strategy\n---\n\n"
            "## Foundation\n\nFoundation text.\n\n"
            "## Progress Synthesis\n\n"
            + (f"Prior progress fact: {marker}.\n" if i == 1 else "Some other prior fact.\n")
        )
        (strategies_dir / f"{slug}.md").write_text(body, encoding="utf-8")
    (tmp_path / "overviews").mkdir()
    (tmp_path / "sources" / "test").mkdir(parents=True)

    writer_draft = {
        "overview": {
            "slug": "overviews/test",
            "frontmatter": {
                "type": "overview",
                "title": "T",
                "source-ref": "[[sources/test/test]]",
            },
            "body": "Overview body",
        },
        "strategy_bodies": [
            {"slug": f"strategies/strategy-{i}-x", "body": "body"} for i in range(1, 8)
        ],
        "stub_pages": [],
        "log_summary": "ok",
    }
    mock_stream_chat.side_effect = [
        json.dumps(writer_draft),
        json.dumps({"proceed_to_edit": True, "overall_score": 9}),
        json.dumps(writer_draft),
    ]

    from pipeline.pass1b_synthesize import synthesize_source
    synthesize_source(
        source_content="---\nuuid: test\n---\nSource body",
        source_uuid="test",
        source_rel_path="sources/test/test",
        source_type="test",
        wiki_root=str(tmp_path),
        run_date="2026-07-01",
        digest_content="[compressed digest text]",
    )

    first_call_user_content = mock_stream_chat.call_args_list[0].kwargs["messages"][0]["content"]
    text = first_call_user_content[0]["text"] if isinstance(first_call_user_content, list) else first_call_user_content
    assert marker in text, "full prior Progress Synthesis text must be injected even when digest_content is set"


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_relationship_lexicon_injected_into_writer_prompt(mock_stream_chat, tmp_path):
    """meta/relationship-lexicon.md content must reach the Writer prompt —
    previously the file was written but never read by any code."""
    wiki_root = tmp_path / "wiki"
    (wiki_root / "strategies").mkdir(parents=True)
    (wiki_root / "overviews").mkdir()
    (wiki_root / "sources" / "test").mkdir(parents=True)
    (tmp_path / "meta").mkdir()
    lexicon_marker = "DISTINCTIVE-LEXICON-VERB-implements"
    (tmp_path / "meta" / "relationship-lexicon.md").write_text(
        f"# Relationship Lexicon\n\nUse `{lexicon_marker}` not \"related to\".\n",
        encoding="utf-8",
    )

    writer_draft = {
        "overview": {
            "slug": "overviews/test",
            "frontmatter": {"type": "overview", "title": "T", "source-ref": "[[sources/test/test]]"},
            "body": "Overview body",
        },
        "strategy_bodies": [],
        "stub_pages": [],
        "log_summary": "ok",
    }
    mock_stream_chat.side_effect = [
        json.dumps(writer_draft),
        json.dumps({"proceed_to_edit": True, "overall_score": 9}),
        json.dumps(writer_draft),
    ]

    from pipeline.pass1b_synthesize import synthesize_source
    synthesize_source(
        source_content="---\nuuid: test\n---\nSource body",
        source_uuid="test",
        source_rel_path="sources/test/test",
        source_type="test",
        wiki_root=str(wiki_root),
        run_date="2026-07-03",
    )

    first_call_user_content = mock_stream_chat.call_args_list[0].kwargs["messages"][0]["content"]
    text = first_call_user_content[0]["text"] if isinstance(first_call_user_content, list) else first_call_user_content
    assert lexicon_marker in text
    assert "[RELATIONSHIP LEXICON]" in text


@patch("pipeline.pass1b_synthesize.append_query_log_entry")
@patch("pipeline.pass1b_synthesize.stream_chat")
def test_topic_candidates_route_to_query_log_not_topic_candidates_file(mock_stream_chat, mock_append_query_log, tmp_path):
    """topic_candidates from the Writer must go through append_query_log_entry
    (meta/query-log.md), not the retired meta/topic-candidates.md."""
    wiki_root = tmp_path / "wiki"
    (wiki_root / "strategies").mkdir(parents=True)
    (wiki_root / "overviews").mkdir()
    (wiki_root / "sources" / "test").mkdir(parents=True)

    required_slugs = [
        "strategies/strategy-1-renewable-grid",
        "strategies/strategy-2-electrification",
        "strategies/strategy-3-building-efficiency",
        "strategies/strategy-4-vmt-reduction",
        "strategies/strategy-5-materials-waste",
        "strategies/strategy-6-resilience",
        "strategies/strategy-7-engagement",
    ]
    for slug in required_slugs:
        (wiki_root / f"{slug}.md").write_text(
            "---\ntype: strategy\n---\n\n## Foundation\n\nFoundation text.\n\n## Progress Synthesis\n\nExisting.\n",
            encoding="utf-8",
        )
    writer_draft = {
        "overview": {
            "slug": "overviews/test",
            "frontmatter": {"type": "overview", "title": "T", "source-ref": "[[sources/test/test]]"},
            "body": "Overview body",
        },
        "strategy_bodies": [{"slug": s, "body": "body"} for s in required_slugs],
        "stub_pages": [
            {"type": "initiative", "title": "Solarize", "slug": "initiatives/solarize",
             "parent-strategy": "strategies/strategy-1-renewable-grid", "one-liner": "Solar program."},
        ],
        "topic_candidates": [
            {
                "title": "How was solar funded?",
                "rationale": "Spans multiple strategies.",
                "draft_narrative": "Funded via [[initiatives/solarize|Solarize]].",
            },
        ],
        "log_summary": "ok",
    }
    mock_stream_chat.side_effect = [
        json.dumps(writer_draft),
        json.dumps({"proceed_to_edit": True, "overall_score": 9}),
        json.dumps(writer_draft),
    ]

    from pipeline.pass1b_synthesize import synthesize_source
    synthesize_source(
        source_content="---\nuuid: test\n---\nSource body",
        source_uuid="test",
        source_rel_path="sources/test/test",
        source_type="test",
        wiki_root=str(wiki_root),
        run_date="2026-07-03",
    )

    mock_append_query_log.assert_called_once()
    call_kwargs = mock_append_query_log.call_args.kwargs
    assert call_kwargs["question"] == "How was solar funded?"
    assert "Solarize" in call_kwargs["answer_text"]
    assert not (tmp_path / "meta" / "topic-candidates.md").exists()


def test_split_strategy_sections_both_present():
    from pipeline.pass1b_synthesize import _split_strategy_sections
    body = "## Foundation\n\nFoundation text here.\n\n## Progress Synthesis\n\nProgress text here.\n"
    foundation, progress = _split_strategy_sections(body)
    assert foundation == "Foundation text here."
    assert progress == "Progress text here."


def test_split_strategy_sections_legacy_single_body():
    from pipeline.pass1b_synthesize import _split_strategy_sections
    body = "This is a legacy single-body strategy page with no section headers."
    foundation, progress = _split_strategy_sections(body)
    assert foundation is None
    assert progress is None


def test_assemble_strategy_body_round_trip():
    from pipeline.pass1b_synthesize import _split_strategy_sections, _assemble_strategy_body
    assembled = _assemble_strategy_body("Foundation text.", "Progress text.")
    foundation, progress = _split_strategy_sections(assembled)
    assert foundation == "Foundation text."
    assert progress == "Progress text."


def test_write_synthesis_refuses_when_foundation_missing(tmp_path):
    from pipeline.pass1b_synthesize import _write_synthesis
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    (strategies_dir / "strategy-1-renewable-grid.md").write_text(
        "---\ntype: strategy\n---\nLegacy single-body content, no sections.\n"
    )
    result = {
        "overview": {"slug": "overviews/test", "frontmatter": {
            "type": "overview", "title": "Test", "source-ref": "[[sources/test]]"
        }, "body": "Test overview."},
        "strategy_bodies": [
            {"slug": "strategies/strategy-1-renewable-grid", "body": "New progress text."}
        ],
        "stub_pages": [],
    }
    import pytest
    with pytest.raises(RuntimeError, match="no Foundation section"):
        _write_synthesis(result, wiki_root=str(tmp_path), source_uuid="test",
                          source_rel_path="sources/test.md", run_date="2026-07-01")


def test_write_synthesis_updates_progress_preserves_foundation(tmp_path):
    from pipeline.pass1b_synthesize import _write_synthesis, _split_strategy_sections
    import re
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    (strategies_dir / "strategy-1-renewable-grid.md").write_text(
        "---\ntype: strategy\n---\n"
        "## Foundation\n\nOriginal CAP-2020 target text.\n\n"
        "## Progress Synthesis\n\nOld progress text.\n"
    )
    result = {
        "overview": {"slug": "overviews/test", "frontmatter": {
            "type": "overview", "title": "Test", "source-ref": "[[sources/test]]"
        }, "body": "Test overview."},
        "strategy_bodies": [
            {"slug": "strategies/strategy-1-renewable-grid", "body": "New progress text, building on the old."}
        ],
        "stub_pages": [],
    }
    _write_synthesis(result, wiki_root=str(tmp_path), source_uuid="test",
                      source_rel_path="sources/test.md", run_date="2026-07-01")
    written = (strategies_dir / "strategy-1-renewable-grid.md").read_text()
    foundation, progress = _split_strategy_sections(
        re.sub(r"^---\n.*?\n---\n", "", written, flags=re.DOTALL)
    )
    assert foundation == "Original CAP-2020 target text."
    assert progress == "New progress text, building on the old."
