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
