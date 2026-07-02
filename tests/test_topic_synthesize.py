import pytest
from pathlib import Path
from unittest.mock import patch
from pipeline.topic_synthesize import (
    append_query_log_entry,
    parse_query_log,
    extract_cited_slugs,
    validate_cited_entities,
    detect_citation_cycle,
    slugify_question,
    build_topic_page,
    promote_query_log_entries,
    pull_full_entity_bodies,
    regenerate_topic,
    find_topics_touched,
)


def test_append_query_log_entry_writes_to_fresh_file(tmp_path):
    log_path = tmp_path / "query-log.md"
    append_query_log_entry(
        question="How did the Bryant project braid its funding sources?",
        answer_text="The project combined [[funding-events/epa-ej-grant-2024]] "
                     "and [[actors/city-of-ann-arbor]] contributions.",
        wiki_root=str(tmp_path / "wiki"),
        query_log_path=str(log_path),
        run_date="2026-07-02",
    )
    content = log_path.read_text(encoding="utf-8")
    assert "## How did the Bryant project braid its funding sources? | 2026-07-02" in content
    assert "[[funding-events/epa-ej-grant-2024]]" in content
    assert "Resolution: [ ] Promote to wiki/topics/<slug>.md  [ ] Dismiss" in content


def test_append_query_log_entry_appends_without_clobbering_existing(tmp_path):
    log_path = tmp_path / "query-log.md"
    log_path.write_text("# Query Log\n\nsome header content\n", encoding="utf-8")
    append_query_log_entry(
        question="Question one?",
        answer_text="Answer one.",
        wiki_root=str(tmp_path / "wiki"),
        query_log_path=str(log_path),
        run_date="2026-07-02",
    )
    content = log_path.read_text(encoding="utf-8")
    assert "some header content" in content
    assert "## Question one? | 2026-07-02" in content


def test_append_query_log_entry_is_idempotent_for_identical_question_and_date(tmp_path):
    log_path = tmp_path / "query-log.md"
    for _ in range(2):
        append_query_log_entry(
            question="Same question?",
            answer_text="Same answer.",
            wiki_root=str(tmp_path / "wiki"),
            query_log_path=str(log_path),
            run_date="2026-07-02",
        )
    content = log_path.read_text(encoding="utf-8")
    assert content.count("## Same question? | 2026-07-02") == 1


# ── Parsing layer ───────────────────────────────────────────────────────────

def _fixture_log(tmp_path, extra_body=""):
    log_path = tmp_path / "query-log.md"
    log_path.write_text(
        "# Query Log\n\nheader text\n\n"
        "## How did Bryant fund itself? | 2026-07-01\n"
        "Answer citing [[funding-events/epa-ej-grant-2024]] and "
        "[[actors/city-of-ann-arbor]] and [[topics/local-state-funding-a2zero]].\n"
        "Resolution: [x] Promote to wiki/topics/<slug>.md  [ ] Dismiss\n"
        "\n"
        "## Unrelated question? | 2026-07-02\n"
        "Some other answer.\n"
        "Resolution: [ ] Promote to wiki/topics/<slug>.md  [x] Dismiss\n"
        + extra_body,
        encoding="utf-8",
    )
    return log_path


def test_parse_query_log_round_trips_fixture(tmp_path):
    log_path = _fixture_log(tmp_path)
    entries = parse_query_log(str(log_path))
    assert len(entries) == 2
    assert entries[0]["question"] == "How did Bryant fund itself?"
    assert entries[0]["date"] == "2026-07-01"
    assert entries[0]["promote"] is True
    assert entries[0]["dismiss"] is False
    assert "[[funding-events/epa-ej-grant-2024]]" in entries[0]["answer"]
    assert entries[1]["question"] == "Unrelated question?"
    assert entries[1]["promote"] is False
    assert entries[1]["dismiss"] is True


def test_parse_query_log_missing_file_returns_empty():
    assert parse_query_log("/nonexistent/query-log.md") == []


def test_extract_cited_slugs_finds_entity_and_topic_wikilinks():
    answer = (
        "Braided [[funding-events/epa-ej-grant-2024]] with "
        "[[actors/city-of-ann-arbor|the City]] and referenced "
        "[[topics/local-state-funding-a2zero]]."
    )
    slugs = extract_cited_slugs(answer)
    assert slugs == [
        "funding-events/epa-ej-grant-2024",
        "actors/city-of-ann-arbor",
        "topics/local-state-funding-a2zero",
    ]


