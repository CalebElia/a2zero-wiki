import json
from pathlib import Path
from pipeline.comprehend import empty_plan, write_integration_plan, load_integration_plan


def test_empty_plan_has_all_required_fields():
    plan = empty_plan()
    assert plan["strategies-touched"] == []
    assert plan["extends"] == []
    assert plan["new-entities"] == []
    assert plan["retrieve-for-context"] == []
    assert plan["theme-connections"] == []


def test_write_and_load_integration_plan_roundtrip(tmp_path):
    plans_dir = tmp_path / "integration-plans"
    plan = {
        "source-uuid": "test-source",
        "generated-at": "2026-06-29T18:00:00Z",
        "digest-rebuilt": "2026-06-29",
        "strategies-touched": ["strategies/strategy-1-renewable-grid"],
        "extends": [{"slug": "initiatives/solarize", "new-data": "Year 3 totals"}],
        "new-entities": [],
        "retrieve-for-context": ["initiatives/solarize"],
        "theme-connections": ["Grid capacity tied to electrification"],
    }
    out_path = write_integration_plan(plan, str(plans_dir))
    assert Path(out_path).exists()
    loaded = load_integration_plan(str(plans_dir), "test-source")
    assert loaded == plan


def test_load_integration_plan_returns_empty_when_missing(tmp_path):
    plans_dir = tmp_path / "integration-plans"
    plans_dir.mkdir()
    loaded = load_integration_plan(str(plans_dir), "nonexistent-source")
    # Falls back to empty plan rather than raising
    assert loaded["extends"] == []
    assert loaded["strategies-touched"] == []


from unittest.mock import patch
from pipeline.comprehend import build_integration_plan


def test_build_integration_plan_returns_empty_when_no_digest():
    """First-ingest path: no digest yet → empty plan, no LLM call."""
    with patch("pipeline.comprehend.chat") as mock_chat:
        plan = build_integration_plan(
            source_content="some source text",
            source_uuid="first-source",
            digest_content=None,
            run_date="2026-06-29",
        )
    assert mock_chat.call_count == 0  # No LLM call when digest is absent
    assert plan["source-uuid"] == "first-source"
    assert plan["extends"] == []
    assert plan["strategies-touched"] == []


def test_build_integration_plan_calls_llm_and_parses_json():
    llm_output = json.dumps({
        "strategies-touched": ["strategies/strategy-1-renewable-grid"],
        "extends": [{"slug": "initiatives/solarize-ann-arbor", "new-data": "Y3 totals"}],
        "new-entities": [],
        "retrieve-for-context": ["initiatives/solarize-ann-arbor"],
        "theme-connections": [],
    })
    with patch("pipeline.comprehend.chat") as mock_chat:
        mock_chat.return_value = llm_output
        plan = build_integration_plan(
            source_content="source text",
            source_uuid="test-source",
            digest_content="# Wiki Digest\n\n## Cross-strategy synthesis\n...",
            run_date="2026-06-29",
        )
    assert mock_chat.call_count == 1
    assert plan["source-uuid"] == "test-source"
    assert "digest-rebuilt" in plan
    assert plan["strategies-touched"] == ["strategies/strategy-1-renewable-grid"]
    assert plan["extends"][0]["slug"] == "initiatives/solarize-ann-arbor"


def test_build_integration_plan_handles_fenced_json():
    llm_output = "```json\n" + json.dumps({
        "strategies-touched": [],
        "extends": [],
        "new-entities": [],
        "retrieve-for-context": [],
        "theme-connections": [],
    }) + "\n```"
    with patch("pipeline.comprehend.chat") as mock_chat:
        mock_chat.return_value = llm_output
        plan = build_integration_plan(
            source_content="x",
            source_uuid="t",
            digest_content="d",
            run_date="2026-06-29",
        )
    assert plan["extends"] == []


def test_build_integration_plan_hard_fails_on_llm_error_when_digest_present():
    """Per spec: digest exists + LLM fails → hard fail (do not silently degrade)."""
    with patch("pipeline.comprehend.chat") as mock_chat:
        mock_chat.side_effect = Exception("API error")
        try:
            build_integration_plan(
                source_content="source",
                source_uuid="test",
                digest_content="# Digest",
                run_date="2026-06-29",
            )
        except Exception as e:
            assert "comprehend" in str(e).lower() or "API error" in str(e)
            return
        raise AssertionError("Expected hard fail, got silent return")


from pipeline.comprehend import validate_plan_slugs


