import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.silver_to_gold import (
    load_existing_body,
    append_to_wiki_page,
    verify_existing_body_unchanged,
)


def test_load_existing_body_strips_frontmatter(tmp_path):
    page_file = tmp_path / "actors" / "missy-stults.md"
    page_file.parent.mkdir()
    page_file.write_text(
        "---\ntype: actor\ntitle: Missy Stults\n---\n\nOriginal body text.\n"
    )
    body = load_existing_body(str(page_file))
    assert body == "Original body text.\n"
    assert "---" not in body


def test_append_to_wiki_page_adds_new_section(tmp_path):
    page_file = tmp_path / "actors" / "missy-stults.md"
    page_file.parent.mkdir()
    page_file.write_text(
        "---\ntype: actor\ntitle: Missy Stults\n---\n\nOriginal body text.\n"
    )
    append_to_wiki_page(
        page_path=str(page_file),
        new_content="\n## Year 3 Activity\n\nNew content from year3 report.\n",
        source_uuid="a2zero-year3",
    )
    content = page_file.read_text()
    assert "Original body text." in content
    assert "Year 3 Activity" in content
    assert "New content from year3 report." in content


def test_append_preserves_existing_body_byte_for_byte(tmp_path):
    page_file = tmp_path / "actors" / "missy-stults.md"
    page_file.parent.mkdir()
    original = "---\ntype: actor\ntitle: Missy Stults\n---\n\nOriginal body text.\n"
    page_file.write_text(original)
    original_body = load_existing_body(str(page_file))
    append_to_wiki_page(
        page_path=str(page_file),
        new_content="\nNew section.\n",
        source_uuid="a2zero-year2",
    )
    after_body = load_existing_body(str(page_file))
    assert after_body.startswith(original_body)


def test_verify_existing_body_unchanged_passes_when_unchanged(tmp_path):
    page_file = tmp_path / "actors" / "test.md"
    page_file.parent.mkdir()
    page_file.write_text("---\ntype: actor\n---\n\nOriginal.\n")
    original_body = load_existing_body(str(page_file))
    # simulate no change
    page_file.write_text("---\ntype: actor\n---\n\nOriginal.\nNew content.\n")
    # should not raise
    verify_existing_body_unchanged(
        page_path=str(page_file),
        expected_original_body=original_body,
    )


def test_verify_existing_body_raises_when_changed(tmp_path):
    page_file = tmp_path / "actors" / "test.md"
    page_file.parent.mkdir()
    page_file.write_text("---\ntype: actor\n---\n\nOriginal.\n")
    original_body = "Original.\n"
    # simulate LLM rewrote existing content
    page_file.write_text("---\ntype: actor\n---\n\nRewritten by LLM.\n")
    with pytest.raises(ValueError, match="existing body was modified"):
        verify_existing_body_unchanged(
            page_path=str(page_file),
            expected_original_body=original_body,
        )


def test_verify_existing_body_raises_on_empty_expected(tmp_path):
    page_file = tmp_path / "actors" / "test.md"
    page_file.parent.mkdir()
    page_file.write_text("---\ntype: actor\n---\n\nSome body.\n")
    with pytest.raises(ValueError, match="must not be empty"):
        verify_existing_body_unchanged(
            page_path=str(page_file),
            expected_original_body="",
        )
