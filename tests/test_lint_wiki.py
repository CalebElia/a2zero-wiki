# tests/test_lint_wiki.py
import pytest
from pathlib import Path


def _make_wiki(tmp_path: Path) -> Path:
    """Create a minimal wiki for lint testing."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "actors").mkdir()
    (wiki / "initiatives").mkdir()

    # Good page — has inbound link, valid wikilink
    (wiki / "actors" / "osi.md").write_text(
        "---\ntype: actor\ntitle: OSI\n---\n"
        "The OSI leads A2Zero. ([[sources/cap/cap-2020|cap-2020]])\n"
    )
    # Page with broken wikilink
    (wiki / "actors" / "broken.md").write_text(
        "---\ntype: actor\ntitle: Broken Actor\n---\n"
        "See [[actors/nonexistent]].\n"
    )
    # Orphaned page (no other page links to it)
    (wiki / "initiatives" / "orphan-program.md").write_text(
        "---\ntype: initiative\ntitle: Orphan Program\n---\n"
        "This initiative exists. ([[actors/osi|OSI]])\n"
    )
    # Index page linking to osi and broken
    (wiki / "index.md").write_text(
        "# Index\n- [[actors/osi|OSI]]\n- [[actors/broken|Broken]]\n"
    )
    return wiki


def test_structural_finds_broken_link(tmp_path):
    from pipeline.lint_wiki import structural_lint
    wiki = _make_wiki(tmp_path)
    findings = structural_lint(str(wiki))
    broken = [f for f in findings if f["type"] == "BROKEN_LINK"]
    assert any("actors/nonexistent" in f["detail"] for f in broken)


def test_structural_finds_orphan(tmp_path):
    from pipeline.lint_wiki import structural_lint
    wiki = _make_wiki(tmp_path)
    findings = structural_lint(str(wiki))
    orphans = [f for f in findings if f["type"] == "ORPHAN"]
    assert any("orphan-program" in f["page"] for f in orphans)


def test_structural_no_false_positive_for_osi(tmp_path):
    from pipeline.lint_wiki import structural_lint
    wiki = _make_wiki(tmp_path)
    findings = structural_lint(str(wiki))
    orphans = [f for f in findings if f["type"] == "ORPHAN"]
    assert not any("osi" in f["page"] for f in orphans)


def test_structural_skips_exempt_pages(tmp_path):
    from pipeline.lint_wiki import structural_lint
    wiki = _make_wiki(tmp_path)
    # index.md is exempt from orphan check
    findings = structural_lint(str(wiki))
    orphans = [f for f in findings if f["type"] == "ORPHAN"]
    assert not any(f["page"].endswith("index.md") for f in orphans)


def test_semantic_lint_calls_llm_for_candidates(tmp_path):
    """Stage 2 LLM verdict is called when Stage 1 fuzzy match finds candidates."""
    import json
    from unittest.mock import patch, MagicMock

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    actors = wiki / "actors"
    actors.mkdir()

    # Two pages with very similar titles — should trigger fuzzy candidate
    (actors / "osi.md").write_text(
        "---\ntype: actor\ntitle: Office of Sustainability and Innovations\n---\nLeads A2Zero.\n"
    )
    (actors / "office-of-sustainability.md").write_text(
        "---\ntype: actor\ntitle: Office of Sustainability\n---\nCity sustainability office.\n"
    )

    verdict = {"relationship": "same", "confidence": 0.92, "reasoning": "Same office."}
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(verdict))]

    with patch("pipeline.lint_wiki.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        from pipeline.lint_wiki import semantic_lint
        proposals = semantic_lint(str(wiki))

    assert len(proposals) == 1
    assert proposals[0]["type"] == "MERGE_PROPOSED"
    assert proposals[0]["confidence"] == 0.92


def test_parse_approved_proposals_finds_checked_merge(tmp_path):
    from pipeline.lint_wiki import _parse_approved_proposals
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "## Semantic Lint — 2026-06-25\n\n"
        "### [MERGE_PROPOSED] actors/osi.md + actors/office-of-sustainability.md\n"
        "- Confidence: 0.91\n"
        "- Reasoning: Same office.\n"
        "- Action: [x] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER\n",
        encoding="utf-8",
    )
    proposals = _parse_approved_proposals(str(rq))
    assert len(proposals) == 1
    assert proposals[0]["approved_action"] == "MERGE"
    assert proposals[0]["page_a"] == "actors/osi.md"


def test_rewrite_inbound_links(tmp_path):
    from pipeline.lint_wiki import _rewrite_inbound_links
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "actors").mkdir()
    (wiki / "actors" / "page.md").write_text(
        "See [[actors/old-slug]] and [[actors/old-slug|Old Name]].\n",
        encoding="utf-8",
    )
    n = _rewrite_inbound_links(str(wiki), "actors/old-slug.md", "actors/new-slug.md")
    assert n == 2
    content = (wiki / "actors" / "page.md").read_text()
    assert "actors/new-slug" in content
    assert "actors/old-slug" not in content
