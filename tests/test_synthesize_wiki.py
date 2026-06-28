# tests/test_synthesize_wiki.py


def test_module_imports():
    """Smoke test: the module exists and exposes the expected public API."""
    from pipeline import synthesize_wiki
    assert hasattr(synthesize_wiki, "synthesize_wiki")
    assert callable(synthesize_wiki.synthesize_wiki)
    assert hasattr(synthesize_wiki, "ALL_STRATEGIES")
    assert len(synthesize_wiki.ALL_STRATEGIES) == 7


def test_gather_strategy_entities_filters_by_strategy(tmp_path):
    """Returns only entities tagged to the given strategy."""
    import shutil
    from pipeline.synthesize_wiki import gather_strategy_entities

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
    from pipeline.synthesize_wiki import gather_strategy_entities
    shutil.copytree("tests/fixtures/synthesize_wiki/wiki", tmp_path / "wiki")
    entities = gather_strategy_entities(
        wiki_root=str(tmp_path / "wiki"),
        strategy_slug="strategies/strategy-99-nonexistent",
    )
    assert entities == []


LOG_FIXTURE = """# Ingest Log

## 2026-06-15 — cap-2020
Pass 3 complete — index rebuilt.

## 2026-06-25 — a2zero-year1
Pass 3 complete — index rebuilt.

## 2026-06-26 — a2zero-year2
Pass 3 complete — index rebuilt.
"""


def test_extract_recent_delta_returns_last_entry(tmp_path):
    from pipeline.synthesize_wiki import extract_recent_delta
    log_path = tmp_path / "log.md"
    log_path.write_text(LOG_FIXTURE, encoding="utf-8")
    delta = extract_recent_delta(str(log_path))
    assert delta["source_uuid"] == "a2zero-year2"
    assert delta["date"] == "2026-06-26"


def test_extract_recent_delta_handles_empty_log(tmp_path):
    from pipeline.synthesize_wiki import extract_recent_delta
    log_path = tmp_path / "log.md"
    log_path.write_text("# Ingest Log\n", encoding="utf-8")
    delta = extract_recent_delta(str(log_path))
    assert delta == {}
