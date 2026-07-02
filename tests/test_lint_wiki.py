# tests/test_lint_wiki.py
import json
import pytest
from pathlib import Path


def _make_wiki(tmp_path: Path) -> Path:
    """Create a minimal wiki for lint testing."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "actors").mkdir()
    (wiki / "initiatives").mkdir()

    # Good page — has inbound link, valid wikilink
    (wiki / "actors" / "osi.md").write_text(
        "---\ntype: actor\ntitle: OSI\n---\n"
        "The OSI leads A2Zero. ([[sources/cap/cap-2020|cap-2020]])\n"
    )
    # Page with broken wikilink
    (wiki / "actors" / "broken.md").write_text(
        "---\ntype: actor\ntitle: Broken Actor\n---\n"
        "See [[actors/nonexistent]].\n"
    )
    # Orphaned page (no other page links to it)
    (wiki / "initiatives" / "orphan-program.md").write_text(
        "---\ntype: initiative\ntitle: Orphan Program\n---\n"
        "This initiative exists. ([[actors/osi|OSI]])\n"
    )
    # Index page linking to osi and broken
    (wiki / "index.md").write_text(
        "# Index\n- [[actors/osi|OSI]]\n- [[actors/broken|Broken]]\n"
    )
    return wiki


def test_structural_finds_broken_link(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    findings = structural_lint(str(wiki))
    broken = [f for f in findings if f["type"] == "BROKEN_LINK"]
    assert any("actors/nonexistent" in f["detail"] for f in broken)


def test_structural_finds_orphan(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    findings = structural_lint(str(wiki))
    orphans = [f for f in findings if f["type"] == "ORPHAN"]
    assert any("orphan-program" in f["page"] for f in orphans)


def test_structural_no_false_positive_for_osi(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    findings = structural_lint(str(wiki))
    orphans = [f for f in findings if f["type"] == "ORPHAN"]
    assert not any("osi" in f["page"] for f in orphans)


def test_structural_skips_exempt_pages(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    # index.md is exempt from orphan check
    findings = structural_lint(str(wiki))
    orphans = [f for f in findings if f["type"] == "ORPHAN"]
    assert not any(f["page"].endswith("index.md") for f in orphans)


def test_semantic_lint_calls_llm_for_candidates(tmp_path):
    """Stage 2 LLM verdict is called when Stage 1 fuzzy match finds candidates."""
    import json
    from unittest.mock import patch, MagicMock

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    actors = wiki / "actors"
    actors.mkdir()

    # Two pages with very similar titles — should trigger fuzzy candidate
    (actors / "osi.md").write_text(
        "---\ntype: actor\ntitle: Office of Sustainability and Innovations\n---\nLeads A2Zero.\n"
    )
    (actors / "office-of-sustainability.md").write_text(
        "---\ntype: actor\ntitle: Office of Sustainability\n---\nCity sustainability office.\n"
    )

    verdict = {"relationship": "same", "confidence": 0.92, "reasoning": "Same office."}

    with patch("pipeline.phase_b_lint.chat") as mock_chat:
        mock_chat.return_value = json.dumps(verdict)
        from pipeline.phase_b_lint import semantic_lint
        proposals = semantic_lint(str(wiki))

    assert len(proposals) == 1
    assert proposals[0]["type"] == "MERGE_PROPOSED"
    assert proposals[0]["confidence"] == 0.92


def test_semantic_lint_skips_meetings_with_different_dates_without_calling_llm(tmp_path):
    """Regression: two meetings with similar titles but different dates must
    never be proposed as a merge — a meeting is a point-in-time event, and a
    date mismatch conclusively proves the pages are distinct. A prior lint run
    proposed merging two real meetings four months apart with the LLM's own
    reasoning self-contradicting ('different dated events... same entity')."""
    from unittest.mock import patch

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    meetings = wiki / "meetings"
    meetings.mkdir()

    (meetings / "2019-12-13-a2zero-partners.md").write_text(
        "---\ntype: meeting\ntitle: A2ZERO Partners — 2019-12-13 (First Partner Meeting)\n"
        "date: '2019-12-13'\n---\nFirst convening.\n"
    )
    (meetings / "2020-03-20-a2zero-partners-strategy-unveiling.md").write_text(
        "---\ntype: meeting\ntitle: A2ZERO Partners — 2020-03-20 (Final Strategy Unveiling)\n"
        "date: '2020-03-20'\n---\nStrategy unveiling.\n"
    )

    with patch("pipeline.phase_b_lint.chat") as mock_chat:
        from pipeline.phase_b_lint import semantic_lint
        proposals = semantic_lint(str(wiki))

    assert proposals == []
    mock_chat.assert_not_called()


def test_semantic_lint_still_compares_meetings_with_same_date(tmp_path):
    """Same-date meeting pages (e.g. duplicate extraction) should still reach
    the LLM verdict — the date-awareness guard only blocks differing dates."""
    import json
    from unittest.mock import patch

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    meetings = wiki / "meetings"
    meetings.mkdir()

    (meetings / "2020-03-20-a2zero-unveiling.md").write_text(
        "---\ntype: meeting\ntitle: A2ZERO Strategy Unveiling\ndate: '2020-03-20'\n---\nEvent A.\n"
    )
    (meetings / "2020-03-20-a2zero-strategy-unveiling.md").write_text(
        "---\ntype: meeting\ntitle: A2ZERO Strategy Unveiling Event\ndate: '2020-03-20'\n---\nEvent B.\n"
    )

    verdict = {"relationship": "same", "confidence": 0.9, "reasoning": "Duplicate extraction."}
    with patch("pipeline.phase_b_lint.chat") as mock_chat:
        mock_chat.return_value = json.dumps(verdict)
        from pipeline.phase_b_lint import semantic_lint
        proposals = semantic_lint(str(wiki))

    assert len(proposals) == 1
    mock_chat.assert_called_once()


def test_parse_approved_proposals_finds_checked_merge(tmp_path):
    from pipeline.phase_b_lint import _parse_approved_proposals
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "## Semantic Lint — 2026-06-25\n\n"
        "### [MERGE_PROPOSED] actors/osi.md + actors/office-of-sustainability.md\n"
        "- Confidence: 0.91\n"
        "- Reasoning: Same office.\n"
        "- Action: [x] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER\n",
        encoding="utf-8",
    )
    proposals = _parse_approved_proposals(str(rq))
    assert len(proposals) == 1
    assert proposals[0]["approved_action"] == "MERGE"
    assert proposals[0]["page_a"] == "actors/osi.md"


def test_structural_finds_empty_page(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    (wiki / "actors" / "ghost.md").write_text("", encoding="utf-8")
    findings = structural_lint(str(wiki))
    empty = [f for f in findings if f["type"] == "EMPTY_PAGE"]
    assert any("ghost" in f["page"] for f in empty)


def test_structural_finds_stub_page(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    (wiki / "actors" / "stub-actor.md").write_text(
        "---\ntype: actor\ntitle: Stub Actor\n---\n<!-- Body populated by holistic synthesizer -->\n",
        encoding="utf-8",
    )
    findings = structural_lint(str(wiki))
    stubs = [f for f in findings if f["type"] == "STUB_PAGE"]
    assert any("stub-actor" in f["page"] for f in stubs)


def test_structural_exempt_pages_skip_empty_check(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    # index.md is already empty-ish in _make_wiki; confirm it is not flagged
    findings = structural_lint(str(wiki))
    empty = [f for f in findings if f["type"] in ("EMPTY_PAGE", "STUB_PAGE")]
    assert not any(f["page"].endswith("index.md") for f in empty)


def test_apply_proposals_link_skips_matches_inside_existing_wikilinks(tmp_path):
    """Regression: a LINK proposal whose display_text is a case-insensitive
    substring of an EXISTING wikilink's slug (e.g. 'vegmichigan' inside
    [[actors/vegmichigan|VegMichigan]]) must not get wrapped in a second,
    nested wikilink — that produced real corruption
    ([[actors/[[actors/vegmichigan|vegmichigan]]|VegMichigan]]) in production."""
    from pipeline.phase_b_lint import apply_proposals

    root = tmp_path / "project"
    wiki = root / "wiki"
    (wiki / "strategies").mkdir(parents=True)
    (wiki / "strategies" / "strategy-5.md").write_text(
        "---\ntype: strategy\n---\n\n"
        "OSI partnered with [[actors/vegmichigan|VegMichigan]] on plant-forward diets. "
        "VegMichigan also engaged local businesses.\n",
        encoding="utf-8",
    )
    (root / "review-queue.md").write_text(
        "## Backlink Lint — 2026-07-02\n\n"
        "### [LINK_PROPOSED] strategies/strategy-5.md ← actors/vegmichigan\n"
        "- Display text: \"vegmichigan\"\n"
        "- Action: [x] APPROVE_LINK  [ ] KEEP_UNLINKED  [ ] DEFER\n",
        encoding="utf-8",
    )

    apply_proposals(
        wiki_root=str(wiki),
        aliases_path=str(tmp_path / "aliases.json"),
        merge_log_path=str(tmp_path / "merge-log.jsonl"),
    )

    content = (wiki / "strategies" / "strategy-5.md").read_text(encoding="utf-8")
    assert "[[actors/[[" not in content
    # The pre-existing wikilink must be untouched, and the second bare
    # mention ("VegMichigan also engaged...") should get linked instead.
    assert "[[actors/vegmichigan|VegMichigan]] on plant-forward diets" in content
    assert content.count("[[actors/vegmichigan") == 2


def test_apply_proposals_also_resolves_checked_schema_drift_entries(tmp_path, monkeypatch):
    """--apply is one command for 'process what I just checked boxes on' —
    schema-drift.md approvals ride the same invocation as review-queue.md ones."""
    from pipeline.phase_b_lint import apply_proposals
    import pipeline._pages as _pages

    root = tmp_path / "project"
    wiki = root / "wiki"
    (wiki / "political-events").mkdir(parents=True)
    (wiki / "political-events" / "zoning-1.md").write_text(
        "---\ntype: political-event\nproposed-type: zoning-application\ntitle: Zoning 1\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (root / "meta").mkdir()
    (root / "meta" / "schema-drift.md").write_text(
        '## 2026-07-03 | Proposed type: "zoning-application" | Written as: "political-event" | Page: "political-events/zoning-1"\n'
        "Title: Zoning 1\n"
        "Resolution: [x] Approve new type  [ ] Keep as fallback + tag [<tag>]\n",
        encoding="utf-8",
    )
    types_path = tmp_path / "valid_page_types.json"
    types_path.write_text(json.dumps({"page_types": ["political-event"]}), encoding="utf-8")
    monkeypatch.setattr(_pages, "_VALID_PAGE_TYPES_PATH", types_path)
    monkeypatch.setattr(_pages, "VALID_PAGE_TYPES", frozenset({"political-event"}))

    apply_proposals(
        wiki_root=str(wiki),
        aliases_path=str(tmp_path / "aliases.json"),
        merge_log_path=str(tmp_path / "merge-log.jsonl"),
    )

    saved = json.loads(types_path.read_text(encoding="utf-8"))
    assert "zoning-application" in saved["page_types"]
    page_content = (wiki / "political-events" / "zoning-1.md").read_text(encoding="utf-8")
    assert "proposed-type:" not in page_content
    drift_content = (root / "meta" / "schema-drift.md").read_text(encoding="utf-8")
    assert "**Resolved" in drift_content


def test_structural_flags_non_topic_page_citing_a_topic(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    (wiki / "topics").mkdir()
    (wiki / "topics" / "some-topic.md").write_text(
        "---\ntype: topic\ntitle: Some Topic\n---\nNarrative.\n", encoding="utf-8"
    )
    (wiki / "actors" / "osi.md").write_text(
        "---\ntype: actor\ntitle: OSI\n---\n"
        "The OSI leads A2Zero. ([[sources/cap/cap-2020|cap-2020]]) "
        "See also [[topics/some-topic|Some Topic]].\n"
    )
    findings = structural_lint(str(wiki))
    violations = [f for f in findings if f["type"] == "TOPIC_CITATION_VIOLATION"]
    assert any("actors/osi" in f["page"] for f in violations)


def test_structural_allows_topic_citing_topic(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    (wiki / "topics").mkdir()
    (wiki / "topics" / "topic-a.md").write_text(
        "---\ntype: topic\ntitle: Topic A\n---\nSee [[topics/topic-b|Topic B]].\n", encoding="utf-8"
    )
    (wiki / "topics" / "topic-b.md").write_text(
        "---\ntype: topic\ntitle: Topic B\n---\nNarrative.\n", encoding="utf-8"
    )
    findings = structural_lint(str(wiki))
    violations = [f for f in findings if f["type"] == "TOPIC_CITATION_VIOLATION"]
    assert violations == []


def test_structural_flags_digest_citing_a_topic(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    (wiki / "topics").mkdir()
    (wiki / "topics" / "some-topic.md").write_text(
        "---\ntype: topic\ntitle: Some Topic\n---\nNarrative.\n", encoding="utf-8"
    )
    (wiki / "digest.md").write_text(
        "# Wiki Digest\nSee [[topics/some-topic|Some Topic]].\n", encoding="utf-8"
    )
    findings = structural_lint(str(wiki))
    violations = [f for f in findings if f["type"] == "TOPIC_CITATION_VIOLATION"]
    assert any(f["page"] == "digest.md" for f in violations)


def test_structural_surfaces_pending_schema_drift(tmp_path):
    """A schema-drift suggestion must never populate silently — it should show
    up in the same --structural pass the human already checks."""
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "schema-drift.md").write_text(
        '## 2026-07-03 | Proposed type: "zoning-application" | Written as: "political-event" | Page: "political-events/zoning-1"\n'
        "Title: Zoning App\n"
        "Resolution: [ ] Approve new type  [ ] Keep as fallback + tag [<tag>]\n",
        encoding="utf-8",
    )
    findings = structural_lint(str(wiki))
    drift = [f for f in findings if f["type"] == "SCHEMA_DRIFT_PENDING"]
    assert len(drift) == 1
    assert "zoning-application" in drift[0]["detail"]


def test_structural_excludes_resolved_schema_drift(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "schema-drift.md").write_text(
        '## 2026-07-03 | Proposed type: "zoning-application" | Written as: "political-event" | Page: "political-events/zoning-1"\n'
        "Title: Zoning App\n"
        "Resolution: [x] Approve new type  [ ] Keep as fallback + tag [<tag>]\n"
        '\n**Resolved 2026-07-04: approved — "zoning-application" added to VALID_PAGE_TYPES**\n',
        encoding="utf-8",
    )
    findings = structural_lint(str(wiki))
    assert not [f for f in findings if f["type"] == "SCHEMA_DRIFT_PENDING"]


def test_structural_surfaces_pending_query_log_entries(tmp_path):
    """A topic-candidate/human question in query-log.md must never sit silently
    either — same alerting requirement as schema drift."""
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "query-log.md").write_text(
        "## How was solar funded? | 2026-07-03\n"
        "Funded via [[actors/osi|OSI]].\n"
        "Resolution: [ ] Promote to wiki/topics/<slug>.md  [ ] Dismiss\n",
        encoding="utf-8",
    )
    findings = structural_lint(str(wiki))
    pending = [f for f in findings if f["type"] == "QUERY_LOG_PENDING"]
    assert len(pending) == 1
    assert "How was solar funded?" in pending[0]["detail"]


def test_structural_excludes_resolved_query_log_entries(tmp_path):
    from pipeline.phase_b_lint import structural_lint
    wiki = _make_wiki(tmp_path)
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "query-log.md").write_text(
        "## How was solar funded? | 2026-07-03\n"
        "Funded via [[actors/osi|OSI]].\n"
        "Resolution: [x] Promote to wiki/topics/<slug>.md  [ ] Dismiss\n",
        encoding="utf-8",
    )
    findings = structural_lint(str(wiki))
    assert not [f for f in findings if f["type"] == "QUERY_LOG_PENDING"]


def test_write_structural_findings_replaces_existing_section(tmp_path):
    from pipeline.phase_b_lint import write_structural_findings
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "# Queue\n"
        "\n## Structural Lint — 2026-06-20\n"
        "- [BROKEN_LINK] `actors/foo.md` — [[actors/old]] not found\n\n"
        "\n## Semantic Lint — 2026-06-20\n"
        "### [MERGE_PROPOSED] actors/a.md + actors/b.md\n",
        encoding="utf-8",
    )
    findings = [{"type": "BROKEN_LINK", "page": "actors/bar.md", "detail": "[[actors/new]] not found"}]
    write_structural_findings(str(wiki), findings)
    content = rq.read_text()
    assert "actors/old" not in content
    assert "actors/new" in content
    assert content.count("## Structural Lint") == 1
    assert "## Semantic Lint" in content


def test_write_structural_findings_clears_section_when_no_findings(tmp_path):
    from pipeline.phase_b_lint import write_structural_findings
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "# Queue\n"
        "\n## Structural Lint — 2026-06-20\n"
        "- [BROKEN_LINK] `actors/foo.md` — stale finding\n",
        encoding="utf-8",
    )
    write_structural_findings(str(wiki), [])
    content = rq.read_text()
    assert "## Structural Lint" not in content
    assert "stale finding" not in content


def test_write_semantic_proposals_replaces_unannotated_section(tmp_path):
    from pipeline.phase_b_lint import write_semantic_proposals
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "# Queue\n"
        "\n## Semantic Lint — 2026-06-20\n"
        "### [MERGE_PROPOSED] actors/old-a.md + actors/old-b.md\n"
        "- Confidence: 0.80\n"
        "- Reasoning: Old stale pair.\n"
        "- Action: [ ] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER\n"
        "- Notes: _Add any notes before approving_\n\n",
        encoding="utf-8",
    )
    proposals = [{
        "type": "MERGE_PROPOSED",
        "page_a": "actors/new-a.md",
        "page_b": "actors/new-b.md",
        "confidence": 0.92,
        "reasoning": "Same entity.",
    }]
    write_semantic_proposals(str(wiki), proposals)
    content = rq.read_text()
    assert "actors/old-a.md" not in content
    assert "actors/new-a.md" in content
    assert content.count("## Semantic Lint") == 1


def test_write_semantic_proposals_appends_when_annotations_present(tmp_path):
    from pipeline.phase_b_lint import write_semantic_proposals
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "# Queue\n"
        "\n## Semantic Lint — 2026-06-20\n"
        "### [MERGE_PROPOSED] actors/old-a.md + actors/old-b.md\n"
        "- Action: [x] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER\n"
        "- Notes: _Add any notes before approving_\n\n",
        encoding="utf-8",
    )
    proposals = [{
        "type": "MERGE_PROPOSED",
        "page_a": "actors/new-a.md",
        "page_b": "actors/new-b.md",
        "confidence": 0.90,
        "reasoning": "Same entity.",
    }]
    write_semantic_proposals(str(wiki), proposals)
    content = rq.read_text()
    # Both sections preserved — old annotated one + new proposals
    assert "actors/old-a.md" in content
    assert "actors/new-a.md" in content


def test_cleanup_review_queue_removes_approved_keeps_deferred(tmp_path):
    from pipeline.phase_b_lint import _cleanup_review_queue
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "# Queue\n"
        "\n## Semantic Lint — 2026-06-26\n\n"
        "### [MERGE_PROPOSED] actors/a.md + actors/b.md\n"
        "- Confidence: 0.95\n"
        "- Reasoning: Same entity.\n"
        "- Action: [x] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER\n"
        "- Notes: _Add any notes before approving_\n\n"
        "### [MERGE_PROPOSED] actors/c.md + actors/d.md\n"
        "- Confidence: 0.90\n"
        "- Reasoning: Revisit later.\n"
        "- Action: [ ] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [x] DEFER\n"
        "- Notes: _Add any notes before approving_\n\n"
        "### [MERGE_PROPOSED] actors/e.md + actors/f.md\n"
        "- Confidence: 0.85\n"
        "- Reasoning: Distinct.\n"
        "- Action: [ ] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [x] KEEP_SEPARATE  [ ] DEFER\n"
        "- Notes: _Add any notes before approving_\n\n",
        encoding="utf-8",
    )
    _cleanup_review_queue(str(rq))
    content = rq.read_text()
    assert "actors/a.md" not in content   # APPROVE_MERGE → removed
    assert "actors/c.md" in content       # DEFER → kept
    assert "actors/e.md" not in content   # KEEP_SEPARATE → removed


def test_build_entity_catalogue(tmp_path):
    from pipeline.phase_b_lint import _build_entity_catalogue
    from pathlib import Path
    wiki = tmp_path / "wiki"
    (wiki / "actors").mkdir(parents=True)
    (wiki / "actors" / "osi.md").write_text(
        "---\ntype: actor\ntitle: Office of Sustainability and Innovations\n---\nBody.\n",
        encoding="utf-8",
    )
    catalogue = _build_entity_catalogue(wiki)
    assert "Office of Sustainability and Innovations" in catalogue
    assert catalogue["Office of Sustainability and Innovations"] == "actors/osi"


def test_find_unlinked_candidates_returns_match(tmp_path):
    from pipeline.phase_b_lint import _find_unlinked_candidates
    catalogue = {"Solarize Ann Arbor": "initiatives/solarize-ann-arbor"}
    body = "The Solarize Ann Arbor program installed 1.3 MW of solar in Year One."
    candidates = _find_unlinked_candidates(body, catalogue)
    assert any(c["slug"] == "initiatives/solarize-ann-arbor" for c in candidates)


def test_find_unlinked_candidates_skips_already_linked(tmp_path):
    from pipeline.phase_b_lint import _find_unlinked_candidates
    catalogue = {"Solarize Ann Arbor": "initiatives/solarize-ann-arbor"}
    body = "The [[initiatives/solarize-ann-arbor|Solarize Ann Arbor]] program runs city-wide."
    candidates = _find_unlinked_candidates(body, catalogue)
    assert not any(c["slug"] == "initiatives/solarize-ann-arbor" for c in candidates)


def test_find_unlinked_candidates_skips_short_titles(tmp_path):
    from pipeline.phase_b_lint import _find_unlinked_candidates
    catalogue = {"EV": "technology/ev", "OSI": "actors/osi"}
    body = "The EV program is run by OSI."
    candidates = _find_unlinked_candidates(body, catalogue)
    # Both titles are < 5 chars — should be excluded
    assert not candidates


def test_parse_approved_proposals_finds_link(tmp_path):
    from pipeline.phase_b_lint import _parse_approved_proposals
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "## Backlink Lint — 2026-06-26\n\n"
        "### [LINK_PROPOSED] strategies/strategy-1-renewable-grid.md ← initiatives/solarize-ann-arbor\n"
        '- Display text: "Solarize Ann Arbor"\n'
        "- Context: …the Solarize Ann Arbor program…\n"
        "- Action: [x] APPROVE_LINK  [ ] KEEP_UNLINKED  [ ] DEFER\n",
        encoding="utf-8",
    )
    proposals = _parse_approved_proposals(str(rq))
    assert len(proposals) == 1
    p = proposals[0]
    assert p["approved_action"] == "LINK"
    assert p["page"] == "strategies/strategy-1-renewable-grid.md"
    assert p["slug"] == "initiatives/solarize-ann-arbor"
    assert p["display_text"] == "Solarize Ann Arbor"


def test_cleanup_removes_approved_link(tmp_path):
    from pipeline.phase_b_lint import _cleanup_review_queue
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "## Backlink Lint — 2026-06-26\n\n"
        "### [LINK_PROPOSED] strategies/strategy-1.md ← initiatives/solarize\n"
        '- Display text: "Solarize"\n'
        "- Action: [x] APPROVE_LINK  [ ] KEEP_UNLINKED  [ ] DEFER\n\n"
        "### [LINK_PROPOSED] strategies/strategy-2.md ← actors/osi\n"
        '- Display text: "OSI"\n'
        "- Action: [ ] APPROVE_LINK  [x] KEEP_UNLINKED  [ ] DEFER\n\n",
        encoding="utf-8",
    )
    _cleanup_review_queue(str(rq))
    content = rq.read_text()
    assert "strategy-1.md" not in content   # APPROVE_LINK → removed
    assert "strategy-2.md" not in content   # KEEP_UNLINKED → removed


def test_cleanup_review_queue_keeps_unannotated_blocks(tmp_path):
    from pipeline.phase_b_lint import _cleanup_review_queue
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "\n## Semantic Lint — 2026-06-26\n\n"
        "### [MERGE_PROPOSED] actors/x.md + actors/y.md\n"
        "- Confidence: 0.88\n"
        "- Reasoning: Possible duplicate.\n"
        "- Action: [ ] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER\n"
        "- Notes: _Add any notes before approving_\n\n",
        encoding="utf-8",
    )
    _cleanup_review_queue(str(rq))
    content = rq.read_text()
    assert "actors/x.md" in content  # unannotated → still pending, kept


def test_rewrite_inbound_links(tmp_path):
    from pipeline.phase_b_lint import _rewrite_inbound_links
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "actors").mkdir()
    (wiki / "actors" / "page.md").write_text(
        "See [[actors/old-slug]] and [[actors/old-slug|Old Name]].\n",
        encoding="utf-8",
    )
    n = _rewrite_inbound_links(str(wiki), "actors/old-slug.md", "actors/new-slug.md")
    assert n == 2
    content = (wiki / "actors" / "page.md").read_text()
    assert "actors/new-slug" in content
    assert "actors/old-slug" not in content