def test_extract_cited_slugs_deduplicates():
    answer = "[[actors/dte-energy]] mentioned twice: [[actors/dte-energy|DTE]]."
    assert extract_cited_slugs(answer) == ["actors/dte-energy"]


def test_validate_cited_entities_surfaces_missing_loudly(tmp_path):
    root = tmp_path / "wiki"
    (root / "actors").mkdir(parents=True)
    (root / "actors" / "dte-energy.md").write_text("---\ntype: actor\n---\n", encoding="utf-8")
    valid, missing = validate_cited_entities(
        ["actors/dte-energy", "actors/hallucinated-entity"], str(root)
    )
    assert valid == ["actors/dte-energy"]
    assert missing == ["actors/hallucinated-entity"]


def test_detect_citation_cycle_finds_a_to_b_to_a(tmp_path):
    root = tmp_path / "wiki"
    (root / "topics").mkdir(parents=True)
    (root / "topics" / "topic-a.md").write_text(
        "---\ntype: topic\ncited-topics: [topics/topic-b]\n---\n", encoding="utf-8"
    )
    (root / "topics" / "topic-b.md").write_text(
        "---\ntype: topic\ncited-topics: [topics/topic-c]\n---\n", encoding="utf-8"
    )
    (root / "topics" / "topic-c.md").write_text(
        "---\ntype: topic\ncited-topics: [topics/topic-a]\n---\n", encoding="utf-8"
    )
    cycle = detect_citation_cycle("topics/topic-a", ["topics/topic-b"], str(root))
    assert cycle == ["topics/topic-a", "topics/topic-b", "topics/topic-c", "topics/topic-a"]


def test_detect_citation_cycle_returns_empty_for_acyclic_graph(tmp_path):
    root = tmp_path / "wiki"
    (root / "topics").mkdir(parents=True)
    (root / "topics" / "topic-b.md").write_text(
        "---\ntype: topic\ncited-topics: []\n---\n", encoding="utf-8"
    )
    cycle = detect_citation_cycle("topics/topic-a", ["topics/topic-b"], str(root))
    assert cycle == []


def test_slugify_question_produces_kebab_case():
    assert slugify_question("How did the Bryant project braid its funding sources?") == \
        "how-did-the-bryant-project-braid-its-funding-sources"


# ── Promotion path ───────────────────────────────────────────────────────────

def _make_entity_wiki(tmp_path):
    root = tmp_path / "wiki"
    (root / "actors").mkdir(parents=True)
    (root / "actors" / "city-of-ann-arbor.md").write_text("---\ntype: actor\n---\n", encoding="utf-8")
    (root / "funding-events").mkdir(parents=True)
    (root / "funding-events" / "epa-ej-grant-2024.md").write_text("---\ntype: funding-event\n---\n", encoding="utf-8")
    return root


def test_build_topic_page_has_expected_frontmatter():
    page = build_topic_page(
        question="How did Bryant fund itself?",
        answer_text="Funded via [[funding-events/epa-ej-grant-2024]].",
        cited_entities=["funding-events/epa-ej-grant-2024"],
        cited_topics=[],
        run_date="2026-07-02",
    )
    assert page.slug == "topics/how-did-bryant-fund-itself"
    assert page.frontmatter["type"] == "topic"
    assert page.frontmatter["governance"] == "synthesized"
    assert page.frontmatter["cited-entities"] == ["funding-events/epa-ej-grant-2024"]
    assert "epa-ej-grant-2024" in page.body


def test_promote_query_log_entries_writes_page_and_clears_entry(tmp_path):
    root = _make_entity_wiki(tmp_path)
    log_path = tmp_path / "query-log.md"
    log_path.write_text(
        "# Query Log\n\n"
        "## How did Bryant fund itself? | 2026-07-01\n"
        "Funded via [[funding-events/epa-ej-grant-2024]] and [[actors/city-of-ann-arbor]].\n"
        "Resolution: [x] Promote to wiki/topics/<slug>.md  [ ] Dismiss\n",
        encoding="utf-8",
    )
    result = promote_query_log_entries(
        wiki_root=str(root), query_log_path=str(log_path), run_date="2026-07-02"
    )
    assert result["promoted"] == ["topics/how-did-bryant-fund-itself"]
    page_path = root / "topics" / "how-did-bryant-fund-itself.md"
    assert page_path.exists()
    assert "epa-ej-grant-2024" in page_path.read_text(encoding="utf-8")
    assert "How did Bryant fund itself?" not in log_path.read_text(encoding="utf-8")


