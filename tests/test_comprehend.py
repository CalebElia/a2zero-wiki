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
