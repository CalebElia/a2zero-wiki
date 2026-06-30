import json
import pytest
from unittest.mock import MagicMock, patch, call


MOCK_SYNTHESIS = {
    "overview": {
        "slug": "overviews/cap-2020",
        "frontmatter": {
            "type": "overview",
            "title": "Ann Arbor A2Zero Living Carbon Neutrality Plan",
            "source-type": "strategic-plan",
            "source-ref": "[[sources/cap/cap-2020]]",
            "date": "2020-04",
            "scope": "community-wide",
            "structure": ["Executive Summary", "Seven Strategies", "Implementation Actions"],
            "tags": ["cap", "a2zero", "carbon-neutrality"],
            "source-first-seen": "[[sources/cap/cap-2020]]",
            "last-updated": "2026-06-23",
        },
        "body": "The A2Zero plan is Ann Arbor's roadmap to carbon neutrality by 2030. ([[sources/cap/cap-2020|cap-2020]])",
    },
    "strategy_bodies": [
        {
            "slug": "strategies/strategy-1-renewable-grid",
            "body": "Strategy 1 focuses on 100% renewable electricity via CCA and solar programs. ([[sources/cap/cap-2020|cap-2020]])",
        },
        {
            "slug": "strategies/strategy-2-electrification",
            "body": "Strategy 2 covers electric vehicle adoption and charging infrastructure. ([[sources/cap/cap-2020|cap-2020]])",
        },
        {
            "slug": "strategies/strategy-3-building-efficiency",
            "body": "Strategy 3 addresses building energy efficiency and retrofits. ([[sources/cap/cap-2020|cap-2020]])",
        },
        {
            "slug": "strategies/strategy-4-vmt-reduction",
            "body": "Strategy 4 focuses on reducing vehicle miles traveled through transit and active transportation. ([[sources/cap/cap-2020|cap-2020]])",
        },
        {
            "slug": "strategies/strategy-5-materials-waste",
            "body": "Strategy 5 addresses materials management, waste reduction, and circular economy. ([[sources/cap/cap-2020|cap-2020]])",
        },
        {
            "slug": "strategies/strategy-6-resilience",
            "body": "Strategy 6 builds climate resilience and adaptability. ([[sources/cap/cap-2020|cap-2020]])",
        },
        {
            "slug": "strategies/strategy-7-engagement",
            "body": "Strategy 7 promotes community engagement and behavior change. ([[sources/cap/cap-2020|cap-2020]])",
        },
    ],
    "stub_pages": [
        {
            "type": "initiative",
            "title": "Community Choice Aggregation",
            "slug": "initiatives/community-choice-aggregation",
            "parent-strategy": "strategy-1-renewable-grid",
            "one-liner": "Municipal bulk renewable energy purchasing for all residents",
        },
    ],
    "topic_candidates": [
        {"title": "Environmental Justice", "rationale": "Equity framing spans Strategies 1, 3, and 7"},
    ],
    "log_summary": "Ingested cap-2020: 7 strategies, 44 actions, community-wide 2030 target.",
}

MOCK_CRITIQUE = {
    "accuracy_issues": [],
    "completeness_gaps": [],
    "format_issues": [],
    "redundancy_issues": [],
    "overall_score": 9,
    "proceed_to_edit": True,
}