def test_promote_query_log_entries_hard_fails_on_hallucinated_entity(tmp_path):
    root = _make_entity_wiki(tmp_path)
    log_path = tmp_path / "query-log.md"
    log_path.write_text(
        "## Bogus question? | 2026-07-01\n"
        "Cites [[actors/does-not-exist]].\n"
        "Resolution: [x] Promote to wiki/topics/<slug>.md  [ ] Dismiss\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does-not-exist"):
        promote_query_log_entries(
            wiki_root=str(root), query_log_path=str(log_path), run_date="2026-07-02"
        )


def test_promote_query_log_entries_rejects_cyclic_topic_citation(tmp_path):
    root = _make_entity_wiki(tmp_path)
    (root / "topics").mkdir(parents=True)
    # topic-b cites the not-yet-created topic slug for this question, creating a cycle
    (root / "topics" / "topic-b.md").write_text(
        "---\ntype: topic\ncited-topics: [topics/does-bryant-loop]\n---\n", encoding="utf-8"
    )
    log_path = tmp_path / "query-log.md"
    log_path.write_text(
        "## Does Bryant loop? | 2026-07-01\n"
        "Cites [[topics/topic-b]].\n"
        "Resolution: [x] Promote to wiki/topics/<slug>.md  [ ] Dismiss\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cycle"):
        promote_query_log_entries(
            wiki_root=str(root), query_log_path=str(log_path), run_date="2026-07-02"
        )


# ── Regeneration path — anti-drift regression tests ─────────────────────────
# These encode the commit-6049b00 lesson directly: regeneration must always
# see the FULL prior text and FULL current cited bodies, fresh from disk,
# never a cached or summarized version.

def test_pull_full_entity_bodies_reads_fresh_from_disk_not_cached(tmp_path):
    root = tmp_path / "wiki"
    (root / "actors").mkdir(parents=True)
    entity_path = root / "actors" / "dte-energy.md"
    entity_path.write_text("---\ntype: actor\n---\n\nOriginal body text.\n", encoding="utf-8")

    first = pull_full_entity_bodies(str(root), ["actors/dte-energy"])
    assert "Original body text." in first["actors/dte-energy"]

    entity_path.write_text("---\ntype: actor\n---\n\nMUTATED body text.\n", encoding="utf-8")
    second = pull_full_entity_bodies(str(root), ["actors/dte-energy"])
    assert "MUTATED body text." in second["actors/dte-energy"]
    assert "Original body text." not in second["actors/dte-energy"]


@patch("pipeline.topic_synthesize.chat")
def test_regenerate_topic_injects_full_prior_narrative_not_summary(mock_chat, tmp_path):
    root = tmp_path / "wiki"
    (root / "topics").mkdir(parents=True)
    (root / "actors").mkdir(parents=True)

    marker = "DISTINCTIVE-MARKER-PRIOR-FACT-77"
    (root / "topics" / "how-was-it-funded.md").write_text(
        "---\ntype: topic\ncited-entities: [actors/dte-energy]\ncited-topics: []\n"
        "title: How was it funded?\n---\n\n"
        f"Prior narrative fact: {marker} ([[actors/dte-energy|DTE Energy]]).\n",
        encoding="utf-8",
    )
    (root / "actors" / "dte-energy.md").write_text(
        "---\ntype: actor\n---\n\nDTE Energy current body.\n", encoding="utf-8"
    )

    mock_chat.return_value = f"Reweaved narrative preserving {marker} and new info."

    result = regenerate_topic("topics/how-was-it-funded", str(root), run_date="2026-07-02")

    assert result is not None
    captured_prompt = mock_chat.call_args.kwargs["messages"][0]["content"]
    assert marker in captured_prompt
    assert "DTE Energy current body." in captured_prompt


