import json
from pathlib import Path
from pipeline.schema_governance import (
    load_relationship_lexicon,
    build_lexicon_block,
    append_schema_drift_entry,
    parse_schema_drift_entries,
    apply_schema_drift,
    schema_drift_findings,
)


# ── relationship lexicon ─────────────────────────────────────────────────────

def test_load_relationship_lexicon_missing_returns_empty(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    assert load_relationship_lexicon(str(root)) == ""


def test_load_relationship_lexicon_reads_content(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "relationship-lexicon.md").write_text(
        "# Relationship Lexicon\n\nUse `implements` not `related to`.\n", encoding="utf-8"
    )
    content = load_relationship_lexicon(str(root))
    assert "implements" in content


def test_build_lexicon_block_wraps_in_brackets(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "relationship-lexicon.md").write_text("Use `implements`.\n", encoding="utf-8")
    block = build_lexicon_block(str(root))
    assert block.startswith("\n[RELATIONSHIP LEXICON]\n")
    assert block.rstrip().endswith("[END RELATIONSHIP LEXICON]")
    assert "implements" in block


def test_build_lexicon_block_empty_when_missing(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    assert build_lexicon_block(str(root)) == ""


# ── schema-drift write format ────────────────────────────────────────────────

def test_append_schema_drift_entry_writes_documented_format(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    append_schema_drift_entry(
        proposed_type="zoning-application",
        fallback_type="political-event",
        slug="political-events/2025-01-15-zoning",
        title="2025 Zoning Application",
        wiki_root=str(root),
        run_date="2026-07-03",
    )
    content = (tmp_path / "meta" / "schema-drift.md").read_text(encoding="utf-8")
    assert '## 2026-07-03 | Proposed type: "zoning-application" | Written as: "political-event" | Page: "political-events/2025-01-15-zoning"' in content
    assert "Title: 2025 Zoning Application" in content
    assert "Resolution: [ ] Approve new type  [ ] Keep as fallback + tag [<tag>]" in content


def test_append_schema_drift_entry_appends_not_clobbers(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    for i in range(2):
        append_schema_drift_entry(
            proposed_type=f"type-{i}", fallback_type="actor", slug=f"actors/x{i}",
            title=f"X{i}", wiki_root=str(root), run_date="2026-07-03",
        )
    content = (tmp_path / "meta" / "schema-drift.md").read_text(encoding="utf-8")
    assert content.count("Proposed type:") == 2


# ── parsing ───────────────────────────────────────────────────────────────────

def _fixture_drift_log(tmp_path, extra=""):
    path = tmp_path / "meta" / "schema-drift.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Schema Drift Log\n\n"
        '## 2026-07-01 | Proposed type: "zoning-application" | Written as: "political-event" | Page: "political-events/zoning-1"\n'
        "Title: Zoning Application 1\n"
        "Resolution: [x] Approve new type  [ ] Keep as fallback + tag [<tag>]\n"
        + extra,
        encoding="utf-8",
    )
    return path


def test_parse_schema_drift_entries_round_trips(tmp_path):
    path = _fixture_drift_log(tmp_path)
    entries = parse_schema_drift_entries(str(path))
    assert len(entries) == 1
    e = entries[0]
    assert e["date"] == "2026-07-01"
    assert e["proposed_type"] == "zoning-application"
    assert e["fallback_type"] == "political-event"
    assert e["slug"] == "political-events/zoning-1"
    assert e["title"] == "Zoning Application 1"
    assert e["approve_checked"] is True
    assert e["keep_checked"] is False
    assert e["resolved"] is False


def test_parse_schema_drift_entries_detects_resolved_marker(tmp_path):
    path = _fixture_drift_log(
        tmp_path,
        extra='\n**Resolved 2026-07-02: approved — "zoning-application" added to VALID_PAGE_TYPES**\n',
    )
    entries = parse_schema_drift_entries(str(path))
    assert entries[0]["resolved"] is True


def test_parse_schema_drift_entries_missing_file_returns_empty():
    assert parse_schema_drift_entries("/nonexistent/schema-drift.md") == []


# ── apply loop ────────────────────────────────────────────────────────────────

def test_apply_schema_drift_approve_adds_type_and_strips_frontmatter(tmp_path, monkeypatch):
    root = tmp_path / "wiki"
    (root / "political-events").mkdir(parents=True)
    (root / "political-events" / "zoning-1.md").write_text(
        "---\ntype: political-event\nproposed-type: zoning-application\ntitle: Zoning 1\n---\n\nBody.\n",
        encoding="utf-8",
    )
    _fixture_drift_log(tmp_path)

    types_path = tmp_path / "valid_page_types.json"
    types_path.write_text(json.dumps({"page_types": ["political-event", "actor"]}), encoding="utf-8")
    import pipeline._pages as _pages
    monkeypatch.setattr(_pages, "_VALID_PAGE_TYPES_PATH", types_path)
    monkeypatch.setattr(_pages, "VALID_PAGE_TYPES", frozenset({"political-event", "actor"}))

    result = apply_schema_drift(str(root))

    assert result["approved"] == ["zoning-application"]
    saved = json.loads(types_path.read_text(encoding="utf-8"))
    assert "zoning-application" in saved["page_types"]

    page_content = (root / "political-events" / "zoning-1.md").read_text(encoding="utf-8")
    assert "proposed-type:" not in page_content

    drift_content = (tmp_path / "meta" / "schema-drift.md").read_text(encoding="utf-8")
    assert "**Resolved" in drift_content
    assert 'approved — "zoning-application"' in drift_content
    # Entry stays in the file — append-only, not deleted like review-queue.md
    assert 'Proposed type: "zoning-application"' in drift_content


def test_apply_schema_drift_keep_as_fallback_tags_page(tmp_path):
    root = tmp_path / "wiki"
    (root / "political-events").mkdir(parents=True)
    (root / "political-events" / "zoning-1.md").write_text(
        "---\ntype: political-event\nproposed-type: zoning-application\ntitle: Zoning 1\ntags: []\n---\n\nBody.\n",
        encoding="utf-8",
    )
    path = tmp_path / "meta" / "schema-drift.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '## 2026-07-01 | Proposed type: "zoning-application" | Written as: "political-event" | Page: "political-events/zoning-1"\n'
        "Title: Zoning Application 1\n"
        "Resolution: [ ] Approve new type  [x] Keep as fallback + tag [zoning]\n",
        encoding="utf-8",
    )

    result = apply_schema_drift(str(root))

    assert result["kept"] == ["political-events/zoning-1"]
    page_content = (root / "political-events" / "zoning-1.md").read_text(encoding="utf-8")
    assert "zoning" in page_content

    drift_content = path.read_text(encoding="utf-8")
    assert "kept as fallback" in drift_content


def test_apply_schema_drift_skips_already_resolved_entries(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    path = _fixture_drift_log(
        tmp_path,
        extra='\n**Resolved 2026-07-02: approved — "zoning-application" added to VALID_PAGE_TYPES**\n',
    )
    original = path.read_text(encoding="utf-8")
    result = apply_schema_drift(str(root))
    assert result == {"approved": [], "kept": []}
    assert path.read_text(encoding="utf-8") == original


def test_apply_schema_drift_no_entries_no_op(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    result = apply_schema_drift(str(root))
    assert result == {"approved": [], "kept": []}


# ── findings for structural_lint ─────────────────────────────────────────────

def test_schema_drift_findings_returns_one_per_unresolved_entry(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    _fixture_drift_log(tmp_path)
    findings = schema_drift_findings(str(root))
    assert len(findings) == 1
    assert findings[0]["type"] == "SCHEMA_DRIFT_PENDING"
    assert findings[0]["page"] == "meta/schema-drift.md"
    assert "zoning-application" in findings[0]["detail"]


def test_schema_drift_findings_excludes_resolved(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    _fixture_drift_log(
        tmp_path,
        extra='\n**Resolved 2026-07-02: approved — "zoning-application" added to VALID_PAGE_TYPES**\n',
    )
    assert schema_drift_findings(str(root)) == []


def test_schema_drift_findings_missing_file_returns_empty(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    assert schema_drift_findings(str(root)) == []
