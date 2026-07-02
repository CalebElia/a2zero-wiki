# tests/test_alias_registry.py
import json
import pytest
from pathlib import Path
from pipeline._aliases import (
    load_aliases,
    save_aliases,
    resolve_slug,
    resolve_slug_for_title,
    fuzzy_resolve_slug_for_title,
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


# ── Type-aware resolution guard ────────────────────────────────────────────────
# Regression coverage for a real Year 4 ingest bug: an alias entry meant for a
# broad "funding topics" rollup also listed the exact name of a dedicated
# initiative ("Community Climate Action Millage") as a synonym. Pass 1.5
# followed it and silently wrote the initiative's new content into a topics/
# page instead of its own page. Entities must never resolve into a
# topic/synthesis/strategy/overview page — those synthesize FROM entities,
# they are never a substitute for an entity having its own page.

TOPIC_REDIRECT_ALIASES = {
    "local-state-funding-a2zero": {
        "canonical": "topics/local-state-funding-a2zero",
        "type": "topic",
        "aliases": ["Community Climate Action Millage", "state funding", "local funding"],
        "relationship": "name-variant",
    },
    "osi": {
        "canonical": "actors/osi",
        "type": "actor",
        "aliases": ["OSI"],
        "relationship": "name-variant",
    },
}


def test_resolve_slug_blocks_entity_redirect_into_topic():
    assert resolve_slug(
        "local-state-funding-a2zero", TOPIC_REDIRECT_ALIASES, proposed_type="initiative"
    ) is None


def test_resolve_slug_for_title_blocks_entity_redirect_into_topic():
    assert resolve_slug_for_title(
        "Community Climate Action Millage", TOPIC_REDIRECT_ALIASES, proposed_type="initiative"
    ) is None


def test_fuzzy_resolve_slug_for_title_blocks_entity_redirect_into_topic():
    assert fuzzy_resolve_slug_for_title(
        "Community Climate Action Millage", TOPIC_REDIRECT_ALIASES, proposed_type="initiative"
    ) is None


def test_resolve_slug_allows_non_entity_types_to_redirect_into_topic():
    """A topic_candidates-driven promotion (proposed_type="topic") legitimately
    targets a topics/ canonical — only real entity types are blocked."""
    assert resolve_slug(
        "local-state-funding-a2zero", TOPIC_REDIRECT_ALIASES, proposed_type="topic"
    ) == "topics/local-state-funding-a2zero"


def test_resolve_slug_without_proposed_type_keeps_old_behavior():
    """Callers that don't pass proposed_type (not yet updated) see unchanged
    behavior — the guard only activates when a type is actually supplied."""
    assert resolve_slug(
        "local-state-funding-a2zero", TOPIC_REDIRECT_ALIASES
    ) == "topics/local-state-funding-a2zero"


def test_resolve_slug_still_resolves_entity_to_entity():
    """The guard doesn't block legitimate entity-to-entity redirects."""
    assert resolve_slug("osi", TOPIC_REDIRECT_ALIASES, proposed_type="actor") == "actors/osi"


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
