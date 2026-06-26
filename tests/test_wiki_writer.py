import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.wiki_pages import build_wiki_page, write_wiki_page


def test_build_wiki_page_actor():
    page = build_wiki_page(
        page_type="actor",
        slug="actors/missy-stults",
        frontmatter={
            "type": "actor",
            "title": "Missy Stults",
            "role": "Sustainability and Innovations Director",
            "organization": "City of Ann Arbor",
            "first-seen": "a2zero-year1",
            "last-updated": "2026-06-18",
            "tags": ["leadership", "osi"],
        },
        body="Missy Stults joined the City of Ann Arbor as Sustainability Director in 2019.",
    )
    assert page.page_type == "actor"
    assert page.slug == "actors/missy-stults"
    assert "Missy Stults" in page.frontmatter["title"]
    assert "Missy Stults joined" in page.body


def test_write_wiki_page_creates_file(tmp_path):
    from pipeline.wiki_pages import build_wiki_page, write_wiki_page
    page = build_wiki_page(
        page_type="actor",
        slug="actors/missy-stults",
        frontmatter={
            "type": "actor",
            "title": "Missy Stults",
            "role": "Sustainability Director",
            "organization": "City of Ann Arbor",
            "first-seen": "a2zero-year1",
            "last-updated": "2026-06-18",
            "tags": ["leadership"],
        },
        body="Missy Stults led the A2Zero program.",
    )
    write_wiki_page(page, wiki_root=str(tmp_path))
    out_file = tmp_path / "actors" / "missy-stults.md"
    assert out_file.exists()
    content = out_file.read_text()
    assert "---" in content
    assert "Missy Stults led" in content


def test_write_wiki_page_frontmatter_is_valid_yaml(tmp_path):
    from pipeline.wiki_pages import build_wiki_page, write_wiki_page
    page = build_wiki_page(
        page_type="actor",
        slug="actors/osi",
        frontmatter={
            "type": "actor",
            "title": "OSI",
            "role": "City department",
            "organization": "City of Ann Arbor",
            "first-seen": "a2zero-year1",
            "last-updated": "2026-06-18",
            "tags": [],
        },
        body="The Office of Sustainability and Innovations (OSI) leads A2Zero.",
    )
    write_wiki_page(page, wiki_root=str(tmp_path))
    out_file = tmp_path / "actors" / "osi.md"
    content = out_file.read_text()
    parts = content.split("---\n")
    parsed = yaml.safe_load(parts[1])
    assert parsed["type"] == "actor"


def test_write_wiki_page_raises_if_exists(tmp_path):
    from pipeline.wiki_pages import build_wiki_page, write_wiki_page
    page = build_wiki_page(
        page_type="actor",
        slug="actors/test-actor",
        frontmatter={"type": "actor", "title": "Test Actor", "first-seen": "s", "last-updated": "2026-06-18", "tags": []},
        body="Body.",
    )
    write_wiki_page(page, wiki_root=str(tmp_path))
    with pytest.raises(FileExistsError):
        write_wiki_page(page, wiki_root=str(tmp_path))  # second write should raise


def test_write_wiki_page_exist_ok_allows_overwrite(tmp_path):
    from pipeline.wiki_pages import build_wiki_page, write_wiki_page
    page = build_wiki_page(
        page_type="actor",
        slug="actors/test-actor",
        frontmatter={"type": "actor", "title": "Test Actor", "first-seen": "s", "last-updated": "2026-06-18", "tags": []},
        body="Body.",
    )
    write_wiki_page(page, wiki_root=str(tmp_path))
    write_wiki_page(page, wiki_root=str(tmp_path), exist_ok=True)  # should not raise


def test_build_wiki_page_raises_on_invalid_page_type():
    from pipeline.wiki_pages import build_wiki_page
    with pytest.raises(ValueError, match="Invalid page_type"):
        build_wiki_page(
            page_type="garbage",
            slug="actors/test",
            frontmatter={},
            body="",
        )
