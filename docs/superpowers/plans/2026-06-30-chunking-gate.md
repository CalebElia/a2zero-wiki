# Chunking Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a human-in-the-loop chunking gate between mechanical section-map parsing and LDP extraction. Add `preflight` and `approve` subcommands to the orchestrator; modify the `source` subcommand to require an approved map (with `--auto-approve` escape).

**Architecture:** A new module `pipeline/pass2a_pre_chunking.py` produces a proposed section map (JSON) plus a human-readable preview (markdown). A separate `approve` step validates and promotes the proposed map. The orchestrator's `source` subcommand refuses to run when LDP is needed but no approved map exists.

**Tech Stack:** Python 3.13, pytest, existing `pipeline/pass2a_chunk_loop.py` `parse_section_map()` (reused), no new LLM calls.

**Spec:** [docs/architecture/chunking-gate.md](../../architecture/chunking-gate.md)

**Branch:** `feat/chunking-gate` (already checked out; stacked on `refactor/pipeline-rename`).

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pipeline/pass2a_pre_chunking.py` | Create | `generate_proposed_map`, `approve_proposed_map`, `load_approved_map`, `render_preview_markdown`, `validate_section_map` |
| `tests/test_pass2a_pre_chunking.py` | Create | Unit tests for all the above |
| `pipeline/pass2a_chunk_loop.py` | Modify | `get_chunks` honors per-section `is_chunk` flag; `parse_section_map` defaults `is_chunk: true` for depth 1-2; `run_ldp_ingest` accepts an approved map or falls back |
| `pipeline/orchestrator.py` | Modify | Add `preflight` and `approve` subcommands; modify `source` subcommand to check for approved map + `--auto-approve` flag |
| `tests/test_pass2a_chunk_loop.py` | Modify | Add tests for `is_chunk` field behavior; ensure backward compat |
| `tests/test_orchestrator.py` (was `test_run_ingest.py`) | Modify | Add tests for gate behavior |
| `CLAUDE.md` | Modify | Document the new gate; add CLI examples |
| `CHANGELOG.md` | Modify | Append entry for this session |

---

### Task 1: Module skeleton + `parse_section_map` v1.1 (adds `is_chunk` field)

**Files:**
- Modify: `pipeline/pass2a_chunk_loop.py` (one tiny change to `parse_section_map`)
- Create: `pipeline/pass2a_pre_chunking.py`
- Create: `tests/test_pass2a_pre_chunking.py`

This task adds the `is_chunk` field to the section map without changing any existing behavior. Sections at depth 1-2 default to `is_chunk: true`; deeper sections default to `false`. Today's logic in `get_chunks` (which uses `depth == 1` / `depth == 2`) continues to work; the new field is additive.

- [ ] **Step 1: Update `parse_section_map` to add `is_chunk` default**

In `pipeline/pass2a_chunk_loop.py`, find the section append in `parse_section_map`:

```python
        stack.append({
            "id": section_id,
            "title": title,
            "depth": depth,
            "line_start": current_line,
            "line_end": None,
        })
```

Change to:

```python
        stack.append({
            "id": section_id,
            "title": title,
            "depth": depth,
            "line_start": current_line,
            "line_end": None,
            "is_chunk": depth <= 2,
            "notes": "",
        })
```

Also bump the version in the returned dict:

```python
    return {
        "document_uuid": document_uuid,
        "total_lines": total_lines,
        "ldp_version": "1.1",
        "sections": sections,
    }
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `python -m pytest tests/test_pass2a_chunk_loop.py -q`
Expected: All existing tests pass. The new `is_chunk` and `notes` fields are present but harmless to existing assertions.

- [ ] **Step 3: Write the failing test for the new module**

```python
# tests/test_pass2a_pre_chunking.py
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_pass2a_pre_chunking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.pass2a_pre_chunking'`

- [ ] **Step 5: Implement the module**

