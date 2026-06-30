# tests/test_synthesize_wiki.py


def test_module_imports():
    """Smoke test: the module exists and exposes the expected public API."""
    from pipeline import phase_c_synthesize
    assert hasattr(phase_c_synthesize, "synthesize_wiki")
    assert callable(phase_c_synthesize.synthesize_wiki)
    assert hasattr(phase_c_synthesize, "ALL_STRATEGIES")
    assert len(phase_c_synthesize.ALL_STRATEGIES) == 7


def test_gather_strategy_entities_filters_by_strategy(tmp_path):
    """Returns only entities tagged to the given strategy."""
    import shutil
    from pipeline.phase_c_synthesize import gather_strategy_entities

    fixture = "tests/fixtures/synthesize_wiki/wiki"
    shutil.copytree(fixture, tmp_path / "wiki")

    entities = gather_strategy_entities(
        wiki_root=str(tmp_path / "wiki"),
        strategy_slug="strategies/strategy-1-renewable-grid",
    )
    titles = sorted(e["title"] for e in entities)
    assert titles == ["Great Lakes Renewable Energy Association", "Solarize Ann Arbor"]

    # Each entity dict carries the keys the downstream LLM prompt expects
    for e in entities:
        assert set(e.keys()) >= {"slug", "title", "type", "one-liner"}


def test_gather_strategy_entities_returns_empty_for_unknown_strategy(tmp_path):
    import shutil
    from pipeline.phase_c_synthesize import gather_strategy_entities
    shutil.copytree("tests/fixtures/synthesize_wiki/wiki", tmp_path / "wiki")
    entities = gather_strategy_entities(
        wiki_root=str(tmp_path / "wiki"),
        strategy_slug="strategies/strategy-99-nonexistent",
    )
    assert entities == []


LOG_FIXTURE = """# Ingest Log

## [2026-06-15 | cap-2020]
Pass 3 complete — index rebuilt.

## [2026-06-25 | a2zero-year1]
Pass 3 complete — index rebuilt.

## [2026-06-26 | a2zero-year2]
Pass 3 complete — index rebuilt.
"""


def test_extract_recent_delta_returns_last_entry(tmp_path):
    from pipeline.phase_c_synthesize import extract_recent_delta
    log_path = tmp_path / "log.md"
    log_path.write_text(LOG_FIXTURE, encoding="utf-8")
    delta = extract_recent_delta(str(log_path))
    assert delta["source_uuid"] == "a2zero-year2"
    assert delta["date"] == "2026-06-26"


def test_extract_recent_delta_handles_empty_log(tmp_path):
    from pipeline.phase_c_synthesize import extract_recent_delta
    log_path = tmp_path / "log.md"
    log_path.write_text("# Ingest Log\n", encoding="utf-8")
    delta = extract_recent_delta(str(log_path))
    assert delta == {}


import json
from unittest.mock import patch


SAMPLE_ENTITIES = [
    {"slug": "initiatives/solarize-ann-arbor", "title": "Solarize Ann Arbor",
     "type": "initiative", "one-liner": "Residential solar bulk-buy."},
    {"slug": "actors/glrea", "title": "Great Lakes Renewable Energy Association",
     "type": "actor", "one-liner": "Nonprofit leading Solarize."},
]


def test_build_strategy_synthesis_calls_anthropic_and_returns_dict():
    from pipeline.phase_c_synthesize import build_strategy_synthesis

    llm_output = json.dumps({
        "core-initiatives": ["initiatives/solarize-ann-arbor"],
        "core-actors": ["actors/glrea"],
        "year-over-year-arc": "Residential solar grew 31% Y1→Y2.",
        "open-questions": ["5MW Y3 target on track?"],
        "cross-strategy-links": [],
    })
    with patch("pipeline.phase_c_synthesize.chat") as mock_chat:
        mock_chat.return_value = llm_output
        result = build_strategy_synthesis(
            strategy_slug="strategies/strategy-1-renewable-grid",
            strategy_title="Strategy 1 — Renewable Grid",
            entities=SAMPLE_ENTITIES,
        )
    assert result["core-initiatives"] == ["initiatives/solarize-ann-arbor"]
    assert result["year-over-year-arc"].startswith("Residential")