def _strategy_stub(tmp_path):
    (tmp_path / "strategies").mkdir(exist_ok=True)
    (tmp_path / "strategies" / "strategy-1-renewable-grid.md").write_text(
        "---\ntype: strategy\ntitle: Strategy 1\n---\n\n<!-- stub -->\n"
    )
    (tmp_path / "strategies" / "strategy-2-electrification.md").write_text(
        "---\ntype: strategy\ntitle: Strategy 2\n---\n\n<!-- stub -->\n"
    )
    (tmp_path / "strategies" / "strategy-3-building-efficiency.md").write_text(
        "---\ntype: strategy\ntitle: Strategy 3\n---\n\n<!-- stub -->\n"
    )
    (tmp_path / "strategies" / "strategy-4-vmt-reduction.md").write_text(
        "---\ntype: strategy\ntitle: Strategy 4\n---\n\n<!-- stub -->\n"
    )
    (tmp_path / "strategies" / "strategy-5-materials-waste.md").write_text(
        "---\ntype: strategy\ntitle: Strategy 5\n---\n\n<!-- stub -->\n"
    )
    (tmp_path / "strategies" / "strategy-6-resilience.md").write_text(
        "---\ntype: strategy\ntitle: Strategy 6\n---\n\n<!-- stub -->\n"
    )
    (tmp_path / "strategies" / "strategy-7-engagement.md").write_text(
        "---\ntype: strategy\ntitle: Strategy 7\n---\n\n<!-- stub -->\n"
    )
    (tmp_path / "overviews").mkdir(exist_ok=True)


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_synthesize_source_makes_three_calls(mock_stream_chat, tmp_path):
    """Writer → Evaluator → Editor: exactly 3 API calls on the happy path."""
    mock_stream_chat.side_effect = [
        json.dumps(MOCK_SYNTHESIS),   # Writer
        json.dumps(MOCK_CRITIQUE),    # Evaluator
        json.dumps(MOCK_SYNTHESIS),   # Editor
    ]
    _strategy_stub(tmp_path)

    from pipeline.pass1b_synthesize import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDocument body.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is not None
    assert mock_stream_chat.call_count == 3


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_synthesize_source_writes_overview(mock_stream_chat, tmp_path):
    mock_stream_chat.side_effect = [
        json.dumps(MOCK_SYNTHESIS),
        json.dumps(MOCK_CRITIQUE),
        json.dumps(MOCK_SYNTHESIS),
    ]
    _strategy_stub(tmp_path)

    from pipeline.pass1b_synthesize import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDocument body.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is not None
    overview_path = tmp_path / "overviews" / "cap-2020.md"
    assert overview_path.exists()
    content = overview_path.read_text()
    assert "Ann Arbor A2Zero" in content
    assert "type: overview" in content


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_synthesize_source_appends_strategy_body(mock_stream_chat, tmp_path):
    mock_stream_chat.side_effect = [
        json.dumps(MOCK_SYNTHESIS),
        json.dumps(MOCK_CRITIQUE),
        json.dumps(MOCK_SYNTHESIS),
    ]
    _strategy_stub(tmp_path)
    stub = tmp_path / "strategies" / "strategy-1-renewable-grid.md"

    from pipeline.pass1b_synthesize import synthesize_source
    synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDoc.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    content = stub.read_text()
    assert "Strategy 1 focuses on 100% renewable electricity" in content


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_synthesize_source_skips_if_overview_exists(mock_stream_chat, tmp_path):
    (tmp_path / "overviews").mkdir()
    (tmp_path / "overviews" / "cap-2020.md").write_text("existing overview")

    from pipeline.pass1b_synthesize import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDoc.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is None
    assert not mock_stream_chat.called


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_evaluator_proceed_false_reruns_writer(mock_stream_chat, tmp_path):
    """If evaluator says proceed_to_edit=False, Writer re-runs, then Editor runs."""
    bad_critique = {**MOCK_CRITIQUE, "overall_score": 2, "proceed_to_edit": False}
    mock_stream_chat.side_effect = [
        json.dumps(MOCK_SYNTHESIS),   # Writer (first attempt)
        json.dumps(bad_critique),     # Evaluator — says don't proceed
        json.dumps(MOCK_SYNTHESIS),   # Writer (retry)
        json.dumps(MOCK_SYNTHESIS),   # Editor
    ]
    _strategy_stub(tmp_path)

    from pipeline.pass1b_synthesize import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDoc.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is not None
    assert mock_stream_chat.call_count == 4


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_editor_retries_on_validation_failure(mock_stream_chat, tmp_path):
    """Editor output that fails structural validation causes Editor to retry."""
    bad_editor_output = {"overview": None, "strategy_bodies": []}
    mock_stream_chat.side_effect = [
        json.dumps(MOCK_SYNTHESIS),       # Writer
        json.dumps(MOCK_CRITIQUE),        # Evaluator
        json.dumps(bad_editor_output),    # Editor attempt 1 — fails validation
        json.dumps(MOCK_SYNTHESIS),       # Editor attempt 2 — passes
    ]
    _strategy_stub(tmp_path)

    from pipeline.pass1b_synthesize import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDoc.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
        max_retries=2,
    )

    assert result is not None
    assert mock_stream_chat.call_count == 4