```python
# pipeline/pass2a_pre_chunking.py
"""HITL chunking gate.

Generates a proposed section map (mechanical, no LLM) plus a human-readable
preview. Human reviews/edits the proposed map, then runs `approve` to validate
and promote it. The orchestrator's source subcommand loads the approved map
instead of generating fresh.

See docs/architecture/chunking-gate.md for design rationale.
"""
import json
from pathlib import Path
from pipeline.pass2a_chunk_loop import parse_section_map


def generate_proposed_map(
    source_content: str,
    source_uuid: str,
    section_maps_dir: str,
    force: bool = False,
) -> tuple[str, str]:
    """Run parse_section_map, write proposed.json + preview.md.

    Refuses to run if <uuid>_approved.json already exists (unless force=True).
    Returns (proposed_json_path, preview_md_path).
    """
    maps_dir = Path(section_maps_dir)
    approved_path = maps_dir / f"{source_uuid}_approved.json"
    if approved_path.exists() and not force:
        raise FileExistsError(
            f"approved section map already exists for {source_uuid!r} at {approved_path}. "
            f"Pass force=True to regenerate (this will not delete the approved file)."
        )

    section_map = parse_section_map(source_content, source_uuid)
    section_map["approved"] = False

    maps_dir.mkdir(parents=True, exist_ok=True)
    proposed_path = maps_dir / f"{source_uuid}_proposed.json"
    preview_path = maps_dir / f"{source_uuid}_preview.md"

    proposed_path.write_text(
        json.dumps(section_map, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    preview = render_preview_markdown(section_map, source_content)
    preview_path.write_text(preview, encoding="utf-8")

    return str(proposed_path), str(preview_path)


def load_approved_map(source_uuid: str, section_maps_dir: str) -> dict | None:
    """Load <uuid>_approved.json. Returns None if missing."""
    path = Path(section_maps_dir) / f"{source_uuid}_approved.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def render_preview_markdown(section_map: dict, source_content: str) -> str:
    """Build the human-readable preview from a section map + source body."""
    lines_src = source_content.splitlines()
    sections = section_map.get("sections", [])
    chunks = [s for s in sections if s.get("is_chunk")]
    skipped = [s for s in sections if not s.get("is_chunk")]

    out = [
        f"# Chunk Preview: {section_map['document_uuid']}",
        "",
        f"**Total source lines:** {section_map.get('total_lines', '?')}",
        f"**Proposed chunks:** {len(chunks)}",
        f"**Skipped sections:** {len(skipped)}",
        "",
        "---",
        "",
    ]

    for i, s in enumerate(chunks, 1):
        start, end = s["line_start"], s["line_end"]
        body_lines = lines_src[start - 1:end]
        body_text = "\n".join(body_lines)
        char_count = len(body_text)
        token_estimate = char_count // 4
        preview = body_text[:200].replace("\n", " ").strip()
        if len(body_text) > 200:
            preview += "…"
        notes = s.get("notes") or "_none_"

        out.extend([
            f"## Chunk {i} — {s['title']}",
            f"- **Lines:** {start}–{end} (~{char_count} chars, ~{token_estimate} tokens)",
            f"- **Depth:** {s['depth']}",
            f"- **Notes:** {notes}",
            "",
            f"> {preview}",
            "",
            "---",
            "",
        ])

    if skipped:
        out.extend(["## Skipped Sections (is_chunk: false)", ""])
        for s in skipped:
            note = f" — {s['notes']}" if s.get("notes") else ""
            out.append(f"- depth {s['depth']}: **{s['title']}** (lines {s['line_start']}–{s['line_end']}){note}")
        out.append("")

    return "\n".join(out)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_pass2a_pre_chunking.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add pipeline/pass2a_chunk_loop.py pipeline/pass2a_pre_chunking.py tests/test_pass2a_pre_chunking.py
git commit -m "feat(chunking-gate): pre-chunking module + is_chunk field on section map"
```

---

### Task 2: `validate_section_map` with all 6 validation rules

**Files:**
- Modify: `pipeline/pass2a_pre_chunking.py`
- Modify: `tests/test_pass2a_pre_chunking.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pass2a_pre_chunking.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pass2a_pre_chunking.py::test_validate_section_map_accepts_valid -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `validate_section_map`**

Append to `pipeline/pass2a_pre_chunking.py`:

```python
def validate_section_map(section_map: dict) -> list[str]:
    """Return list of validation errors (empty if valid)."""
    errors: list[str] = []

    if section_map.get("approved") is True:
        errors.append("section map is already approved (approved=true); cannot re-approve")

    total_lines = section_map.get("total_lines", 0)
    sections = section_map.get("sections", [])

    chunk_sections = [s for s in sections if s.get("is_chunk")]
    if not chunk_sections:
        errors.append("no sections marked is_chunk=true — at least one chunk required for extraction")

    for s in sections:
        start, end = s.get("line_start"), s.get("line_end")
        if start is None or end is None:
            errors.append(f"section {s.get('id', '?')!r}: line_start or line_end missing")
            continue
        if start > end:
            errors.append(
                f"section {s.get('id', '?')!r}: line_start ({start}) > line_end ({end})"
            )
        if start < 1 or end > total_lines:
            errors.append(
                f"section {s.get('id', '?')!r}: lines {start}-{end} outside bounds 1-{total_lines}"
            )

    # Check overlap among chunk sections only
    sorted_chunks = sorted(chunk_sections, key=lambda s: s.get("line_start", 0))
    for a, b in zip(sorted_chunks, sorted_chunks[1:]):
        a_end = a.get("line_end", 0)
        b_start = b.get("line_start", 0)
        if a_end >= b_start:
            errors.append(
                f"chunks {a.get('id', '?')!r} (ends {a_end}) and {b.get('id', '?')!r} "
                f"(starts {b_start}) overlap"
            )

    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pass2a_pre_chunking.py -v`
Expected: PASS (13 tests total)

- [ ] **Step 5: Commit**

```bash
git add pipeline/pass2a_pre_chunking.py tests/test_pass2a_pre_chunking.py
git commit -m "feat(chunking-gate): validate_section_map with 6 validation rules"
```

---

### Task 3: `approve_proposed_map` — validate and promote

**Files:**
- Modify: `pipeline/pass2a_pre_chunking.py`
- Modify: `tests/test_pass2a_pre_chunking.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pass2a_pre_chunking.py`:

```python
from pipeline.pass2a_pre_chunking import approve_proposed_map


