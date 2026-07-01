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
