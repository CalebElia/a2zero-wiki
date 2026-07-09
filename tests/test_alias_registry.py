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


# ── Ambiguous-term resolution ──────────────────────────────────────────────────
# Some real-world names are genuinely ambiguous between two legitimate,
# different-typed entities depending on sentence intent (a place vs. the
# government acting as an actor; a plan vs. its administering office). The
# LLM's own type judgment (already threaded through as proposed_type at both
# Pass 1.5 call sites) should pick between candidates instead of being
# discarded by a flat, type-blind alias lookup.

AMBIGUOUS_SAMPLE = {
    "_ambiguous_terms": [
        {
            "aliases": ["Ann Arbor"],
            "candidates": [
                {"type": "location", "canonical": "locations/ann-arbor"},
                {"type": "actor", "canonical": "actors/city-of-ann-arbor"},
            ],
            "default": "locations/ann-arbor",
        },
    ],
    "osi": {
        "canonical": "actors/osi",
        "type": "actor",
        "aliases": ["OSI", "Office of Sustainability and Innovations"],
        "relationship": "name-variant",
    },
}


def test_resolve_slug_ambiguous_term_by_proposed_type():
    assert resolve_slug("ann-arbor", AMBIGUOUS_SAMPLE, proposed_type="actor") == "actors/city-of-ann-arbor"
    assert resolve_slug("ann-arbor", AMBIGUOUS_SAMPLE, proposed_type="location") == "locations/ann-arbor"


def test_resolve_slug_ambiguous_term_no_matching_candidate_returns_none():
    """A proposed_type that matches neither candidate must never force a guess —
    let the normal fallback chain (ultimately new-stub creation) decide."""
    assert resolve_slug("ann-arbor", AMBIGUOUS_SAMPLE, proposed_type="initiative") is None


def test_resolve_slug_ambiguous_term_no_type_uses_default():
    assert resolve_slug("ann-arbor", AMBIGUOUS_SAMPLE) == "locations/ann-arbor"


def test_resolve_slug_for_title_ambiguous_term_by_proposed_type():
    assert resolve_slug_for_title("Ann Arbor", AMBIGUOUS_SAMPLE, proposed_type="actor") == "actors/city-of-ann-arbor"
    assert resolve_slug_for_title("Ann Arbor", AMBIGUOUS_SAMPLE, proposed_type="location") == "locations/ann-arbor"


def test_fuzzy_resolve_slug_for_title_ambiguous_term_typo_tolerant():
    assert fuzzy_resolve_slug_for_title("Ann Arbour", AMBIGUOUS_SAMPLE, proposed_type="location") == "locations/ann-arbor"


def test_resolve_slug_for_title_skips_reserved_key_without_crashing():
    """_ambiguous_terms' value is a list, not a dict — the normal entry-scanning
    loop must explicitly skip it or entry.get(...) raises AttributeError."""
    assert resolve_slug_for_title("Office of Sustainability and Innovations", AMBIGUOUS_SAMPLE) == "actors/osi"


def test_fuzzy_resolve_slug_for_title_skips_reserved_key_without_crashing():
    assert fuzzy_resolve_slug_for_title("Office of Sustainability & Innovations", AMBIGUOUS_SAMPLE) == "actors/osi"


def test_add_alias_rejects_writing_to_reserved_key(tmp_path):
    p = tmp_path / "aliases.json"
    save_aliases({}, str(p))
    with pytest.raises(ValueError):
        add_alias(
            slug="_ambiguous_terms",
            canonical="actors/osi",
            entity_type="actor",
            alias_labels=["X"],
            aliases_path=str(p),
        )


def test_build_ambiguous_terms_block_empty_registry_returns_empty_string(tmp_path):
    from pipeline._aliases import build_ambiguous_terms_block
    p = tmp_path / "aliases.json"
    save_aliases({}, str(p))
    assert build_ambiguous_terms_block(str(p)) == ""


def test_build_ambiguous_terms_block_wraps_entries_in_brackets(tmp_path):
    from pipeline._aliases import build_ambiguous_terms_block
    p = tmp_path / "aliases.json"
    save_aliases(AMBIGUOUS_SAMPLE, str(p))
    block = build_ambiguous_terms_block(str(p))
    assert "[AMBIGUOUS NAMES" in block
    assert "[END AMBIGUOUS NAMES]" in block
    assert "Ann Arbor" in block
    assert "actors/city-of-ann-arbor" in block
    assert "locations/ann-arbor" in block


# ── Regression: the two live shadowing bugs, verified against real production
# data (registry/entity_aliases.json), not just a fixture ─────────────────────

REAL_ALIASES_PATH = "registry/entity_aliases.json"


def test_no_flat_entries_shadow_ambiguous_terms():
    aliases = load_aliases(REAL_ALIASES_PATH)
    for shadow_key in ("ann-arbor", "a2zero", "a2zero-as-actor", "washtenaw-county", "state-of-michigan"):
        assert shadow_key not in aliases, f"{shadow_key!r} should be covered by _ambiguous_terms, not a flat entry"


def test_ann_arbor_resolves_by_proposed_type_real_registry():
    aliases = load_aliases(REAL_ALIASES_PATH)
    assert resolve_slug("ann-arbor", aliases, proposed_type="location") == "locations/ann-arbor"
    assert resolve_slug("ann-arbor", aliases, proposed_type="actor") == "actors/city-of-ann-arbor"


def test_a2zero_resolves_by_proposed_type_real_registry():
    aliases = load_aliases(REAL_ALIASES_PATH)
    assert resolve_slug_for_title("A2Zero", aliases, proposed_type="plan") == "plans/a2zero-carbon-neutrality-plan"
    assert resolve_slug_for_title("A2Zero", aliases, proposed_type="actor") == "actors/office-of-sustainability-and-innovations"


def test_washtenaw_county_resolves_by_proposed_type_real_registry():
    aliases = load_aliases(REAL_ALIASES_PATH)
    assert resolve_slug_for_title("Washtenaw County", aliases, proposed_type="location") == "locations/washtenaw-county"
    assert resolve_slug_for_title("Washtenaw County", aliases, proposed_type="actor") == "actors/washtenaw-county"


def test_michigan_resolves_by_proposed_type_real_registry():
    aliases = load_aliases(REAL_ALIASES_PATH)
    assert resolve_slug_for_title("Michigan", aliases, proposed_type="location") == "locations/michigan"
    assert resolve_slug_for_title("State of Michigan", aliases, proposed_type="actor") == "actors/state-of-michigan"


def test_ambiguous_term_with_no_matching_candidate_falls_through_real_registry():
    """A wrong-type guess for an ambiguous term must not force a redirect —
    existing unrelated entity resolution stays completely unaffected."""
    aliases = load_aliases(REAL_ALIASES_PATH)
    assert resolve_slug("ann-arbor", aliases, proposed_type="funding-event") is None
    assert resolve_slug("osi", aliases, proposed_type="actor") == "actors/office-of-sustainability-and-innovations"