def test_validate_synthesis_output_catches_missing_overview(tmp_path):
    from pipeline.pass1b_synthesize import _validate_synthesis_output
    errors = _validate_synthesis_output(
        {"strategy_bodies": []}, source_uuid="cap-2020", wiki_root=str(tmp_path)
    )
    assert any("overview" in e for e in errors)


def test_validate_synthesis_output_catches_bad_source_ref(tmp_path):
    from pipeline.pass1b_synthesize import _validate_synthesis_output
    result = {
        "overview": {
            "slug": "overviews/cap-2020",
            "frontmatter": {
                "type": "overview",
                "title": "Test",
                "source-ref": "sources/cap/cap-2020",  # missing [[...]] wikilink format
            },
            "body": "Some body.",
        },
        "strategy_bodies": [],
    }
    errors = _validate_synthesis_output(result, source_uuid="cap-2020", wiki_root=str(tmp_path))
    assert any("source-ref" in e for e in errors)


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_synthesize_source_integrates_existing_strategy_body(mock_stream_chat, tmp_path):
    """When a strategy page already has real content, body is replaced not appended."""
    mock_stream_chat.side_effect = [
        json.dumps(MOCK_SYNTHESIS),
        json.dumps(MOCK_CRITIQUE),
        json.dumps(MOCK_SYNTHESIS),
    ]
    _strategy_stub(tmp_path)
    # Write existing real content to strategy page (not a stub comment)
    strat_path = tmp_path / "strategies" / "strategy-1-renewable-grid.md"
    strat_path.write_text(
        "---\ntype: strategy\ntitle: Strategy 1\n---\n\nExisting synthesis paragraph.\n"
    )
    (tmp_path / "overviews").mkdir(exist_ok=True)

    from pipeline.pass1b_synthesize import synthesize_source
    synthesize_source(
        source_content="---\nuuid: annual-report-year1\n---\n\nNew content.",
        source_uuid="annual-report-year1",
        source_rel_path="sources/annual-reports/year1",
        source_type="annual-report",
        wiki_root=str(tmp_path),
        run_date="2026-06-24",
    )

    result = strat_path.read_text()
    # Integrated body from MOCK_SYNTHESIS should be present
    assert "Strategy 1 focuses on 100% renewable electricity" in result
    # Old body should NOT appear alongside new body (replacement, not append)
    assert result.count("Existing synthesis paragraph.") == 0


def test_replace_wiki_page_body_preserves_frontmatter(tmp_path):
    from pipeline.pass1b_synthesize import _replace_wiki_page_body
    page = tmp_path / "test.md"
    page.write_text("---\ntype: strategy\ntitle: Test\n---\n\nOld body.\n")
    _replace_wiki_page_body(str(page), "New integrated body.")
    content = page.read_text()
    assert "type: strategy" in content
    assert "New integrated body." in content
    assert "Old body." not in content


def test_validate_synthesis_output_catches_unknown_strategy_slug(tmp_path):
    from pipeline.pass1b_synthesize import _validate_synthesis_output
    (tmp_path / "strategies").mkdir()
    result = {
        "overview": {
            "slug": "overviews/cap-2020",
            "frontmatter": {
                "type": "overview",
                "title": "Test",
                "source-ref": "[[sources/cap/cap-2020]]",
            },
            "body": "Body.",
        },
        "strategy_bodies": [
            {"slug": "strategies/strategy-8-invented", "body": "Body."}
        ],
    }
    errors = _validate_synthesis_output(result, source_uuid="cap-2020", wiki_root=str(tmp_path))
    assert any("strategy-8-invented" in e for e in errors)