@patch("pipeline.topic_synthesize.chat")
def test_regenerate_topic_falls_back_to_existing_body_on_llm_failure(mock_chat, tmp_path):
    root = tmp_path / "wiki"
    (root / "topics").mkdir(parents=True)
    original = (
        "---\ntype: topic\ncited-entities: []\ncited-topics: []\n"
        "title: X\n---\n\nOriginal narrative, must survive.\n"
    )
    page_path = root / "topics" / "x.md"
    page_path.write_text(original, encoding="utf-8")

    mock_chat.side_effect = Exception("LLM call failed")

    result = regenerate_topic("topics/x", str(root), run_date="2026-07-02")

    assert result is None
    assert page_path.read_text(encoding="utf-8") == original


# ── find_topics_touched ──────────────────────────────────────────────────────

def test_find_topics_touched_matches_cited_entities(tmp_path):
    root = tmp_path / "wiki"
    (root / "topics").mkdir(parents=True)
    (root / "topics" / "t1.md").write_text(
        "---\ntype: topic\ncited-entities: [actors/dte-energy]\ncited-topics: []\n---\n",
        encoding="utf-8",
    )
    (root / "topics" / "t2.md").write_text(
        "---\ntype: topic\ncited-entities: [actors/unrelated]\ncited-topics: []\n---\n",
        encoding="utf-8",
    )
    touched = find_topics_touched(str(root), ["actors/dte-energy"])
    assert touched == ["topics/t1"]


def test_find_topics_touched_skips_frozen_governance(tmp_path):
    root = tmp_path / "wiki"
    (root / "topics").mkdir(parents=True)
    (root / "topics" / "frozen-t.md").write_text(
        "---\ntype: topic\ngovernance: frozen\ncited-entities: [actors/dte-energy]\n"
        "cited-topics: []\n---\n",
        encoding="utf-8",
    )
    touched = find_topics_touched(str(root), ["actors/dte-energy"])
    assert touched == []


# ── End-to-end: log → promote → touch entity → detect → regenerate → validate ─

@patch("pipeline.topic_synthesize.chat")
def test_full_topic_lifecycle_end_to_end(mock_chat, tmp_path):
    from pipeline.phase_b_lint import structural_lint

    root = tmp_path / "wiki"
    (root / "actors").mkdir(parents=True)
    (root / "actors" / "dte-energy.md").write_text(
        "---\ntype: actor\ntitle: DTE Energy\n---\n\nOriginal DTE body.\n", encoding="utf-8"
    )
    log_path = tmp_path / "query-log.md"

    # 1. Log a query
    append_query_log_entry(
        question="How was the grid strategy funded?",
        answer_text="Funded via [[actors/dte-energy|DTE Energy]] partnership.",
        wiki_root=str(root),
        query_log_path=str(log_path),
        run_date="2026-07-01",
    )
    # Mark it Promote (simulating the human review step)
    content = log_path.read_text(encoding="utf-8")
    content = content.replace(
        "Resolution: [ ] Promote to wiki/topics/<slug>.md  [ ] Dismiss",
        "Resolution: [x] Promote to wiki/topics/<slug>.md  [ ] Dismiss",
    )
    log_path.write_text(content, encoding="utf-8")

    # 2. Promote
    result = promote_query_log_entries(
        wiki_root=str(root), query_log_path=str(log_path), run_date="2026-07-01"
    )
    topic_slug = result["promoted"][0]
    assert topic_slug == "topics/how-was-the-grid-strategy-funded"
    assert (root / f"{topic_slug}.md").exists()

    # 3. Touch the cited entity (simulating a new ingest updating its body)
    (root / "actors" / "dte-energy.md").write_text(
        "---\ntype: actor\ntitle: DTE Energy\n---\n\nUpdated DTE body with new grant info.\n",
        encoding="utf-8",
    )

    # 4. Detect
    touched = find_topics_touched(str(root), ["actors/dte-energy"])
    assert touched == [topic_slug]

    # 5. Regenerate
    mock_chat.return_value = "Reweaved: DTE Energy partnership, now including the new grant."
    new_body = regenerate_topic(topic_slug, str(root), run_date="2026-07-02")
    assert new_body is not None
    assert "new grant" in new_body

    # 6. Validate — no structural lint violations for the topic citation direction
    findings = structural_lint(str(root))
    violations = [f for f in findings if f["type"] == "TOPIC_CITATION_VIOLATION"]
    assert violations == []

    # 7. Confirm digest unaffected — no digest exists in this fixture, and no
    # page in the wiki references the topic (only the topic cites the entity)
    assert not (root / "digest.md").exists()