def test_approve_proposed_map_promotes_to_approved(tmp_path):
    maps_dir = tmp_path / "section_maps"
    maps_dir.mkdir()
    proposed = _make_valid_map()
    (maps_dir / "test_proposed.json").write_text(
        json.dumps(proposed) + "\n", encoding="utf-8"
    )

    approved_path = approve_proposed_map("test", str(maps_dir))

    assert approved_path.endswith("test_approved.json")
    assert Path(approved_path).exists()
    assert not (maps_dir / "test_proposed.json").exists()  # proposed deleted
    loaded = json.loads(Path(approved_path).read_text())
    assert loaded["approved"] is True


def test_approve_proposed_map_raises_on_invalid(tmp_path):
    import pytest
    maps_dir = tmp_path / "section_maps"
    maps_dir.mkdir()
    invalid = _make_valid_map()
    invalid["sections"][1]["line_start"] = 30  # overlap
    (maps_dir / "test_proposed.json").write_text(
        json.dumps(invalid) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="overlap"):
        approve_proposed_map("test", str(maps_dir))
    # Proposed file is untouched on failure
    assert (maps_dir / "test_proposed.json").exists()
    assert not (maps_dir / "test_approved.json").exists()


def test_approve_proposed_map_raises_when_proposed_missing(tmp_path):
    import pytest
    maps_dir = tmp_path / "section_maps"
    maps_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="proposed"):
        approve_proposed_map("nonexistent", str(maps_dir))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pass2a_pre_chunking.py::test_approve_proposed_map_promotes_to_approved -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `pipeline/pass2a_pre_chunking.py`:

```python
def approve_proposed_map(source_uuid: str, section_maps_dir: str) -> str:
    """Validate proposed.json, set approved=true, rename to approved.json.

    Returns the approved.json path. Raises FileNotFoundError if proposed is
    missing, or ValueError listing all validation errors if invalid.
    """
    maps_dir = Path(section_maps_dir)
    proposed_path = maps_dir / f"{source_uuid}_proposed.json"
    approved_path = maps_dir / f"{source_uuid}_approved.json"

    if not proposed_path.exists():
        raise FileNotFoundError(
            f"no proposed section map for {source_uuid!r} at {proposed_path}. "
            f"Run 'preflight' first."
        )

    section_map = json.loads(proposed_path.read_text(encoding="utf-8"))
    errors = validate_section_map(section_map)
    if errors:
        raise ValueError(
            f"section map for {source_uuid!r} is invalid:\n  - " + "\n  - ".join(errors)
        )

    section_map["approved"] = True
    approved_path.write_text(
        json.dumps(section_map, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    proposed_path.unlink()
    return str(approved_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pass2a_pre_chunking.py -v`
Expected: PASS (16 tests total)

- [ ] **Step 5: Commit**

```bash
git add pipeline/pass2a_pre_chunking.py tests/test_pass2a_pre_chunking.py
git commit -m "feat(chunking-gate): approve_proposed_map validates and promotes"
```

---

### Task 4: Update `get_chunks` to honor `is_chunk` field; backward compat for legacy maps

**Files:**
- Modify: `pipeline/pass2a_chunk_loop.py`
- Modify: `tests/test_pass2a_chunk_loop.py`

`get_chunks` currently uses `s["depth"] == 1` and `s["depth"] == 2` to decide which sections become chunks. We're changing it to honor the new `is_chunk` field, with a fallback that reproduces today's behavior when `is_chunk` is missing (e.g., legacy `<uuid>_structure.json` files from Year 1/2).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pass2a_chunk_loop.py`:

```python
def test_get_chunks_honors_is_chunk_field_when_present():
    from pipeline.pass2a_chunk_loop import get_chunks
    section_map = {
        "document_uuid": "t", "total_lines": 100, "ldp_version": "1.1",
        "sections": [
            {"id": "a", "title": "A", "depth": 1, "line_start": 1, "line_end": 50,
             "is_chunk": False},  # explicit: don't extract
            {"id": "b", "title": "B", "depth": 2, "line_start": 51, "line_end": 75,
             "is_chunk": True},
            {"id": "c", "title": "C", "depth": 3, "line_start": 76, "line_end": 100,
             "is_chunk": True},  # explicit: extract even though depth 3
        ],
    }
    chunks = get_chunks(section_map)
    titles = [c["title"] for c in chunks]
    assert "A" not in titles
    assert "B" in titles
    assert "C" in titles  # depth-3 promoted to chunk