def test_stub_creation_redirects_known_alias(tmp_path):
    """Pass 1.5: a stub whose slug is a known alias should write to the canonical path."""
    import json
    from unittest.mock import patch
    from pipeline.pass1b_synthesize import _write_synthesis

    # Set up minimal wiki structure
    (tmp_path / "strategies").mkdir()
    (tmp_path / "actors").mkdir()
    (tmp_path / "overviews").mkdir()

    # Set up alias registry: "office-of-sustainability" → canonical "actors/osi"
    aliases_path = tmp_path / "aliases.json"
    aliases = {
        "office-of-sustainability": {
            "canonical": "actors/osi",
            "type": "actor",
            "aliases": ["Office of Sustainability"],
            "relationship": "name-variant",
        }
    }
    aliases_path.write_text(json.dumps(aliases), encoding="utf-8")

    # Synthesis result proposing the alias slug
    result = {
        "overview": {
            "slug": "overviews/test-source",
            "frontmatter": {
                "type": "overview",
                "title": "Test Source",
                "source-ref": "[[sources/cap/cap-2020]]",
                "source-first-seen": "[[sources/cap/cap-2020]]",
            },
            "body": "Overview body.",
        },
        "strategy_bodies": [],
        "stub_pages": [
            {
                "slug": "actors/office-of-sustainability",
                "type": "actor",
                "title": "Office of Sustainability",
                "one-liner": "Leads A2Zero.",
            }
        ],
        "topic_candidates": [],
        "log_summary": "Test run.",
    }

    with patch("pipeline.pass1b_synthesize.alias_registry_path", str(aliases_path)):
        _write_synthesis(
            result=result,
            wiki_root=str(tmp_path),
            source_uuid="cap-2020",
            source_rel_path="sources/cap/cap-2020",
            run_date="2026-06-25",
        )

    # Stub should be written at the canonical path, NOT the alias path
    assert (tmp_path / "actors" / "osi.md").exists(), "Canonical osi.md should have been created"
    assert not (tmp_path / "actors" / "office-of-sustainability.md").exists(), "Alias path should not exist"


@patch("pipeline.pass1b_synthesize.stream_chat")
def test_synthesize_source_injects_integration_plan_and_digest(mock_stream_chat, tmp_path):
    """Plan + digest replace the legacy strategy-body integration block."""
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
    editor_final = {
        "overview": {
            "slug": "overviews/test",
            "frontmatter": {
                "type": "overview",
                "title": "T",
                "source-ref": "[[sources/test/test]]",
            },
            "body": "Edited overview",
        },
        "strategy_bodies": [
            {"slug": f"strategies/strategy-{i}-x", "body": "edited"} for i in range(1, 8)
        ],
        "stub_pages": [],
        "log_summary": "edited",
    }
    mock_stream_chat.side_effect = [
        json.dumps(writer_draft),
        json.dumps({"proceed_to_edit": True, "overall_score": 9}),
        json.dumps(editor_final),
    ]
    # Stage minimum strategy stubs so validate_synthesis_output passes
    strategies = tmp_path / "strategies"
    strategies.mkdir()
    for i in range(1, 8):
        (strategies / f"strategy-{i}-x.md").write_text(
            "---\ntype: strategy\n---\n", encoding="utf-8"
        )
    (tmp_path / "overviews").mkdir()
    (tmp_path / "sources" / "test").mkdir(parents=True)

    plan = {
        "source-uuid": "test",
        "extends": [{"slug": "x", "new-data": "y"}],
        "strategies-touched": ["strategies/strategy-1-x"],
        "new-entities": [],
        "retrieve-for-context": [],
        "theme-connections": [],
    }
    digest = "# Wiki Digest\n\nDigest content here.\n"

    from pipeline.pass1b_synthesize import synthesize_source
    synthesize_source(
        source_content="---\nuuid: test\n---\nSource body",
        source_uuid="test",
        source_rel_path="sources/test/test",
        source_type="test",
        wiki_root=str(tmp_path),
        run_date="2026-06-29",
        integration_plan=plan,
        digest_content=digest,
    )

    # The first call (Writer) should have received the plan + digest in its user content
    first_call_user_content = mock_stream_chat.call_args_list[0].kwargs["messages"][0]["content"]
    # Content is a list with one cache_control block whose 'text' contains both
    text = first_call_user_content[0]["text"] if isinstance(first_call_user_content, list) else first_call_user_content
    assert "INTEGRATION PLAN" in text
    assert "WIKI DIGEST" in text
    assert "Digest content here" in text