def test_validate_plan_slugs_strips_ghost_entries(tmp_path):
    """Plan with slugs pointing to nonexistent pages → ghosts removed."""
    # Set up a tiny wiki with one real entity
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "initiatives" / "solarize.md").write_text("---\ntype: initiative\n---\n", encoding="utf-8")

    plan = {
        "source-uuid": "test",
        "generated-at": "2026-06-29",
        "digest-rebuilt": "2026-06-29",
        "strategies-touched": [],
        "extends": [
            {"slug": "initiatives/solarize", "new-data": "real"},
            {"slug": "initiatives/ghost-entity", "new-data": "fake"},
        ],
        "new-entities": [],
        "retrieve-for-context": ["initiatives/solarize", "initiatives/another-ghost"],
        "theme-connections": [],
    }
    cleaned = validate_plan_slugs(plan, wiki_root=str(wiki), aliases={})
    # extends: ghost dropped
    extend_slugs = [e["slug"] for e in cleaned["extends"]]
    assert extend_slugs == ["initiatives/solarize"]
    # retrieve-for-context: ghost dropped
    assert cleaned["retrieve-for-context"] == ["initiatives/solarize"]
    # new-entities: untouched (these are proposed pages that don't exist YET)
    assert cleaned["new-entities"] == []


def test_validate_plan_slugs_resolves_aliases(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "actors").mkdir(parents=True)
    (wiki / "actors" / "office-of-sustainability-and-innovations.md").write_text(
        "---\ntype: actor\n---\n", encoding="utf-8"
    )
    aliases = {
        "a2zero-office": {
            "canonical": "actors/office-of-sustainability-and-innovations",
            "type": "actor", "aliases": [], "relationship": "name-variant",
        }
    }
    plan = {
        "source-uuid": "t", "generated-at": "x", "digest-rebuilt": "y",
        "strategies-touched": [], "new-entities": [], "theme-connections": [],
        "extends": [{"slug": "actors/a2zero-office", "new-data": "x"}],
        "retrieve-for-context": ["actors/a2zero-office"],
    }
    cleaned = validate_plan_slugs(plan, wiki_root=str(wiki), aliases=aliases)
    assert cleaned["extends"][0]["slug"] == "actors/office-of-sustainability-and-innovations"
    assert cleaned["retrieve-for-context"] == ["actors/office-of-sustainability-and-innovations"]


from pipeline.comprehend import load_retrieved_bodies, RETRIEVE_TOKEN_BUDGET


def test_load_retrieved_bodies_returns_under_budget(tmp_path):
    """Small wiki, all pages fit → all returned."""
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    for slug_stem in ["a", "b", "c"]:
        (wiki / "initiatives" / f"{slug_stem}.md").write_text(
            f"---\ntype: initiative\n---\nShort body {slug_stem}\n", encoding="utf-8"
        )
    plan = {
        "extends": [],
        "retrieve-for-context": ["initiatives/a", "initiatives/b", "initiatives/c"],
        "theme-connections": [],
    }
    bodies = load_retrieved_bodies(plan, str(wiki))
    assert set(bodies.keys()) == {"initiatives/a", "initiatives/b", "initiatives/c"}
    for slug, body in bodies.items():
        assert "Short body" in body


def test_load_retrieved_bodies_prioritizes_extends_when_over_budget(tmp_path, monkeypatch):
    """When over budget: extends entries kept first, others dropped."""
    # Shrink budget for the test
    monkeypatch.setattr("pipeline.comprehend.RETRIEVE_TOKEN_BUDGET", 200)
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    # Create pages where each body is roughly ~100 tokens (400+ chars)
    big_body = "word " * 200  # ~200 tokens
    for stem in ["in-extends", "not-in-extends-1", "not-in-extends-2"]:
        (wiki / "initiatives" / f"{stem}.md").write_text(
            f"---\ntype: initiative\n---\n{big_body}\n", encoding="utf-8"
        )
    plan = {
        "extends": [{"slug": "initiatives/in-extends", "new-data": "x"}],
        "retrieve-for-context": [
            "initiatives/not-in-extends-1",
            "initiatives/in-extends",
            "initiatives/not-in-extends-2",
        ],
        "theme-connections": [],
    }
    bodies = load_retrieved_bodies(plan, str(wiki))
    # Extends entry is included; one or both of the others gets dropped
    assert "initiatives/in-extends" in bodies
    total_chars = sum(len(b) for b in bodies.values())
    assert total_chars < 200 * 5  # under budget (4 chars/token heuristic)


def test_load_retrieved_bodies_skips_missing_files(tmp_path):
    """Ghost slugs in retrieve-for-context are silently dropped."""
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "initiatives" / "real.md").write_text("---\ntype: initiative\n---\nbody\n", encoding="utf-8")
    plan = {
        "extends": [],
        "retrieve-for-context": ["initiatives/real", "initiatives/ghost"],
        "theme-connections": [],
    }
    bodies = load_retrieved_bodies(plan, str(wiki))
    assert set(bodies.keys()) == {"initiatives/real"}