def test_get_chunks_falls_back_to_depth_rule_when_is_chunk_missing():
    """Legacy section maps without is_chunk should still work — defaults to depth 1-2."""
    from pipeline.pass2a_chunk_loop import get_chunks
    legacy_section_map = {
        "document_uuid": "t", "total_lines": 100, "ldp_version": "1.0",
        "sections": [
            {"id": "a", "title": "A", "depth": 1, "line_start": 1, "line_end": 50},
            {"id": "b", "title": "B", "depth": 2, "line_start": 51, "line_end": 75},
            {"id": "c", "title": "C", "depth": 3, "line_start": 76, "line_end": 100},
        ],
    }
    chunks = get_chunks(legacy_section_map)
    titles = [c["title"] for c in chunks]
    # depth 1 and 2 included, depth 3 excluded — same as today
    assert "A" in titles
    assert "B" in titles
    assert "C" not in titles
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pass2a_chunk_loop.py::test_get_chunks_honors_is_chunk_field_when_present -v`
Expected: FAIL — current behavior ignores `is_chunk`.

- [ ] **Step 3: Modify `get_chunks` in `pipeline/pass2a_chunk_loop.py`**

Replace the existing `get_chunks` function body. The new logic:
- If section has `is_chunk` field: honor it directly
- If section doesn't have `is_chunk` field (legacy): default to `depth <= 2`
- Preserve the existing depth-1 clipping behavior for sections that become chunks

```python
def get_chunks(section_map: dict) -> list[dict]:
    """Return chunks for LLM extraction.

    Honors the per-section `is_chunk` field when present (v1.1+ section maps).
    Falls back to "depth 1 and depth 2 become chunks" for legacy v1.0 maps
    that don't carry the is_chunk field.

    Depth-1 sections that become chunks are clipped to end just before their
    first depth-2 child to avoid double-extraction with their child chunks.
    """
    all_sections = section_map["sections"]

    def _is_chunk(s: dict) -> bool:
        if "is_chunk" in s:
            return bool(s["is_chunk"])
        return s["depth"] in (1, 2)  # legacy fallback

    chunks = []
    for s in all_sections:
        if not _is_chunk(s):
            continue

        if s["depth"] == 1:
            # Clip depth-1 chunks to end just before their first depth-2 child chunk
            first_child = next(
                (c for c in all_sections
                 if c["depth"] == 2
                 and _is_chunk(c)
                 and s["line_start"] < c["line_start"] <= s["line_end"]),
                None,
            )
            if first_child is None:
                chunks.append(s)
            else:
                clipped_end = first_child["line_start"] - 1
                if clipped_end > s["line_start"]:
                    chunks.append({**s, "line_end": clipped_end})
                # else: skip — heading is immediately followed by a child
        else:
            chunks.append(s)

    chunks.sort(key=lambda c: c["line_start"])
    return chunks
```

- [ ] **Step 4: Run all chunk_loop tests**

Run: `python -m pytest tests/test_pass2a_chunk_loop.py -v`
Expected: All existing tests pass + 2 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/pass2a_chunk_loop.py tests/test_pass2a_chunk_loop.py
git commit -m "feat(chunking-gate): get_chunks honors is_chunk field with legacy depth-rule fallback"
```

---

### Task 5: Wire approved-map loading into `run_ldp_ingest`

**Files:**
- Modify: `pipeline/pass2a_chunk_loop.py`
- Modify: `tests/test_pass2a_chunk_loop.py`

This task changes `run_ldp_ingest` to load from `<uuid>_approved.json` instead of generating the section map fresh. Adds a fallback for the `--auto-approve` path (signaled via a new kwarg).

- [ ] **Step 1: Update `run_ldp_ingest` signature and implementation**

In `pipeline/pass2a_chunk_loop.py`, find `run_ldp_ingest`. Add a new kwarg:

```python
def run_ldp_ingest(
    source_content: str,
    uuid: str,
    title: str,
    quads_path: str,
    source_rel_path: str = "",
    wiki_root: str = "wiki",
    source_type: str = "cap",
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
    wiki_only: bool = False,
    quads_only: bool = False,
    entity_context: str = "",
    integration_plan: dict | None = None,
    retrieved_bodies: dict[str, str] | None = None,
    auto_approve_chunks: bool = False,
):
```

