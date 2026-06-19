import json
import pytest
from pathlib import Path
from pipeline.quad_linter import lint_quads, LintReport


VALID_QUAD = {
    "id": "sha256-abc001",
    "date": "2021-09",
    "date_precision": "month",
    "subject": "u-20713-settlement",
    "relation": "established",
    "object": "community solar",
    "sources": ["test-year1"],
    "source_types": ["annual-report"],
    "confidence": 2,
    "status": "confirmed",
    "dark_matter": False,
    "topics": [],
    "locations": [],
    "strategies": ["strategy-1"],
    "actors": ["actors/osi"],
    "keywords": ["solar"],
    "fund_type": None,
    "commitment_status": None,
    "last_updated": "2026-06-18",
}


def test_lint_valid_quads_returns_no_errors(tmp_path):
    qf = tmp_path / "quads.jsonl"
    qf.write_text(json.dumps(VALID_QUAD) + "\n")
    report = lint_quads(str(qf))
    assert report.schema_errors == []
    assert report.duplicate_ids == []


def test_lint_detects_schema_error(tmp_path):
    bad = {"id": "sha256-bad", "subject": "a"}  # missing most fields
    qf = tmp_path / "quads.jsonl"
    qf.write_text(json.dumps(bad) + "\n")
    report = lint_quads(str(qf))
    assert len(report.schema_errors) > 0


def test_lint_detects_duplicate_ids(tmp_path):
    qf = tmp_path / "quads.jsonl"
    qf.write_text(
        json.dumps(VALID_QUAD) + "\n" + json.dumps(VALID_QUAD) + "\n"
    )
    report = lint_quads(str(qf))
    assert "sha256-abc001" in report.duplicate_ids


def test_lint_detects_dark_matter(tmp_path):
    dark_quad = {**VALID_QUAD, "id": "sha256-dark", "dark_matter": True}
    qf = tmp_path / "quads.jsonl"
    qf.write_text(json.dumps(dark_quad) + "\n")
    report = lint_quads(str(qf))
    assert "sha256-dark" in report.dark_matter_ids


def test_lint_report_summary_counts(tmp_path):
    qf = tmp_path / "quads.jsonl"
    qf.write_text(json.dumps(VALID_QUAD) + "\n")
    report = lint_quads(str(qf))
    assert report.total_quads == 1
    assert report.confirmed_count == 1
    assert report.unverified_count == 0
