# tests/test_alias_registry.py
import json
import pytest
from pathlib import Path
from pipeline._aliases import (
    load_aliases,
    save_aliases,
    resolve_slug,
    resolve_slug_for_title,
    fuzzy_candidates,
    add_alias,
)

SAMPLE_ALIASES = {
    "osi": {
        "canonical": "actors/osi",
        "type": "actor",
        "aliases": ["OSI", "Office of Sustainability and Innovations"],
        "relationship": "name-variant",
    },
    "seu": {
        "canonical": "actors/osi",
        "type": "actor",
        "aliases": ["Sustainable Energy Utility", "SEU"],
        "relationship": "predecessor",
        "as-of": "2022",
        "notes": "SEU restructured into OSI per Year 2 annual report",
    },
}


def test_load_aliases(tmp_path):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps(SAMPLE_ALIASES), encoding="utf-8")
    result = load_aliases(str(p))
    assert "osi" in result
    assert result["osi"]["canonical"] == "actors/osi"


def test_load_aliases_missing_file_returns_empty(tmp_path):
    result = load_aliases(str(tmp_path / "nonexistent.json"))
    assert result == {}


def test_save_aliases_round_trips(tmp_path):
    p = tmp_path / "aliases.json"
    save_aliases(SAMPLE_ALIASES, str(p))
    result = load_aliases(str(p))
    assert result == SAMPLE_ALIASES


def test_resolve_slug_known_key():
    assert resolve_slug("osi", SAMPLE_ALIASES) == "actors/osi"


def test_resolve_slug_unknown_returns_none():
    assert resolve_slug("unknown-entity", SAMPLE_ALIASES) is None


def test_resolve_slug_for_title_case_insensitive():
    assert resolve_slug_for_title("office of sustainability and innovations", SAMPLE_ALIASES) == "actors/osi"


def test_resolve_slug_for_title_unknown_returns_none():
    assert resolve_slug_for_title("completely unknown entity", SAMPLE_ALIASES) is None


def test_fuzzy_candidates_finds_near_match():
    titles = ["Office of Sustainability and Innovations", "Ann Arbor City Council", "DTE Energy"]
    result = fuzzy_candidates("Office of Sustainability & Innovations", titles, threshold=0.7)
    assert "Office of Sustainability and Innovations" in result


def test_fuzzy_candidates_ignores_distinct_entities():
    titles = ["Ann Arbor City Council", "DTE Energy", "University of Michigan"]
    result = fuzzy_candidates("Completely Different Thing", titles, threshold=0.7)
    assert result == []


def test_add_alias_writes_to_file(tmp_path):
    p = tmp_path / "aliases.json"
    save_aliases({}, str(p))
    add_alias(
        slug="seu",
        canonical="actors/osi",
        entity_type="actor",
        alias_labels=["SEU", "Sustainable Energy Utility"],
        relationship="predecessor",
        aliases_path=str(p),
        as_of="2022",
        notes="SEU restructured into OSI",
    )
    result = load_aliases(str(p))
    assert "seu" in result
    assert result["seu"]["canonical"] == "actors/osi"
    assert result["seu"]["relationship"] == "predecessor"
    assert result["seu"]["as-of"] == "2022"