Replace the inline `section_map = parse_section_map(source_content, uuid)` with:

```python
    from pipeline.pass2a_pre_chunking import load_approved_map

    section_map = load_approved_map(uuid, section_maps_dir)
    if section_map is None:
        if not auto_approve_chunks:
            raise RuntimeError(
                f"No approved section map for {uuid!r}. "
                f"Run 'python -m pipeline.orchestrator preflight --source ... --uuid {uuid}' first, "
                f"review the preview, then 'approve'. "
                f"Or pass --auto-approve to bypass the chunking gate."
            )
        # auto-approve path: generate mechanically (legacy behavior)
        print(f"[ldp] WARNING: --auto-approve bypassed the chunking gate for {uuid!r}")
        section_map = parse_section_map(source_content, uuid)
        save_section_map(section_map, section_maps_dir)
```

- [ ] **Step 2: Add tests**

Append to `tests/test_pass2a_chunk_loop.py`:

```python
def test_run_ldp_ingest_raises_when_no_approved_map(tmp_path):
    import pytest
    maps_dir = tmp_path / "section_maps"
    maps_dir.mkdir()
    with pytest.raises(RuntimeError, match="approved section map"):
        from pipeline.pass2a_chunk_loop import run_ldp_ingest
        run_ldp_ingest(
            source_content="---\nuuid: t\n---\n# X\nbody",
            uuid="t", title="T",
            quads_path=str(tmp_path / "q.jsonl"),
            section_maps_dir=str(maps_dir),
            wiki_root=str(tmp_path / "wiki"),
            wiki_only=True,
        )


def test_run_ldp_ingest_uses_approved_map_when_present(tmp_path):
    import json as _json
    from unittest.mock import patch
    maps_dir = tmp_path / "section_maps"
    maps_dir.mkdir()
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    approved = {
        "document_uuid": "t", "total_lines": 5, "ldp_version": "1.1", "approved": True,
        "sections": [
            {"id": "x", "title": "X", "depth": 2, "line_start": 1, "line_end": 5,
             "is_chunk": True},
        ],
    }
    (maps_dir / "t_approved.json").write_text(_json.dumps(approved), encoding="utf-8")

    with patch("pipeline.pass2b_extract.extract_wiki_pages_from_chunk", return_value=[]):
        from pipeline.pass2a_chunk_loop import run_ldp_ingest
        run_ldp_ingest(
            source_content="---\n---\n# X\nline2\nline3\nline4\nline5\n",
            uuid="t", title="T",
            quads_path=str(tmp_path / "q.jsonl"),
            section_maps_dir=str(maps_dir),
            wiki_root=str(wiki),
            wiki_only=True,
        )
    # Should NOT have generated a fresh structure.json
    assert not (maps_dir / "t_structure.json").exists()


def test_run_ldp_ingest_auto_approve_bypasses_gate(tmp_path):
    from unittest.mock import patch
    maps_dir = tmp_path / "section_maps"
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    # No approved map — auto-approve should fall back to generating mechanically
    with patch("pipeline.pass2b_extract.extract_wiki_pages_from_chunk", return_value=[]):
        from pipeline.pass2a_chunk_loop import run_ldp_ingest
        run_ldp_ingest(
            source_content="---\n---\n# X\ncontent\n## Sub\nsubcontent\n",
            uuid="t", title="T",
            quads_path=str(tmp_path / "q.jsonl"),
            section_maps_dir=str(maps_dir),
            wiki_root=str(wiki),
            wiki_only=True,
            auto_approve_chunks=True,
        )
    # Fresh structure.json IS generated in auto-approve mode
    assert (maps_dir / "t_structure.json").exists()
```

- [ ] **Step 3: Run all tests**

Run: `python -m pytest tests/test_pass2a_chunk_loop.py -v`
Expected: All existing + 3 new tests pass.

- [ ] **Step 4: Commit**

```bash
git add pipeline/pass2a_chunk_loop.py tests/test_pass2a_chunk_loop.py
git commit -m "feat(chunking-gate): run_ldp_ingest requires approved map (with --auto-approve escape)"
```

---

### Task 6: Add `preflight` and `approve` subcommands + `--auto-approve` flag to orchestrator

**Files:**
- Modify: `pipeline/orchestrator.py`
- Modify: `tests/test_orchestrator.py` (or whatever the renamed test file is — check `git log --follow tests/test_run_ingest.py`)

- [ ] **Step 1: Add subcommands to orchestrator CLI**

In `pipeline/orchestrator.py`, find the `argparse` setup (the `if __name__ == "__main__"` block near the bottom). Add two new subparsers:

