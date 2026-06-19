import pytest
from pathlib import Path
from pipeline.post_ingest import generate_review_queue
from pipeline.quad_linter import LintReport


def test_generate_review_queue_creates_file(tmp_path):
    report = LintReport(
        total_quads=10,
        confirmed_count=8,
        unverified_count=2,
        schema_errors=[],
        duplicate_ids=[],
        dark_matter_ids=["sha256-dark1"],
    )
    out_path = tmp_path / "review-queue.md"
    generate_review_queue(
        report=report,
        source_uuid="a2zero-year1",
        out_path=str(out_path),
        run_date="2026-06-18",
    )
    assert out_path.exists()


def test_review_queue_contains_urgent_section_on_errors(tmp_path):
    report = LintReport(
        total_quads=5,
        confirmed_count=3,
        unverified_count=2,
        schema_errors=[{"line": 3, "id": "sha256-bad", "errors": ["missing field: date"]}],
        duplicate_ids=["sha256-dup1"],
        dark_matter_ids=[],
    )
    out_path = tmp_path / "review-queue.md"
    generate_review_queue(report=report, source_uuid="a2zero-year2",
                          out_path=str(out_path), run_date="2026-06-18")
    content = out_path.read_text()
    assert "🔴" in content
    assert "sha256-bad" in content
    assert "sha256-dup1" in content


def test_review_queue_contains_dark_matter_in_normal_tier(tmp_path):
    report = LintReport(
        total_quads=5,
        confirmed_count=5,
        unverified_count=0,
        schema_errors=[],
        duplicate_ids=[],
        dark_matter_ids=["sha256-dark1", "sha256-dark2"],
    )
    out_path = tmp_path / "review-queue.md"
    generate_review_queue(report=report, source_uuid="a2zero-year3",
                          out_path=str(out_path), run_date="2026-06-18")
    content = out_path.read_text()
    assert "🟡" in content
    assert "sha256-dark1" in content


def test_review_queue_shows_summary_stats(tmp_path):
    report = LintReport(
        total_quads=42,
        confirmed_count=40,
        unverified_count=2,
        schema_errors=[],
        duplicate_ids=[],
        dark_matter_ids=[],
    )
    out_path = tmp_path / "review-queue.md"
    generate_review_queue(report=report, source_uuid="a2zero-year5",
                          out_path=str(out_path), run_date="2026-06-18")
    content = out_path.read_text()
    assert "42" in content
    assert "a2zero-year5" in content
