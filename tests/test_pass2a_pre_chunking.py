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


from pipeline.pass2a_pre_chunking import validate_section_map


def _make_valid_map():
    return {
        "document_uuid": "test",
        "total_lines": 100,
        "ldp_version": "1.1",
        "approved": False,
        "sections": [
            {"id": "a", "title": "A", "depth": 1, "line_start": 1, "line_end": 50,
             "is_chunk": True, "notes": ""},
            {"id": "b", "title": "B", "depth": 1, "line_start": 51, "line_end": 100,
             "is_chunk": True, "notes": ""},
        ],
    }


def test_validate_section_map_accepts_valid():
    errors = validate_section_map(_make_valid_map())
    assert errors == []


def test_validate_section_map_rejects_negative_range():
    m = _make_valid_map()
    m["sections"][0]["line_end"] = 0  # 0 < line_start=1
    errors = validate_section_map(m)
    assert any("line_end" in e and "line_start" in e for e in errors)


def test_validate_section_map_rejects_overlapping_chunks():
    m = _make_valid_map()
    m["sections"][1]["line_start"] = 30  # overlaps with section[0] which ends at 50
    errors = validate_section_map(m)
    assert any("overlap" in e.lower() for e in errors)


def test_validate_section_map_rejects_out_of_bounds():
    m = _make_valid_map()
    m["sections"][1]["line_end"] = 200  # total_lines is 100
    errors = validate_section_map(m)
    assert any("bounds" in e.lower() or "total_lines" in e for e in errors)


def test_validate_section_map_requires_at_least_one_chunk():
    m = _make_valid_map()
    for s in m["sections"]:
        s["is_chunk"] = False
    errors = validate_section_map(m)
    assert any("at least one" in e.lower() or "no chunks" in e.lower() for e in errors)


def test_validate_section_map_rejects_already_approved():
    m = _make_valid_map()
    m["approved"] = True
    errors = validate_section_map(m)
    assert any("already approved" in e.lower() for e in errors)


def test_validate_section_map_ignores_overlap_when_one_side_is_not_chunk():
    """Sections marked is_chunk=False can overlap with chunks (they're not extracted)."""
    m = _make_valid_map()
    m["sections"].append({
        "id": "c", "title": "C", "depth": 3, "line_start": 5, "line_end": 10,
        "is_chunk": False, "notes": "nested",
    })
    errors = validate_section_map(m)
    # No overlap error — the depth-3 isn't a chunk
    assert not any("overlap" in e.lower() for e in errors)
