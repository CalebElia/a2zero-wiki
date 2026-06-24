import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

MOCK_PLAN_RESPONSE = {
    "page_type": "plan",
    "slug": "plans/cap-2020",
    "frontmatter": {
        "type": "plan",
        "title": "Ann Arbor A2Zero Living Carbon Neutrality Plan",
        "published": "2020-04",
        "jurisdiction": "ann-arbor",
        "source": "[[silver/cap/cap-2020]]",
        "overarching-goal": "Achieve community-wide carbon neutrality by 2030.",
        "party-responsible": "[[actors/osi]]",
        "strategies": [
            "[[strategies/strategy-1-renewable-grid]]",
            "[[strategies/strategy-2-electrification]]",
            "[[strategies/strategy-3-building-efficiency]]",
            "[[strategies/strategy-4-vmt-reduction]]",
            "[[strategies/strategy-5-materials-waste]]",
            "[[strategies/strategy-6-resilience]]",
            "[[strategies/strategy-7-engagement]]",
        ],
        "tags": ["carbon-neutrality", "cap", "2030", "a2zero"],
        "last-updated": "2026-06-23",
    },
    "body": "The A2Zero Living Carbon Neutrality Plan commits Ann Arbor to achieving community-wide carbon neutrality by 2030. ([[silver/cap/cap-2020|cap-2020]])",
}

SAMPLE_SILVER = """---
source_type: cap
---

# Ann Arbor A2Zero Living Carbon Neutrality Plan

Ann Arbor commits to achieving carbon neutrality by 2030.

## Introduction

This is the plan.
"""


@patch("pipeline.plan_extractor.anthropic.Anthropic")
def test_extract_plan_page_writes_file(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=json.dumps(MOCK_PLAN_RESPONSE))]
    mock_client.messages.create.return_value = mock_response

    from pipeline.plan_extractor import extract_plan_page
    result = extract_plan_page(
        silver_content=SAMPLE_SILVER,
        source_uuid="cap-2020",
        source_rel_path="silver/cap/cap-2020",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is not None
    assert result["page_type"] == "plan"
    plan_file = tmp_path / "plans" / "cap-2020.md"
    assert plan_file.exists()
    content = plan_file.read_text()
    assert "type: plan" in content
    assert "A2Zero Living Carbon Neutrality Plan" in content
    assert "[[silver/cap/cap-2020]]" in content


@patch("pipeline.plan_extractor.anthropic.Anthropic")
def test_extract_plan_page_skips_if_exists(mock_anthropic_class, tmp_path):
    """Plan extractor is idempotent — skip if plan page already exists."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client

    # Pre-create the plan file
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "cap-2020.md").write_text("---\ntype: plan\n---\n\nExisting plan.\n")

    from pipeline.plan_extractor import extract_plan_page
    result = extract_plan_page(
        silver_content=SAMPLE_SILVER,
        source_uuid="cap-2020",
        source_rel_path="silver/cap/cap-2020",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is None
    assert not mock_client.messages.create.called


@patch("pipeline.plan_extractor.anthropic.Anthropic")
def test_extract_plan_page_returns_none_on_api_failure(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API error")

    from pipeline.plan_extractor import extract_plan_page
    result = extract_plan_page(
        silver_content=SAMPLE_SILVER,
        source_uuid="cap-2020",
        source_rel_path="silver/cap/cap-2020",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )
    assert result is None


@patch("pipeline.plan_extractor.anthropic.Anthropic")
def test_extract_plan_page_rejects_wrong_type(mock_anthropic_class, tmp_path):
    """If LLM returns wrong page_type, return None without writing file."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    wrong_response = {**MOCK_PLAN_RESPONSE, "page_type": "initiative"}
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=json.dumps(wrong_response))]
    mock_client.messages.create.return_value = mock_response

    from pipeline.plan_extractor import extract_plan_page
    result = extract_plan_page(
        silver_content=SAMPLE_SILVER,
        source_uuid="cap-2020",
        source_rel_path="silver/cap/cap-2020",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )
    assert result is None
    assert not (tmp_path / "plans" / "cap-2020.md").exists()
