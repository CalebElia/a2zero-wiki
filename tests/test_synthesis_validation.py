from pipeline.synthesis_validation import BrokenRef, ValidationReport
import json
from pathlib import Path
from pipeline.synthesis_validation import validate_synthesis


def test_broken_ref_dataclass():
    b = BrokenRef(slug="actors/foo", location="core-actors", display="Foo", context="")
    assert b.slug == "actors/foo"
    assert b.location == "core-actors"


def test_validation_report_is_clean_when_empty():
    report = ValidationReport(broken=[])
    assert report.is_clean is True


def test_validation_report_is_dirty_when_broken_present():
    report = ValidationReport(broken=[
        BrokenRef(slug="actors/foo", location="core-actors", display="Foo", context="")
    ])
    assert report.is_clean is False


def _make_wiki(tmp_path, actors=None, initiatives=None, locations=None):
    """Helper: create a minimal wiki with stub files for given slugs."""
    root = tmp_path / "wiki"
    for type_dir, slugs in [
        ("actors", actors or []),
        ("initiatives", initiatives or []),
        ("locations", locations or []),
    ]:
        d = root / type_dir
        d.mkdir(parents=True, exist_ok=True)
        for slug in slugs:
            (d / f"{slug}.md").write_text("---\ntype: actor\n---\n", encoding="utf-8")
    return root


def test_validate_synthesis_passes_when_all_slugs_exist(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"], initiatives=["bar"])
    synthesis = {
        "core-initiatives": ["initiatives/bar"],
        "core-actors": ["actors/foo"],
        "cross-strategy-links": [],
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases={})
    assert report.is_clean
    assert corrected["core-actors"] == ["actors/foo"]


def test_validate_synthesis_flags_missing_slug(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "actors/ghost"],
        "cross-strategy-links": [],
    }
    _, report = validate_synthesis(synthesis, str(root), aliases={})
    assert not report.is_clean
    assert any(b.slug == "actors/ghost" for b in report.broken)
    assert all(b.location == "core-actors" for b in report.broken)


def test_validate_synthesis_resolves_aliases_before_checking(tmp_path):
    root = _make_wiki(tmp_path, actors=["office-of-sustainability-and-innovations"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/a2zero-office"],
        "cross-strategy-links": [],
    }
    aliases = {
        "a2zero-office": {
            "canonical": "actors/office-of-sustainability-and-innovations",
            "type": "actor",
            "aliases": [],
            "relationship": "name-variant",
        }
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases=aliases)
    assert report.is_clean
    assert corrected["core-actors"] == ["actors/office-of-sustainability-and-innovations"]


def test_validate_synthesis_moves_initiatives_out_of_core_actors(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"], initiatives=["bar"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "initiatives/bar"],
        "cross-strategy-links": [],
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases={})
    assert report.is_clean
    assert corrected["core-actors"] == ["actors/foo"]
    assert corrected["core-initiatives"] == ["initiatives/bar"]


def test_validate_synthesis_drops_locations_from_core_actors(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"], locations=["place"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "locations/place"],
        "cross-strategy-links": [],
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases={})
    assert report.is_clean
    assert corrected["core-actors"] == ["actors/foo"]


def test_validate_synthesis_suppress_list_drops_known_bad(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "actors/systems-planning-unit"],
        "cross-strategy-links": [],
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases={})
    assert report.is_clean
    assert "actors/systems-planning-unit" not in corrected["core-actors"]


def test_validate_synthesis_deduplicates(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "actors/foo"],
        "cross-strategy-links": [],
    }
    corrected, _ = validate_synthesis(synthesis, str(root), aliases={})
    assert corrected["core-actors"] == ["actors/foo"]


from pipeline.synthesis_validation import validate_narrative


def test_validate_narrative_passes_clean_prose(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"], initiatives=["bar"])
    narrative = "The [[actors/foo|Foo Org]] led [[initiatives/bar|Bar Program]] this year."
    report = validate_narrative(narrative, str(root), aliases={})
    assert report.is_clean


def test_validate_narrative_flags_broken_wikilinks(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"])
    narrative = "The [[actors/foo|Foo Org]] partnered with [[actors/ghost|Ghost Inc]]."
    report = validate_narrative(narrative, str(root), aliases={})
    assert not report.is_clean
    assert len(report.broken) == 1
    assert report.broken[0].slug == "actors/ghost"
    assert report.broken[0].display == "Ghost Inc"
    assert report.broken[0].location == "narrative"
    assert "Ghost Inc" in report.broken[0].context


def test_validate_narrative_resolves_aliases(tmp_path):
    root = _make_wiki(tmp_path, actors=["office-of-sustainability-and-innovations"])
    narrative = "[[actors/a2zero-office|A2Zero Office]] coordinated the program."
    aliases = {
        "a2zero-office": {
            "canonical": "actors/office-of-sustainability-and-innovations",
            "type": "actor", "aliases": [], "relationship": "name-variant",
        }
    }
    report = validate_narrative(narrative, str(root), aliases=aliases)
    assert report.is_clean


def test_validate_narrative_handles_bare_wikilinks(tmp_path):
    """[[slug]] without pipe-display should still validate."""
    root = _make_wiki(tmp_path, actors=["foo"])
    narrative = "Background on [[actors/foo]] and [[actors/missing]]."
    report = validate_narrative(narrative, str(root), aliases={})
    assert not report.is_clean
    assert report.broken[0].slug == "actors/missing"