```python
    # preflight subcommand
    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Generate proposed section map + preview for human review",
    )
    preflight_parser.add_argument("--source", required=True)
    preflight_parser.add_argument("--uuid", required=True)
    preflight_parser.add_argument(
        "--section-maps-dir", default="blackboard/section_maps"
    )
    preflight_parser.add_argument(
        "--force", action="store_true",
        help="Regenerate proposed map even if approved.json already exists",
    )

    # approve subcommand
    approve_parser = subparsers.add_parser(
        "approve",
        help="Validate proposed section map and promote to approved",
    )
    approve_parser.add_argument("--uuid", required=True)
    approve_parser.add_argument(
        "--section-maps-dir", default="blackboard/section_maps"
    )
```

Add a `--auto-approve` flag to the existing `source` subcommand:

```python
    source_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Bypass the chunking-gate human review; generate section map mechanically",
    )
```

Add the dispatch logic (in the main block after `args = parser.parse_args()`):

```python
    if args.command == "preflight":
        from pipeline.pass2a_pre_chunking import generate_proposed_map
        source_content = Path(args.source).read_text(encoding="utf-8")
        json_path, preview_path = generate_proposed_map(
            source_content=source_content,
            source_uuid=args.uuid,
            section_maps_dir=args.section_maps_dir,
            force=args.force,
        )
        print(f"[preflight] proposed map: {json_path}")
        print(f"[preflight] preview:       {preview_path}")
        print(f"[preflight] Review the preview. When ready:")
        print(f"           python -m pipeline.orchestrator approve --uuid {args.uuid}")

    elif args.command == "approve":
        from pipeline.pass2a_pre_chunking import approve_proposed_map
        approved_path = approve_proposed_map(
            source_uuid=args.uuid,
            section_maps_dir=args.section_maps_dir,
        )
        print(f"[approve] approved map: {approved_path}")
        print(f"[approve] Run: python -m pipeline.orchestrator source --source ... --uuid {args.uuid} ...")

    elif args.command == "source":
        run_source_ingest(
            # ... existing args ...
            auto_approve_chunks=args.auto_approve,
        )
```

- [ ] **Step 2: Thread `auto_approve_chunks` through `run_source_ingest`**

Add the kwarg to `run_source_ingest` signature and pass it through to `run_ldp_ingest`:

```python
def run_source_ingest(
    source_path: str,
    uuid: str,
    title: str,
    quads_path: str,
    wiki_root: str,
    review_queue_path: str,
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
    wiki_only: bool = False,
    quads_only: bool = False,
    auto_approve_chunks: bool = False,
):
```

Pass it to the `run_ldp_ingest` call:

```python
        run_ldp_ingest(
            # ... existing kwargs ...
            auto_approve_chunks=auto_approve_chunks,
        )
```

- [ ] **Step 3: Add tests for orchestrator gate behavior**

Append to the orchestrator test file (most likely renamed; check `ls tests/test_orchestrator.py tests/test_run_ingest.py`):

```python
def test_source_ingest_refuses_without_approved_map(tmp_path):
    import pytest
    from unittest.mock import patch
    # Stage a wiki + source that would route to LDP
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "t.md"
    # Long enough to route to LDP: 150+ lines, 5+ headings
    headings_and_body = "\n".join([f"# H{i}\nbody{i}" for i in range(10)]) + ("\nfiller\n" * 200)
    src_path.write_text(f"---\nuuid: t\n---\n{headings_and_body}", encoding="utf-8")

    from pipeline.orchestrator import run_source_ingest
    with pytest.raises(RuntimeError, match="approved section map"):
        run_source_ingest(
            source_path=str(src_path),
            uuid="t", title="T",
            quads_path=str(tmp_path / "q.jsonl"),
            wiki_root=str(wiki),
            review_queue_path=str(tmp_path / "queue.md"),
            section_maps_dir=str(tmp_path / "maps"),
            run_date="2026-06-30",
            wiki_only=True,
            auto_approve_chunks=False,  # gate ON
        )


def test_source_ingest_small_doc_bypasses_gate(tmp_path):
    """Small docs route to the non-LDP path and don't need approval."""
    from unittest.mock import patch
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "tiny.md"
    src_path.write_text("---\nuuid: tiny\n---\n# Just one heading\nBrief.\n", encoding="utf-8")

    with patch("pipeline.pass1b_synthesize.synthesize_source", return_value={"stub_pages": []}), \
         patch("pipeline.pass2b_extract.extract_wiki_pages_from_chunk", return_value=[]), \
         patch("pipeline.pass2b_extract.chat", return_value="[]"), \
         patch("pipeline.pass1a_comprehend.chat") as mock_comprehend:
        # No digest exists → comprehend graceful fallback (no LLM)
        from pipeline.orchestrator import run_source_ingest
        run_source_ingest(
            source_path=str(src_path),
            uuid="tiny", title="T",
            quads_path=str(tmp_path / "q.jsonl"),
            wiki_root=str(wiki),
            review_queue_path=str(tmp_path / "queue.md"),
            run_date="2026-06-30",
            wiki_only=True,
            auto_approve_chunks=False,  # gate ON but irrelevant for small docs
        )
        # No exception — gate was bypassed because LDP wasn't used
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -q`
Expected: All passing (existing + new).