def test_build_strategy_synthesis_handles_fenced_json():
    from pipeline.phase_c_synthesize import build_strategy_synthesis
    llm_output = "```json\n" + json.dumps({
        "core-initiatives": [], "core-actors": [],
        "year-over-year-arc": "—", "open-questions": [], "cross-strategy-links": [],
    }) + "\n```"
    with patch("pipeline.phase_c_synthesize.chat") as mock_chat:
        mock_chat.return_value = llm_output
        result = build_strategy_synthesis(
            strategy_slug="strategies/strategy-1-renewable-grid",
            strategy_title="Strategy 1 — Renewable Grid",
            entities=SAMPLE_ENTITIES,
        )
    assert result["core-initiatives"] == []


def test_build_strategy_synthesis_returns_empty_skeleton_on_api_failure():
    from pipeline.phase_c_synthesize import build_strategy_synthesis
    with patch("pipeline.phase_c_synthesize.chat") as mock_chat:
        mock_chat.side_effect = Exception("api error")
        result = build_strategy_synthesis(
            strategy_slug="strategies/strategy-1-renewable-grid",
            strategy_title="Strategy 1 — Renewable Grid",
            entities=SAMPLE_ENTITIES,
        )
    assert "core-initiatives" in result
    assert result["core-initiatives"] == []


STRATEGY_FIXTURE = """---
title: "Strategy 1 — Renewable Grid"
type: strategy
slug: strategies/strategy-1-renewable-grid
---

This strategy focuses on grid-scale renewable energy and rooftop solar.
The Solarize program is the flagship initiative. ([[sources/cap/cap-2020|cap-2020]])
"""


def test_write_strategy_synthesis_injects_synthesis_block(tmp_path):
    from pipeline.phase_c_synthesize import write_strategy_synthesis
    page = tmp_path / "strategy-1-renewable-grid.md"
    page.write_text(STRATEGY_FIXTURE, encoding="utf-8")

    synthesis = {
        "core-initiatives": ["initiatives/solarize-ann-arbor"],
        "core-actors": ["actors/glrea"],
        "year-over-year-arc": "Residential solar grew 31% Y1→Y2.",
        "open-questions": ["5MW Y3 target on track?"],
        "cross-strategy-links": [],
    }
    write_strategy_synthesis(str(page), synthesis, run_date="2026-06-26")
    text = page.read_text(encoding="utf-8")

    # Synthesis block lives in frontmatter
    assert "synthesis:" in text
    assert "core-initiatives:" in text
    assert "initiatives/solarize-ann-arbor" in text
    assert "last-rebuilt: '2026-06-26'" in text or 'last-rebuilt: "2026-06-26"' in text

    # Prose body is preserved
    assert "This strategy focuses on grid-scale renewable energy" in text
    assert "Solarize program is the flagship initiative" in text


def test_write_strategy_synthesis_overwrites_existing_block(tmp_path):
    from pipeline.phase_c_synthesize import write_strategy_synthesis
    page = tmp_path / "s1.md"
    page.write_text(STRATEGY_FIXTURE, encoding="utf-8")
    write_strategy_synthesis(str(page),
        {"core-initiatives": ["initiatives/old"],
         "core-actors": [], "year-over-year-arc": "old",
         "open-questions": [], "cross-strategy-links": []},
        run_date="2026-06-01")
    write_strategy_synthesis(str(page),
        {"core-initiatives": ["initiatives/new"],
         "core-actors": [], "year-over-year-arc": "new",
         "open-questions": [], "cross-strategy-links": []},
        run_date="2026-06-26")
    text = page.read_text(encoding="utf-8")
    assert "initiatives/new" in text
    assert "initiatives/old" not in text
    # Prose body still present and intact
    assert "Solarize program is the flagship initiative" in text


SAMPLE_STRATEGIES_DATA = {
    "strategies/strategy-1-renewable-grid": {
        "title": "Strategy 1 — Renewable Grid",
        "synthesis": {
            "core-initiatives": ["initiatives/solarize-ann-arbor"],
            "core-actors": ["actors/glrea"],
            "year-over-year-arc": "Residential solar grew 31% Y1→Y2.",
            "open-questions": ["DTE intervention outcomes pending"],
            "cross-strategy-links": ["initiatives/bryant-neighborhood-decarbonization"],
        },
    },
    "strategies/strategy-2-electrification": {
        "title": "Strategy 2 — Electrification",
        "synthesis": {
            "core-initiatives": ["initiatives/electrification-campaign"],
            "core-actors": ["actors/rmi"],
            "year-over-year-arc": "Contractor cohort launched Y2.",
            "open-questions": ["Heat pump adoption uptake?"],
            "cross-strategy-links": [],
        },
    },
}


