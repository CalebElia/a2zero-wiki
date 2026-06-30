import json
from pathlib import Path
from pipeline.pass2a_pre_chunking import (
    generate_proposed_map,
    load_approved_map,
)


SAMPLE_SOURCE = """---
uuid: test-source
---

# Top
Intro prose.

## Strategy 1
Strategy 1 content.

### Sub-detail
Detail content.

## Strategy 2
Strategy 2 content.
"""


def test_generate_proposed_map_writes_json_and_preview(tmp_path):
    maps_dir = tmp_path / "section_maps"
    json_path, preview_path = generate_proposed_map(
        source_content=SAMPLE_SOURCE,
        source_uuid="test-source",
        section_maps_dir=str(maps_dir),
    )
    assert Path(json_path).exists()
    assert Path(preview_path).exists()
    assert json_path.endswith("test-source_proposed.json")
    assert preview_path.endswith("test-source_preview.md")

    plan = json.loads(Path(json_path).read_text())
    assert plan["document_uuid"] == "test-source"
    assert plan["approved"] is False
    assert any(s["title"] == "Strategy 1" for s in plan["sections"])


def test_generate_proposed_map_defaults_is_chunk_by_depth(tmp_path):
    maps_dir = tmp_path / "section_maps"
    json_path, _ = generate_proposed_map(
        source_content=SAMPLE_SOURCE,
        source_uuid="test-source",
        section_maps_dir=str(maps_dir),
    )
    plan = json.loads(Path(json_path).read_text())
    by_title = {s["title"]: s for s in plan["sections"]}
    assert by_title["Strategy 1"]["is_chunk"] is True   # depth 2
    assert by_title["Top"]["is_chunk"] is True          # depth 1
    assert by_title["Sub-detail"]["is_chunk"] is False  # depth 3


def test_generate_proposed_map_refuses_when_approved_exists(tmp_path):
    import pytest
    maps_dir = tmp_path / "section_maps"
    maps_dir.mkdir()
    # Stage an existing approved.json
    (maps_dir / "test-source_approved.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="approved"):
        generate_proposed_map(
            source_content=SAMPLE_SOURCE,
            source_uuid="test-source",
            section_maps_dir=str(maps_dir),
        )


def test_generate_proposed_map_force_overrides_existing_approved(tmp_path):
    maps_dir = tmp_path / "section_maps"
    maps_dir.mkdir()
    (maps_dir / "test-source_approved.json").write_text("{}", encoding="utf-8")
    json_path, _ = generate_proposed_map(
        source_content=SAMPLE_SOURCE,
        source_uuid="test-source",
        section_maps_dir=str(maps_dir),
        force=True,
    )
    assert Path(json_path).exists()


def test_load_approved_map_returns_none_when_missing(tmp_path):
    result = load_approved_map(
        source_uuid="nonexistent",
        section_maps_dir=str(tmp_path),
    )
    assert result is None


def test_load_approved_map_returns_dict_when_present(tmp_path):
    maps_dir = tmp_path / "section_maps"
    maps_dir.mkdir()
    payload = {"document_uuid": "test", "approved": True, "sections": []}
    (maps_dir / "test_approved.json").write_text(json.dumps(payload), encoding="utf-8")
    result = load_approved_map("test", str(maps_dir))
    assert result == payload
