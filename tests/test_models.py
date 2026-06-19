import hashlib
import pytest
from pipeline.models import make_quad_id, validate_quad


def test_quad_id_is_deterministic():
    id1 = make_quad_id("missy-stults", "leads", "osi", "2021")
    id2 = make_quad_id("missy-stults", "leads", "osi", "2021")
    assert id1 == id2


def test_quad_id_changes_with_different_inputs():
    id1 = make_quad_id("missy-stults", "leads", "osi", "2021")
    id2 = make_quad_id("missy-stults", "leads", "osi", "2022")
    assert id1 != id2


def test_quad_id_is_sha256_prefix():
    raw = "missy-stults|leads|osi|2021"
    expected = "sha256-" + hashlib.sha256(raw.encode()).hexdigest()[:16]
    assert make_quad_id("missy-stults", "leads", "osi", "2021") == expected


def test_validate_quad_accepts_valid():
    quad = {
        "id": "sha256-abc123",
        "date": "2021",
        "date_precision": "year",
        "subject": "missy-stults",
        "relation": "leads",
        "object": "osi",
        "sources": ["test-year1"],
        "source_types": ["annual-report"],
        "confidence": 2,
        "status": "confirmed",
        "dark_matter": False,
        "topics": [],
        "locations": [],
        "strategies": ["strategy-1"],
        "actors": ["actors/missy-stults"],
        "keywords": ["leadership"],
        "fund_type": None,
        "commitment_status": None,
        "last_updated": "2026-06-18",
    }
    errors = validate_quad(quad)
    assert errors == []


def test_validate_quad_rejects_missing_required():
    quad = {"id": "sha256-abc123"}
    errors = validate_quad(quad)
    assert any("date" in e for e in errors)
    assert any("subject" in e for e in errors)


def test_validate_quad_rejects_bad_confidence():
    quad = {
        "id": "sha256-x", "date": "2021", "date_precision": "year",
        "subject": "a", "relation": "b", "object": "c",
        "sources": ["s"], "source_types": ["annual-report"],
        "confidence": 3,  # invalid — must be 1 or 2
        "status": "confirmed", "dark_matter": False,
        "topics": [], "locations": [], "strategies": [],
        "actors": [], "keywords": [],
        "fund_type": None, "commitment_status": None,
        "last_updated": "2026-06-18",
    }
    errors = validate_quad(quad)
    assert any("confidence" in e for e in errors)


def test_validate_quad_rejects_bad_status():
    quad = {
        "id": "sha256-x", "date": "2021", "date_precision": "year",
        "subject": "a", "relation": "b", "object": "c",
        "sources": ["s"], "source_types": ["annual-report"],
        "confidence": 2, "status": "maybe",  # invalid
        "dark_matter": False, "topics": [], "locations": [],
        "strategies": [], "actors": [], "keywords": [],
        "fund_type": None, "commitment_status": None,
        "last_updated": "2026-06-18",
    }
    errors = validate_quad(quad)
    assert any("status" in e for e in errors)


def test_validate_quad_rejects_bad_date_precision():
    quad = {
        "id": "sha256-x", "date": "2021", "date_precision": "quarter",  # invalid
        "subject": "a", "relation": "b", "object": "c",
        "sources": ["s"], "source_types": ["annual-report"],
        "confidence": 2, "status": "confirmed",
        "dark_matter": False, "topics": [], "locations": [],
        "strategies": [], "actors": [], "keywords": [],
        "fund_type": None, "commitment_status": None,
        "last_updated": "2026-06-18",
    }
    errors = validate_quad(quad)
    assert any("date_precision" in e for e in errors)