def test_build_digest_narrative_calls_anthropic():
    from pipeline.phase_c_synthesize import build_digest_narrative
    narrative_text = (
        "## Cross-strategy synthesis\n\n"
        "Strategy 1 has built a 1.7MW residential rooftop base anchored by "
        "[[initiatives/solarize-ann-arbor]]...\n"
    )
    with patch("pipeline.phase_c_synthesize.chat") as mock_chat:
        mock_chat.return_value = narrative_text
        result = build_digest_narrative(strategies_data=SAMPLE_STRATEGIES_DATA)
    assert "Strategy 1" in result
    assert "[[initiatives/solarize-ann-arbor]]" in result


def test_build_digest_narrative_returns_placeholder_on_failure():
    from pipeline.phase_c_synthesize import build_digest_narrative
    with patch("pipeline.phase_c_synthesize.chat") as mock_chat:
        mock_chat.side_effect = Exception("api error")
        result = build_digest_narrative(strategies_data=SAMPLE_STRATEGIES_DATA)
    # Falls back to a placeholder rather than crashing the synthesis run
    assert "Cross-strategy synthesis" in result


def test_assemble_digest_combines_all_sections():
    from pipeline.phase_c_synthesize import assemble_digest
    text = assemble_digest(
        narrative="## Cross-strategy synthesis\n\nStrategy 1 ...\n",
        strategies_data=SAMPLE_STRATEGIES_DATA,
        delta={"date": "2026-06-26", "source_uuid": "a2zero-year2"},
        run_date="2026-06-26",
        sources_count=3,
        entity_count=399,
    )
    # Frontmatter
    assert text.startswith("---\n")
    assert "generated-by: synthesize_wiki" in text
    assert "last-rebuilt: '2026-06-26'" in text or 'last-rebuilt: "2026-06-26"' in text
    # Narrative section
    assert "Cross-strategy synthesis" in text
    # Entity map section
    assert "## Strategy entity map" in text
    assert "[[initiatives/solarize-ann-arbor|Solarize Ann Arbor]]" in text
    # Recent delta section
    assert "## Recent delta" in text
    assert "a2zero-year2" in text


def test_write_digest_writes_to_vault_root(tmp_path):
    from pipeline.phase_c_synthesize import write_digest
    (tmp_path / "wiki").mkdir()
    out = write_digest(wiki_root=str(tmp_path / "wiki"), content="# Hello digest")
    assert (tmp_path / "wiki" / "digest.md").read_text(encoding="utf-8") == "# Hello digest"
    assert out.endswith("wiki/digest.md")


def _setup_full_fixture(tmp_path):
    """Stage a minimal but complete wiki fixture for end-to-end orchestration."""
    import shutil
    root = tmp_path / "wiki"
    shutil.copytree("tests/fixtures/synthesize_wiki/wiki", root)
    (root / "strategies").mkdir(parents=True, exist_ok=True)
    (root / "strategies" / "strategy-1-renewable-grid.md").write_text(
        STRATEGY_FIXTURE, encoding="utf-8")
    (root / "log.md").write_text(LOG_FIXTURE, encoding="utf-8")
    return root


def test_synthesize_wiki_orchestrates_end_to_end(tmp_path):
    from pipeline.phase_c_synthesize import synthesize_wiki

    root = _setup_full_fixture(tmp_path)
    strategy_llm_output = json.dumps({
        "core-initiatives": ["initiatives/solarize-ann-arbor"],
        "core-actors": ["actors/glrea"],
        "year-over-year-arc": "Residential solar grew 31% Y1→Y2.",
        "open-questions": [],
        "cross-strategy-links": [],
    })
    narrative_output = "## Cross-strategy synthesis\n\nStrategy 1 has solarized 430+ homes.\n"

    with patch("pipeline.phase_c_synthesize.chat") as mock_chat:
        # Writer calls only — validators are deterministic and the fixture is clean
        # so no Reviser calls fire. Call order: 1 strategy synth + 1 narrative.
        mock_chat.side_effect = [strategy_llm_output, narrative_output]

        result = synthesize_wiki(
            wiki_root=str(root),
            strategies=["strategies/strategy-1-renewable-grid"],
        )

    assert result["strategies_rebuilt"] == ["strategies/strategy-1-renewable-grid"]
    assert (root / "digest.md").exists()
    digest_text = (root / "digest.md").read_text(encoding="utf-8")
    assert "Strategy 1 has solarized 430+ homes" in digest_text
    strategy_text = (root / "strategies" / "strategy-1-renewable-grid.md").read_text(encoding="utf-8")
    assert "synthesis:" in strategy_text
    assert "Solarize program is the flagship initiative" in strategy_text  # prose preserved
