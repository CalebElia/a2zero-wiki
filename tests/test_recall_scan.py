import json


def _make_wiki(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "actors").mkdir()
    (wiki / "initiatives" / "aging-in-place-efficiently.md").write_text(
        "---\ntype: initiative\ntitle: Support Aging in Place Efficiently\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (wiki / "actors" / "dte-energy.md").write_text(
        "---\ntype: actor\ntitle: DTE Energy\n---\n\nBody.\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "entity_aliases.json").write_text(json.dumps({
        "detroit-edison": {
            "canonical": "actors/dte-energy", "type": "actor",
            "aliases": ["Detroit Edison", "DTE"], "relationship": "name-variant",
        },
    }), encoding="utf-8")
    return wiki


def test_index_contains_titles_aliases_and_verb_stripped_variants(tmp_path):
    from pipeline.recall_scan import build_entity_name_index
    wiki = _make_wiki(tmp_path)
    index = build_entity_name_index(str(wiki))
    assert index["support aging in place efficiently"] == "initiatives/aging-in-place-efficiently"
    # computed verb-prefix variant — the CAP-2020 naming convention
    assert index["aging in place efficiently"] == "initiatives/aging-in-place-efficiently"
    assert index["detroit edison"] == "actors/dte-energy"
    # names shorter than 4 chars are excluded ("DTE" alias)
    assert "dte" not in index


def test_scan_finds_word_boundary_mentions_only(tmp_path):
    from pipeline.recall_scan import build_entity_name_index, scan_source_for_known_entities
    wiki = _make_wiki(tmp_path)
    index = build_entity_name_index(str(wiki))
    source = (
        "The Aging in Place Efficiently program served 19 residents.\n"
        "Detroit Edison filed a rate case. Grandtedison is unrelated."
    )
    hits = scan_source_for_known_entities(source, index)
    assert hits["initiatives/aging-in-place-efficiently"]["mentions"] == 1
    assert hits["actors/dte-energy"]["mentions"] == 1
    assert len(hits) == 2


def test_scan_counts_multiple_mentions(tmp_path):
    from pipeline.recall_scan import build_entity_name_index, scan_source_for_known_entities
    wiki = _make_wiki(tmp_path)
    index = build_entity_name_index(str(wiki))
    source = "DTE Energy did X. Later, DTE Energy did Y. Detroit Edison history."
    hits = scan_source_for_known_entities(source, index)
    assert hits["actors/dte-energy"]["mentions"] == 3


def test_scan_matches_punctuation_ending_names(tmp_path):
    """~6% of real indexed names end in a parenthetical acronym ("... (MDOT)").
    A trailing \\b after ")" requires the NEXT char to be a word char, so those
    names silently never matched in prose — the inverse of a recall floor."""
    from pipeline.recall_scan import build_entity_name_index, scan_source_for_known_entities
    wiki = _make_wiki(tmp_path)
    (wiki / "actors" / "michigan-department-of-transportation.md").write_text(
        "---\ntype: actor\ntitle: Michigan Department of Transportation (MDOT)\n---\n\nBody.\n",
        encoding="utf-8",
    )
    index = build_entity_name_index(str(wiki))
    source = "Partners include the Michigan Department of Transportation (MDOT) for road work."
    hits = scan_source_for_known_entities(source, index)
    assert hits["actors/michigan-department-of-transportation"]["mentions"] == 1


def test_index_skips_aliases_whose_canonical_page_is_missing(tmp_path):
    """A stale registry entry pointing at a deleted/renamed page must not
    resurrect that slug in the index."""
    import json as _json
    from pipeline.recall_scan import build_entity_name_index
    wiki = _make_wiki(tmp_path)
    aliases_path = wiki.parent / "registry" / "entity_aliases.json"
    aliases = _json.loads(aliases_path.read_text(encoding="utf-8"))
    aliases["ghost-entry"] = {
        "canonical": "actors/deleted-long-ago", "type": "actor",
        "aliases": ["Ghost Organization Name"], "relationship": "name-variant",
    }
    aliases_path.write_text(_json.dumps(aliases), encoding="utf-8")
    index = build_entity_name_index(str(wiki))
    assert "ghost organization name" not in index
    assert "actors/deleted-long-ago" not in index.values()


def test_augment_adds_only_missing_slugs(tmp_path):
    from pipeline.recall_scan import augment_integration_plan
    plan = {
        "extends": [{"slug": "actors/dte-energy", "new-data": "rate case"}],
        "new-entities": [{"slug": "initiatives/brand-new-thing"}],
        "retrieve-for-context": ["actors/dte-energy"],
    }
    scan_hits = {
        "actors/dte-energy": {"matched-names": ["dte energy"], "mentions": 3},
        "initiatives/aging-in-place-efficiently": {"matched-names": ["aging in place efficiently"], "mentions": 2},
        "initiatives/brand-new-thing": {"matched-names": ["brand new thing"], "mentions": 1},
    }
    out = augment_integration_plan(plan, scan_hits)
    flagged_slugs = [e["slug"] for e in out["scan-flagged"]]
    # already in extends → not re-flagged; already in new-entities → not re-flagged
    assert flagged_slugs == ["initiatives/aging-in-place-efficiently"]
    assert out["scan-flagged"][0]["mentions"] == 2
    # appended to retrieve-for-context, existing entries preserved and first
    assert out["retrieve-for-context"] == [
        "actors/dte-energy", "initiatives/aging-in-place-efficiently",
    ]


def test_augment_orders_scan_slugs_by_mention_count(tmp_path):
    from pipeline.recall_scan import augment_integration_plan
    plan = {"extends": [], "new-entities": [], "retrieve-for-context": []}
    scan_hits = {
        "initiatives/rare": {"matched-names": ["rare"], "mentions": 1},
        "initiatives/common": {"matched-names": ["common"], "mentions": 9},
    }
    out = augment_integration_plan(plan, scan_hits)
    assert out["retrieve-for-context"] == ["initiatives/common", "initiatives/rare"]


def test_augment_handles_empty_hits():
    from pipeline.recall_scan import augment_integration_plan
    plan = {"extends": [], "new-entities": [], "retrieve-for-context": ["a/b"]}
    out = augment_integration_plan(plan, {})
    assert out["scan-flagged"] == []
    assert out["retrieve-for-context"] == ["a/b"]