- [ ] **Step 5: Commit**

```bash
git add pipeline/orchestrator.py tests/test_orchestrator.py 2>/dev/null || git add pipeline/orchestrator.py tests/test_run_ingest.py
git commit -m "feat(chunking-gate): preflight + approve subcommands; --auto-approve escape on source"
```

---

### Task 7: Smoke test on Year 3 (manual)

This is a manual verification step. No code; just exercising the gate end-to-end on real data.

- [ ] **Step 1: Run preflight**

```bash
python -m pipeline.orchestrator preflight \
  --source prepared/annual-reports/a2zero-year3.md \
  --uuid a2zero-year3
```

Expected output: two file paths printed, plus next-step instructions.

- [ ] **Step 2: Inspect the preview**

```bash
cat blackboard/section_maps/a2zero-year3_preview.md | head -80
```

Look for:
- Sensible chunk titles (should match A2Zero's strategy structure)
- Reasonable line ranges (no chunks > ~3000 chars or < ~200 chars usually)
- Content previews look like the start of real strategy sections

If anything looks off, edit `blackboard/section_maps/a2zero-year3_proposed.json` directly.

- [ ] **Step 3: Run approve**

```bash
python -m pipeline.orchestrator approve --uuid a2zero-year3
```

Expected: `[approve] approved map: blackboard/section_maps/a2zero-year3_approved.json` + next-step instruction.

- [ ] **Step 4: Verify gate behavior (sanity check, no full ingest yet)**

```bash
ls blackboard/section_maps/a2zero-year3_*.json
```

Expected: only `a2zero-year3_approved.json` exists (`_proposed.json` was deleted by approve).

The actual full Year 3 ingest is a separate decision — this smoke test only validates the gate plumbing works.

---

### Task 8: Update CLAUDE.md + CHANGELOG.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update CLAUDE.md**

Add a new section after the existing ingest commands describing the gate. Use the chunking-gate spec as the source of language. At minimum:
- Three-command workflow (`preflight`, then human review, then `approve`, then `source`)
- The `--auto-approve` escape
- Note that small docs bypass the gate
- Link to `docs/architecture/chunking-gate.md`

Add `pass2a_pre_chunking.py` to the Pipeline Modules table:

```markdown
| `pass2a_pre_chunking.py` | HITL chunking gate: preflight + approve subcommands |
```

- [ ] **Step 2: Update CHANGELOG.md**

Prepend a new entry under today's date:

```markdown
## 2026-06-30 — Chunking gate (HITL review before LDP)

**What changed:**
- **`pipeline/pass2a_pre_chunking.py`** — new module implementing the chunking gate: `generate_proposed_map`, `approve_proposed_map`, `load_approved_map`, `render_preview_markdown`, `validate_section_map`. No LLM calls; pure mechanical orchestration.
- **`pipeline/orchestrator.py`** — added `preflight` and `approve` subcommands; modified `source` subcommand to require an approved section map (with `--auto-approve` escape hatch for trusted batch ingests).
- **`pipeline/pass2a_chunk_loop.py`** — `parse_section_map` now produces v1.1 section maps with per-section `is_chunk` and `notes` fields. `get_chunks` honors `is_chunk` when present, falls back to depth-1-or-2 rule for legacy v1.0 maps. `run_ldp_ingest` loads from `<uuid>_approved.json` instead of generating mechanically; raises clear error when no approved map exists.
- **Workflow change:** Every new LDP-routed ingest now requires `preflight` → human review → `approve` → `source`. Small documents (those that don't trigger LDP) bypass the gate.
- **Backward compat:** Existing `<uuid>_structure.json` files from CAP/Year1/Year2 ingests are untouched. The new `<uuid>_proposed.json` / `<uuid>_approved.json` filenames don't collide.
- **~16 new tests** in `tests/test_pass2a_pre_chunking.py` covering preflight, approve, validation rules, and load_approved_map. Plus tests for the new `get_chunks` behavior and orchestrator gate.

**Why:** Mechanical chunking via markdown headings works for clean sources like A2Zero annual reports, but will fail on council transcripts, news articles, OCR'd PDFs, and other heading-poor formats. Bad chunks have outsized downstream cost — split entities fragment, fused topics dilute extraction. The HITL gate is cheap (one click-through per ingest) and forces human review of chunk quality before extraction commits any LLM tokens. Year 3 is the shakedown on a clean source.

**Spec:** `docs/architecture/chunking-gate.md`. **Plan:** `docs/superpowers/plans/2026-06-30-chunking-gate.md`. **Branch:** `feat/chunking-gate` (draft PR).

---
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: document chunking gate in CLAUDE.md + CHANGELOG"
```

---

### Task 9: Push branch + open draft PR

- [ ] **Step 1: Verify all tests pass**

```bash
python -m pytest tests/ -q
```
Expected: all green (existing 205 + ~16 new tests from this PR).

- [ ] **Step 2: Push branch**

```bash
git push
```

- [ ] **Step 3: Open draft PR with `--base refactor/pipeline-rename`**

The PR's base is `refactor/pipeline-rename`, NOT main. PRs stack: #4 → #5 → #6.

Write the PR body to scratchpad first:

```bash
cat > /tmp/chunking-gate-pr-body.md <<'EOF'
## Summary

Introduces a human-in-the-loop chunking gate between mechanical section-map parsing and Pass 2 LDP extraction. Adds `preflight` and `approve` subcommands to the orchestrator. The `source` subcommand now requires an approved section map (with `--auto-approve` escape for trusted batch ingests).

## Architecture

- **`pipeline/pass2a_pre_chunking.py`** (new): `generate_proposed_map`, `approve_proposed_map`, `load_approved_map`, `render_preview_markdown`, `validate_section_map`. No LLM calls.
- **`pipeline/orchestrator.py`**: two new subcommands (`preflight`, `approve`); `source` gains `--auto-approve` flag.
- **`pipeline/pass2a_chunk_loop.py`**: `parse_section_map` produces v1.1 maps with `is_chunk` field; `get_chunks` honors it with legacy fallback; `run_ldp_ingest` loads from approved map.

## Workflow

```bash
python -m pipeline.orchestrator preflight --source ... --uuid a2zero-year3
# Human reads blackboard/section_maps/a2zero-year3_preview.md
# Human optionally edits blackboard/section_maps/a2zero-year3_proposed.json
python -m pipeline.orchestrator approve --uuid a2zero-year3
python -m pipeline.orchestrator source --source ... --uuid a2zero-year3 ...
```

## Key design decisions (per spec)

- Gate is mandatory by default; `--auto-approve` is the escape hatch
- Small documents (non-LDP path) bypass the gate
- Preview is generated, read-only; humans edit the JSON directly
- `approve` validates (no negative ranges, no overlapping chunks, in-bounds, at least one chunk) and rejects with clear errors
- Backward compat: existing `<uuid>_structure.json` files untouched; legacy v1.0 maps without `is_chunk` field default to depth-1-or-2 rule

## Test plan

- [x] ~16 new unit tests in `tests/test_pass2a_pre_chunking.py` covering preflight, approve, validation, load
- [x] Updated tests in `tests/test_pass2a_chunk_loop.py` for new `is_chunk` behavior + backward compat
- [x] Updated orchestrator tests for gate behavior + small-doc bypass
- [x] Manual smoke test on Year 3: preflight → inspect preview → approve, gate plumbing works
- [ ] Year 3 full ingest — DEFERRED (Caleb's call after PR review)

## Stacking

Base: `refactor/pipeline-rename` (PR #5). PRs land in order: #4 (Comprehend) → #5 (Rename) → this PR.

## Spec + plan

- **Spec:** [docs/architecture/chunking-gate.md](docs/architecture/chunking-gate.md)
- **Plan:** [docs/superpowers/plans/2026-06-30-chunking-gate.md](docs/superpowers/plans/2026-06-30-chunking-gate.md)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

Then:

```bash
gh pr create --draft \
  --base refactor/pipeline-rename \
  --title "feat: chunking gate (HITL review before LDP)" \
  --body-file /tmp/chunking-gate-pr-body.md
```

- [ ] **Step 4: Report PR URL back to the user**

---

## Self-Review Checklist

After all tasks complete:

- [ ] All tests passing
- [ ] `parse_section_map` produces v1.1 maps with `is_chunk` and `notes`
- [ ] `get_chunks` works for both v1.1 and legacy v1.0 maps
- [ ] `preflight` writes proposed.json + preview.md
- [ ] `approve` validates and promotes; rejects invalid maps with all errors listed
- [ ] `source` refuses to run when LDP would route and no approved map exists (without `--auto-approve`)
- [ ] Small docs (non-LDP path) bypass the gate
- [ ] CLAUDE.md and CHANGELOG.md updated
- [ ] Year 3 smoke test passed (preflight → approve worked, no actual ingest yet)
- [ ] Draft PR opened with base `refactor/pipeline-rename`
