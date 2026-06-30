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
