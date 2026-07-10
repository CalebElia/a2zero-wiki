# tests/test_lint_wiki.py
import json
import pytest
from pathlib import Path
from unittest.mock import patch


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


def test_semantic_lint_flags_identical_titles_without_calling_llm(tmp_path):
    """Regression: two pages sharing an exact title within the same type
    directory must be flagged directly. Before this fix, title_map was
    title -> single Path, so a second page with an identical title silently
    overwrote the first and was never compared to anything — the exact bug
    that let three duplicate political-event pages for the same SEU vote go
    undetected (see docs/action-plan-2026-07-09.md Item 2.4)."""
    from unittest.mock import patch

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    events = wiki / "political-events"
    events.mkdir()

    same_title = "Ann Arbor voter authorization of the Sustainable Energy Utility"
    (events / "2024-11-01-vote.md").write_text(
        f"---\ntype: political-event\ntitle: {same_title}\ndate: '2024-11-01'\n---\nEarly report.\n"
    )
    (events / "2024-11-05-vote.md").write_text(
        f"---\ntype: political-event\ntitle: {same_title}\ndate: '2024-11-05'\n---\nCorrected date.\n"
    )

    with patch("pipeline.phase_b_lint.chat") as mock_chat:
        from pipeline.phase_b_lint import semantic_lint
        proposals = semantic_lint(str(wiki))

    assert len(proposals) == 1
    assert proposals[0]["type"] == "MERGE_PROPOSED"
    assert proposals[0]["confidence"] == 1.0
    mock_chat.assert_not_called()


def test_semantic_lint_flags_structurally_similar_political_events(tmp_path):
    """An anticipated-announcement page and a reported-outcome page for the
    same vote often have very different titles ('November 2024 SEU Ballot
    Question' vs 'Ann Arbor voter authorization...') so fuzzy title matching
    alone misses them. Same event-type + overlapping programs-authorized +
    dates within 60 days should still reach the LLM verdict."""
    import json
    from unittest.mock import patch

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    events = wiki / "political-events"
    events.mkdir()

    (events / "november-2024-seu-ballot-question.md").write_text(
        "---\ntype: political-event\ntitle: November 2024 SEU Ballot Question\n"
        "date: '2024-11-01'\nevent-type: referendum\noutcome: pending\n"
        "programs-authorized: ['[[initiatives/sustainable-energy-utility]]']\n---\n"
        "Voters will decide in November.\n"
    )
    (events / "2024-11-05-seu-vote.md").write_text(
        "---\ntype: political-event\ntitle: Ann Arbor voter authorization of the Sustainable Energy Utility\n"
        "date: '2024-11-05'\nevent-type: referendum\noutcome: approved\n"
        "programs-authorized: ['[[initiatives/sustainable-energy-utility]]']\n---\n"
        "Voters authorized the SEU with 79% of the vote.\n"
    )

    verdict = {"relationship": "same", "confidence": 0.95, "reasoning": "Same vote, announced then resolved."}
    with patch("pipeline.phase_b_lint.chat") as mock_chat:
        mock_chat.return_value = json.dumps(verdict)
        from pipeline.phase_b_lint import semantic_lint
        proposals = semantic_lint(str(wiki))

    assert len(proposals) == 1
    assert proposals[0]["type"] == "MERGE_PROPOSED"
    mock_chat.assert_called_once()


def test_political_event_structural_pairs_requires_overlap_and_date_window(tmp_path):
    from pipeline.phase_b_lint import _political_event_structural_pairs

    events = tmp_path / "political-events"
    events.mkdir()

    a = events / "a.md"
    a.write_text(
        "---\ndate: '2024-11-05'\nevent-type: referendum\n"
        "programs-authorized: ['[[initiatives/sustainable-energy-utility]]']\n---\nbody\n"
    )
    # Same event-type + overlapping program, within 60 days -> pairs with a
    b = events / "b.md"
    b.write_text(
        "---\ndate: '2024-11-01'\nevent-type: referendum\n"
        "programs-authorized: ['[[initiatives/sustainable-energy-utility]]']\n---\nbody\n"
    )
    # Different program -> no pair
    c = events / "c.md"
    c.write_text(
        "---\ndate: '2024-11-02'\nevent-type: referendum\n"
        "programs-authorized: ['[[initiatives/some-other-initiative]]']\n---\nbody\n"
    )
    # Same program, but >60 days away -> no pair
    d = events / "d.md"
    d.write_text(
        "---\ndate: '2025-06-01'\nevent-type: referendum\n"
        "programs-authorized: ['[[initiatives/sustainable-energy-utility]]']\n---\nbody\n"
    )

    pairs = _political_event_structural_pairs([a, b, c, d])
    assert pairs == [(a, b)]


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


def test_find_unlinked_candidates_ignores_frontmatter_text(tmp_path):
    """Regression: backlink_lint only ever passes the stripped markdown body to
    the candidate scanner — a mention that only occurs in YAML frontmatter
    (e.g. an auto-generated synthesis narrative) must never surface as a
    LINK_PROPOSED candidate, since frontmatter is never rendered/linkable."""
    from pipeline.phase_b_lint import backlink_lint

    wiki = tmp_path / "wiki"
    (wiki / "strategies").mkdir(parents=True)
    (wiki / "initiatives").mkdir()
    (wiki / "initiatives" / "carbon-offsets.md").write_text(
        "---\ntype: initiative\ntitle: Carbon Offsets\n---\nBody.\n", encoding="utf-8"
    )
    (wiki / "strategies" / "strategy-7.md").write_text(
        "---\n"
        "type: strategy\n"
        "synthesis:\n"
        '  year-over-year-arc: "Year 4 introduced Carbon Offsets as a bridging mechanism."\n'
        "---\n\n"
        "This page never mentions the phrase in its body prose.\n",
        encoding="utf-8",
    )

    proposals = backlink_lint(str(wiki), scope=["strategies"])
    assert not [p for p in proposals if p["entity_slug"] == "initiatives/carbon-offsets"]


def test_apply_proposals_link_only_touches_body_not_frontmatter(tmp_path):
    """Regression: a LINK proposal's display_text ('offsets') also appears,
    unlinked, inside an auto-generated YAML frontmatter field
    (synthesis.year-over-year-arc). --apply's naive first-match-in-file
    replace previously landed the wikilink inside the frontmatter string
    instead of the body prose the proposal's context actually quoted,
    corrupting the frontmatter and leaving the real body mention unlinked
    (which then kept getting re-proposed on every subsequent scan)."""
    from pipeline.phase_b_lint import apply_proposals

    root = tmp_path / "project"
    wiki = root / "wiki"
    (wiki / "strategies").mkdir(parents=True)
    (wiki / "strategies" / "strategy-7.md").write_text(
        "---\n"
        "type: strategy\n"
        "synthesis:\n"
        '  year-over-year-arc: "Year 4 introduced offsets as a bridging mechanism."\n'
        "---\n\n"
        "The strategy notes greenhouse gas emissions offsets to close remaining gaps.\n",
        encoding="utf-8",
    )
    (root / "review-queue.md").write_text(
        "## Backlink Lint — 2026-07-07\n\n"
        "### [LINK_PROPOSED] strategies/strategy-7.md ← initiatives/carbon-offsets\n"
        '- Display text: "offsets"\n'
        "- Context: …The strategy notes greenhouse gas emissions offsets to close "
        "remaining gaps.…\n"
        "- Action: [x] APPROVE_LINK  [ ] KEEP_UNLINKED  [ ] DEFER\n",
        encoding="utf-8",
    )

    apply_proposals(
        wiki_root=str(wiki),
        aliases_path=str(tmp_path / "aliases.json"),
        merge_log_path=str(tmp_path / "merge-log.jsonl"),
    )

    content = (wiki / "strategies" / "strategy-7.md").read_text(encoding="utf-8")
    assert 'year-over-year-arc: "Year 4 introduced offsets as a bridging mechanism."' in content
    assert "[[initiatives/carbon-offsets|offsets]] to close remaining gaps" in content
    assert content.count("[[initiatives/carbon-offsets") == 1


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


def _staleness_fixture(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "entity_aliases.json").write_text("{}", encoding="utf-8")
    (tmp_path / "meta").mkdir()
    # stale page: named in source, no year9 citation
    (wiki / "initiatives" / "old-program.md").write_text(
        "---\ntype: initiative\ntitle: Old Program\n---\n\n"
        "Body cites ([[sources/annual-reports/a2zero-year1|a2zero-year1]]).\n",
        encoding="utf-8",
    )
    # fresh page: named in source AND cites it
    (wiki / "initiatives" / "fresh-program.md").write_text(
        "---\ntype: initiative\ntitle: Fresh Program\n---\n\n"
        "Updated ([[sources/annual-reports/a2zero-year9|a2zero-year9]]).\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "annual-reports" / "a2zero-year9.md").write_text(
        "---\nuuid: a2zero-year9\n---\n\n"
        "The Old Program expanded. Fresh Program also grew.\n",
        encoding="utf-8",
    )
    return wiki


def test_staleness_lint_flags_mentioned_but_uncited_entities(tmp_path):
    from pipeline.phase_b_lint import staleness_lint
    wiki = _staleness_fixture(tmp_path)
    findings = staleness_lint(str(wiki), source_uuid="a2zero-year9")
    assert len(findings) == 1
    f = findings[0]
    assert f["type"] == "STALE_ENTITY"
    assert f["page"] == "initiatives/old-program.md"
    assert "a2zero-year9" in f["detail"]


def test_staleness_lint_defaults_to_last_ingest_stats_entry(tmp_path):
    import json as _json
    from pipeline.phase_b_lint import staleness_lint
    wiki = _staleness_fixture(tmp_path)
    stats = tmp_path / "meta" / "ingest-stats.jsonl"
    stats.write_text(
        _json.dumps({"source-uuid": "a2zero-year9", "run-date": "2026-07-06"}) + "\n",
        encoding="utf-8",
    )
    findings = staleness_lint(str(wiki))  # no source_uuid → read stats
    assert [f["page"] for f in findings] == ["initiatives/old-program.md"]


def test_staleness_lint_annotates_context_dropped_entities(tmp_path):
    import json as _json
    from pipeline.phase_b_lint import staleness_lint
    wiki = _staleness_fixture(tmp_path)
    plans_dir = tmp_path / "integration-plans"
    plans_dir.mkdir()
    (plans_dir / "a2zero-year9.json").write_text(
        _json.dumps({"context-dropped": ["initiatives/old-program"]}),
        encoding="utf-8",
    )
    findings = staleness_lint(str(wiki), source_uuid="a2zero-year9")
    assert len(findings) == 1
    assert "context-dropped at ingest" in findings[0]["detail"]


def test_staleness_lint_annotates_ambiguous_entities(tmp_path):
    """A STALE_ENTITY finding for a slug the recall scanner could only
    resolve via the _ambiguous_terms multi-candidate path (not a confident
    single-slug match) must say so — human triage needs to know this isn't
    a confident miss, it's an unresolved "could be either" hit."""
    from pipeline.phase_b_lint import staleness_lint
    wiki = tmp_path / "wiki"
    (wiki / "locations").mkdir(parents=True)
    (wiki / "actors").mkdir()
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "entity_aliases.json").write_text(
        json.dumps({
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
        }),
        encoding="utf-8",
    )
    (tmp_path / "meta").mkdir()
    (wiki / "locations" / "ann-arbor.md").write_text(
        "---\ntype: location\ntitle: Ann Arbor\n---\n\nBody.\n", encoding="utf-8",
    )
    (wiki / "actors" / "city-of-ann-arbor.md").write_text(
        "---\ntype: actor\ntitle: City of Ann Arbor\n---\n\nBody.\n", encoding="utf-8",
    )
    (wiki / "sources" / "annual-reports" / "a2zero-year9.md").write_text(
        "---\nuuid: a2zero-year9\n---\n\nElectricity use in Ann Arbor rose this year.\n",
        encoding="utf-8",
    )
    findings = staleness_lint(str(wiki), source_uuid="a2zero-year9")
    by_page = {f["page"]: f for f in findings}
    assert "ambiguous — verify against source" in by_page["locations/ann-arbor.md"]["detail"]
    assert "actors/city-of-ann-arbor" in by_page["locations/ann-arbor.md"]["detail"]
    assert "ambiguous — verify against source" in by_page["actors/city-of-ann-arbor.md"]["detail"]


# ── Contradiction sweep (Item 3 / docs/contradiction-tracking-assessment-2026-07-10.md) ──

def _make_contradiction_sweep_wiki(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "sources" / "cap").mkdir(parents=True)
    (wiki / "sources" / "annual-reports").mkdir(parents=True)

    (wiki / "sources" / "cap" / "cap-2020.md").write_text(
        "---\nuuid: cap-2020\n---\n\n"
        "By the end of 2023, a 24MW solar installation is fully operational at the "
        "former Ann Arbor landfill.\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "annual-reports" / "a2zero-year2.md").write_text(
        "---\nuuid: a2zero-year2\n---\n\n"
        "Final design for a 20MW solar field on our capped landfill was completed.\n",
        encoding="utf-8",
    )
    (wiki / "initiatives" / "wheeler-center-solar-park.md").write_text(
        "---\ntype: initiative\ntitle: Wheeler Center Solar Park\ntags: [solar, landfill]\n"
        "---\n\n"
        "The Wheeler Center Solar Park is a planned 20MW solar installation "
        "([[sources/annual-reports/a2zero-year2|a2zero-year2]]) targeting 20MW capacity "
        "and $5,000,000 in funding ([[sources/cap/cap-2020|cap-2020]]).\n",
        encoding="utf-8",
    )
    return wiki


def test_numeric_density_candidates_finds_multi_source_numeric_page(tmp_path):
    from pipeline.phase_b_lint import _numeric_density_candidates
    wiki = _make_contradiction_sweep_wiki(tmp_path)
    candidates = _numeric_density_candidates(str(wiki), min_claims=2, min_sources=2)
    slugs = [c["slug"] for c in candidates]
    assert "initiatives/wheeler-center-solar-park" in slugs


def test_numeric_density_candidates_excludes_pages_below_threshold(tmp_path):
    from pipeline.phase_b_lint import _numeric_density_candidates
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "initiatives" / "quiet-initiative.md").write_text(
        "---\ntype: initiative\ntitle: Quiet Initiative\n---\n\n"
        "This initiative has no numeric claims at all, just prose.\n",
        encoding="utf-8",
    )
    candidates = _numeric_density_candidates(str(wiki))
    assert candidates == []


def test_gather_source_excerpts_greps_relevant_numeric_lines(tmp_path):
    from pipeline.phase_b_lint import _gather_source_excerpts
    wiki = _make_contradiction_sweep_wiki(tmp_path)
    excerpts = _gather_source_excerpts(
        str(wiki), "Wheeler Center Solar Park",
        ["sources/cap/cap-2020", "sources/annual-reports/a2zero-year2"],
    )
    assert "24MW" in excerpts["sources/cap/cap-2020"]
    assert "20MW" in excerpts["sources/annual-reports/a2zero-year2"]


def test_open_question_boost_slugs_matches_scale_language(tmp_path):
    from pipeline.phase_b_lint import _open_question_boost_slugs
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "digest.md").write_text(
        "## Strategy entity map\n\n"
        "### [[strategies/strategy-1-renewable-grid|Strategy 1]]\n"
        "- **core initiatives:** [[initiatives/wheeler-center-solar-park|Wheeler Center Solar Park]], [[initiatives/other-thing|Other Thing]]\n"
        "- **open:** Whether the landfill solar concept advances to full development and at what scale\n",
        encoding="utf-8",
    )
    boosted = _open_question_boost_slugs(str(wiki))
    assert "initiatives/wheeler-center-solar-park" in boosted
    assert "initiatives/other-thing" in boosted


def test_open_question_boost_slugs_ignores_purely_qualitative_open_questions(tmp_path):
    from pipeline.phase_b_lint import _open_question_boost_slugs
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "digest.md").write_text(
        "### [[strategies/strategy-2-electrification|Strategy 2]]\n"
        "- **core initiatives:** [[initiatives/some-program|Some Program]]\n"
        "- **open:** Whether financing tools were ultimately deployed\n",
        encoding="utf-8",
    )
    boosted = _open_question_boost_slugs(str(wiki))
    assert boosted == set()


def test_build_contradiction_page_assembles_expected_frontmatter_and_body():
    from pipeline.phase_b_lint import _build_contradiction_page
    candidate = {"slug": "initiatives/wheeler-center-solar-park", "tags": ["solar", "landfill"]}
    verdict = {
        "title": "Wheeler Center Solar Park capacity: 24MW vs 20MW",
        "cross_source": True,
        "claims": [
            {"source": "sources/cap/cap-2020", "quote": "24MW solar installation fully operational"},
            {"source": "sources/annual-reports/a2zero-year2", "quote": "Final design for a 20MW solar field"},
        ],
        "why_it_matters": "Affects assessed progress toward the 78MW target.",
        "best_guess_explanation": "The 20MW figure is likely the right-sized final design.",
    }
    slug, content = _build_contradiction_page(candidate, verdict, "2026-07-10")
    assert slug == "contradictions/wheeler-center-solar-park-capacity-24mw-vs-20mw"
    assert "type: contradiction" in content
    assert "cross-source: true" in content
    assert "'[[initiatives/wheeler-center-solar-park]]'" in content
    assert "24MW solar installation" in content
    assert "20MW solar field" in content
    assert "## Why it matters" in content
    assert "## Best-guess explanation" in content


@patch("pipeline.phase_b_lint.chat")
def test_contradiction_sweep_produces_proposal_for_real_conflict(mock_chat, tmp_path):
    import json as _json
    wiki = _make_contradiction_sweep_wiki(tmp_path)
    mock_chat.return_value = _json.dumps({
        "contradiction_found": True,
        "confidence": 0.9,
        "title": "Wheeler Center capacity 24MW vs 20MW",
        "cross_source": True,
        "claims": [
            {"source": "sources/cap/cap-2020", "quote": "24MW"},
            {"source": "sources/annual-reports/a2zero-year2", "quote": "20MW"},
        ],
        "why_it_matters": "Matters for tracking the 78MW goal.",
        "best_guess_explanation": "Unknown",
    })
    from pipeline.phase_b_lint import contradiction_sweep
    proposals = contradiction_sweep(str(wiki), max_candidates=5)
    assert len(proposals) == 1
    assert proposals[0]["related_initiative"] == "initiatives/wheeler-center-solar-park"
    assert "type: contradiction" in proposals[0]["content"]


@patch("pipeline.phase_b_lint.chat")
def test_contradiction_sweep_skips_when_llm_finds_no_conflict(mock_chat, tmp_path):
    import json as _json
    wiki = _make_contradiction_sweep_wiki(tmp_path)
    mock_chat.return_value = _json.dumps({"contradiction_found": False, "confidence": 0.1})
    from pipeline.phase_b_lint import contradiction_sweep
    proposals = contradiction_sweep(str(wiki), max_candidates=5)
    assert proposals == []


@patch("pipeline.phase_b_lint.chat")
def test_contradiction_sweep_skips_low_confidence(mock_chat, tmp_path):
    import json as _json
    wiki = _make_contradiction_sweep_wiki(tmp_path)
    mock_chat.return_value = _json.dumps({
        "contradiction_found": True,
        "confidence": 0.3,
        "title": "x", "cross_source": True,
        "claims": [{"source": "sources/cap/cap-2020", "quote": "a"},
                   {"source": "sources/annual-reports/a2zero-year2", "quote": "b"}],
        "why_it_matters": "x", "best_guess_explanation": "x",
    })
    from pipeline.phase_b_lint import contradiction_sweep
    proposals = contradiction_sweep(str(wiki), max_candidates=5, confidence_threshold=0.6)
    assert proposals == []


@patch("pipeline.phase_b_lint.chat")
def test_contradiction_sweep_skips_already_backfilled_slug(mock_chat, tmp_path):
    import json as _json
    wiki = _make_contradiction_sweep_wiki(tmp_path)
    (wiki / "contradictions").mkdir(parents=True)
    (wiki / "contradictions" / "wheeler-capacity-conflict.md").write_text(
        "---\ntype: contradiction\ntitle: already here\n---\n\nAlready backfilled.\n",
        encoding="utf-8",
    )
    mock_chat.return_value = _json.dumps({
        "contradiction_found": True,
        "confidence": 0.9,
        "title": "Wheeler capacity conflict",
        "cross_source": True,
        "claims": [{"source": "sources/cap/cap-2020", "quote": "24MW"},
                   {"source": "sources/annual-reports/a2zero-year2", "quote": "20MW"}],
        "why_it_matters": "x", "best_guess_explanation": "x",
    })
    from pipeline.phase_b_lint import contradiction_sweep
    proposals = contradiction_sweep(str(wiki), max_candidates=5)
    assert proposals == []


def test_write_contradiction_proposals_writes_fenced_content(tmp_path):
    from pipeline.phase_b_lint import write_contradiction_proposals
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    proposals = [{
        "slug": "contradictions/example-conflict",
        "content": "---\ntype: contradiction\ntitle: Example\n---\n\n## Conflicting claims\n\nBody.\n",
        "confidence": 0.85,
        "reasoning": "Two figures disagree.",
        "related_initiative": "initiatives/example",
    }]
    write_contradiction_proposals(str(wiki), proposals)
    rq = (tmp_path / "review-queue.md").read_text(encoding="utf-8")
    assert "### [CONTRADICTION_PROPOSED] contradictions/example-conflict" in rq
    assert "- Action: [ ] APPROVE_CREATE  [ ] DISMISS  [ ] DEFER" in rq
    assert "```markdown" in rq
    assert "## Conflicting claims" in rq


def test_parse_approved_proposals_extracts_fenced_contradiction_content(tmp_path):
    from pipeline.phase_b_lint import _parse_approved_proposals
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "## Contradiction Sweep — 2026-07-10\n\n"
        "### [CONTRADICTION_PROPOSED] contradictions/example-conflict\n"
        "- Related initiative: [[initiatives/example]]\n"
        "- Confidence: 0.85\n"
        "- Reasoning: Two figures disagree.\n"
        "- Action: [x] APPROVE_CREATE  [ ] DISMISS  [ ] DEFER\n"
        "- Notes: looks right\n\n"
        "```markdown\n"
        "---\n"
        "type: contradiction\n"
        "title: Example\n"
        "---\n\n"
        "## Conflicting claims\n\n"
        "Body text.\n"
        "```\n",
        encoding="utf-8",
    )
    proposals = _parse_approved_proposals(str(rq))
    assert len(proposals) == 1
    p = proposals[0]
    assert p["approved_action"] == "CREATE_CONTRADICTION"
    assert p["slug"] == "contradictions/example-conflict"
    assert "## Conflicting claims" in p["content"]
    assert "type: contradiction" in p["content"]


def test_parse_approved_proposals_ignores_unapproved_contradiction(tmp_path):
    from pipeline.phase_b_lint import _parse_approved_proposals
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "### [CONTRADICTION_PROPOSED] contradictions/example-conflict\n"
        "- Action: [ ] APPROVE_CREATE  [ ] DISMISS  [ ] DEFER\n\n"
        "```markdown\n---\ntype: contradiction\n---\n\nBody.\n```\n",
        encoding="utf-8",
    )
    assert _parse_approved_proposals(str(rq)) == []


def test_apply_proposals_creates_contradiction_page_from_approved_content(tmp_path):
    from pipeline.phase_b_lint import apply_proposals
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "entity_aliases.json").write_text("{}", encoding="utf-8")
    (tmp_path / "registry" / "merge-log.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "review-queue.md").write_text(
        "### [CONTRADICTION_PROPOSED] contradictions/example-conflict\n"
        "- Action: [x] APPROVE_CREATE  [ ] DISMISS  [ ] DEFER\n\n"
        "```markdown\n"
        "---\ntype: contradiction\ntitle: Example\n---\n\n"
        "## Conflicting claims\n\nBody text.\n"
        "```\n",
        encoding="utf-8",
    )
    apply_proposals(
        str(wiki),
        str(tmp_path / "registry" / "entity_aliases.json"),
        str(tmp_path / "registry" / "merge-log.jsonl"),
    )
    out = wiki / "contradictions" / "example-conflict.md"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "type: contradiction" in content
    assert "## Conflicting claims" in content


def test_cleanup_review_queue_ignores_headers_inside_contradiction_fence(tmp_path):
    """Regression: a contradiction proposal's fenced page content contains its
    own '## Conflicting claims' / '## Why it matters' headers — the cleanup
    pass must not mistake those for review-queue.md section boundaries and
    truncate the block early."""
    from pipeline.phase_b_lint import _parse_approved_proposals, _cleanup_review_queue
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "## Contradiction Sweep — 2026-07-10\n\n"
        "### [CONTRADICTION_PROPOSED] contradictions/example-conflict\n"
        "- Action: [x] APPROVE_CREATE  [ ] DISMISS  [ ] DEFER\n\n"
        "```markdown\n"
        "---\ntype: contradiction\ntitle: Example\n---\n\n"
        "## Conflicting claims\n\nFirst claim.\n\n"
        "## Why it matters\n\nIt matters.\n"
        "```\n\n"
        "## Semantic Lint — 2026-07-10\n\n"
        "### [MERGE_PROPOSED] initiatives/a.md + initiatives/b.md\n"
        "- Action: [ ] APPROVE_MERGE  [ ] KEEP_SEPARATE  [ ] DEFER\n",
        encoding="utf-8",
    )
    _cleanup_review_queue(str(rq))
    remaining = rq.read_text(encoding="utf-8")
    # The approved contradiction block is dropped (resolved)...
    assert "CONTRADICTION_PROPOSED" not in remaining
    # ...but the unrelated, still-pending MERGE block below it survives intact.
    assert "[MERGE_PROPOSED] initiatives/a.md + initiatives/b.md" in remaining


@patch("pipeline.phase_b_lint.chat")
def test_contradiction_sweep_dedupes_against_existing_page_by_source_overlap(mock_chat, tmp_path):
    """Regression: the same real-world conflict gets independently
    rediscovered once per initiative page that cites the same two sources,
    and the LLM titles/slugs it differently each time — an exact-slug check
    alone doesn't catch this. A live sweep against the real wiki produced 5
    near-duplicate Wheeler Center MW proposals before this fix (2026-07-10)."""
    import json as _json
    wiki = _make_contradiction_sweep_wiki(tmp_path)
    # A second initiative page that independently cites the same two sources.
    (wiki / "initiatives" / "landfill-solar-project.md").write_text(
        "---\ntype: initiative\ntitle: Landfill Solar Project\ntags: [solar]\n---\n\n"
        "The landfill solar project targets 20MW capacity "
        "([[sources/annual-reports/a2zero-year2|a2zero-year2]]) versus an original "
        "24MW figure ([[sources/cap/cap-2020|cap-2020]]).\n",
        encoding="utf-8",
    )
    # Already backfilled by hand under a completely different slug/title wording.
    (wiki / "contradictions").mkdir(parents=True)
    (wiki / "contradictions" / "wheeler-center-mw-discrepancy.md").write_text(
        "---\ntype: contradiction\ntitle: Existing\n"
        "sources:\n- '[[sources/cap/cap-2020]]'\n- '[[sources/annual-reports/a2zero-year2]]'\n"
        "---\n\nAlready here.\n",
        encoding="utf-8",
    )
    mock_chat.return_value = _json.dumps({
        "contradiction_found": True,
        "confidence": 0.9,
        "title": "A totally differently worded title each time",
        "cross_source": True,
        "claims": [
            {"source": "sources/cap/cap-2020", "quote": "24MW"},
            {"source": "sources/annual-reports/a2zero-year2", "quote": "20MW"},
        ],
        "why_it_matters": "x", "best_guess_explanation": "x",
    })
    from pipeline.phase_b_lint import contradiction_sweep
    proposals = contradiction_sweep(str(wiki), max_candidates=5)
    assert proposals == []


@patch("pipeline.phase_b_lint.chat")
def test_contradiction_sweep_dedupes_within_same_run_across_candidates(mock_chat, tmp_path):
    """Same as above but with no pre-existing contradiction page — two
    candidates discovered IN THE SAME sweep run, citing the same two
    sources, must still only produce one proposal."""
    import json as _json
    wiki = _make_contradiction_sweep_wiki(tmp_path)
    (wiki / "initiatives" / "landfill-solar-project.md").write_text(
        "---\ntype: initiative\ntitle: Landfill Solar Project\ntags: [solar]\n---\n\n"
        "The landfill solar project targets 20MW capacity "
        "([[sources/annual-reports/a2zero-year2|a2zero-year2]]) versus an original "
        "24MW figure ([[sources/cap/cap-2020|cap-2020]]).\n",
        encoding="utf-8",
    )
    mock_chat.return_value = _json.dumps({
        "contradiction_found": True,
        "confidence": 0.9,
        "title": "Different title each call",
        "cross_source": True,
        "claims": [
            {"source": "sources/cap/cap-2020", "quote": "24MW"},
            {"source": "sources/annual-reports/a2zero-year2", "quote": "20MW"},
        ],
        "why_it_matters": "x", "best_guess_explanation": "x",
    })
    from pipeline.phase_b_lint import contradiction_sweep
    proposals = contradiction_sweep(str(wiki), max_candidates=5)
    assert len(proposals) == 1


@patch("pipeline.phase_b_lint.chat")
def test_contradiction_sweep_drops_candidate_with_invented_source(mock_chat, tmp_path):
    """Regression: a live sweep run produced a claim citing the initiative
    page itself as a 'source' (not a real sources/ document) and another with
    a parenthetical LLM annotation baked into what should have been a plain
    slug — either would write a malformed wikilink or a schema-violating
    sources: entry straight into review-queue.md. Every claims[].source must
    be validated against the actual excerpt slugs shown to the model."""
    import json as _json
    wiki = _make_contradiction_sweep_wiki(tmp_path)
    mock_chat.return_value = _json.dumps({
        "contradiction_found": True,
        "confidence": 0.9,
        "title": "x",
        "cross_source": True,
        "claims": [
            {"source": "sources/cap/cap-2020", "quote": "24MW"},
            {"source": "initiatives/wheeler-center-solar-park (page body)", "quote": "20MW"},
        ],
        "why_it_matters": "x", "best_guess_explanation": "x",
    })
    from pipeline.phase_b_lint import contradiction_sweep
    proposals = contradiction_sweep(str(wiki), max_candidates=5)
    assert proposals == []


# ── Rename-phrase scanner + safe redirect + keep-separate memory ──
# (docs/architecture/semantic-lint-structural-candidates.md)

def test_extract_rename_candidates_splits_chained_clause():
    """The spec's own regex captured the whole chained clause as one blob
    ('the Wheeler Center Landfill Solar Project and later the Wheeler Center
    Solar Park') → 0.47 fuzzy, missing its own motivating example. The
    corrected capture yields each name separately."""
    from pipeline.phase_b_lint import _extract_rename_candidates
    body = ("The Landfill Solar Project, also referred to as the Wheeler Center "
            "Landfill Solar Project and later the Wheeler Center Solar Park, was "
            "proposed in CAP 2020 as a utility-scale solar installation.")
    names = [n for n, _ in _extract_rename_candidates(body)]
    assert "Wheeler Center Solar Park" in names
    assert "Wheeler Center Landfill Solar Project" in names


def test_alias_phrase_lint_emits_for_real_rename(tmp_path):
    from pipeline.phase_b_lint import alias_phrase_lint
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "initiatives" / "landfill-solar-project.md").write_text(
        "---\ntype: initiative\ntitle: Landfill Solar Project\n---\n\n"
        "The Landfill Solar Project, later the Wheeler Center Solar Park, was "
        "proposed in CAP 2020.\n",
        encoding="utf-8",
    )
    (wiki / "initiatives" / "wheeler-center-solar-park.md").write_text(
        "---\ntype: initiative\ntitle: Wheeler Center Solar Park\n---\n\n"
        "A 20MW solar installation.\n",
        encoding="utf-8",
    )
    proposals = alias_phrase_lint(str(wiki))
    assert len(proposals) == 1
    p = proposals[0]
    assert p["old"] == "initiatives/landfill-solar-project"
    assert p["canonical"] == "initiatives/wheeler-center-solar-park"
    assert p["score"] >= 0.99


def test_alias_phrase_lint_filters_non_rename_construction(tmp_path):
    """'also referred to as a pilot program' is a description, not a name —
    the title-case anchor rejects it (lowercase 'a')."""
    from pipeline.phase_b_lint import alias_phrase_lint
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "initiatives" / "foo.md").write_text(
        "---\ntype: initiative\ntitle: Foo Program\n---\n\n"
        "The Foo Program, also referred to as a pilot program, launched in 2022.\n",
        encoding="utf-8",
    )
    (wiki / "initiatives" / "bar.md").write_text(
        "---\ntype: initiative\ntitle: Bar Program\n---\n\nUnrelated.\n",
        encoding="utf-8",
    )
    assert alias_phrase_lint(str(wiki)) == []


def test_alias_phrase_lint_no_proposal_when_name_matches_no_page(tmp_path):
    from pipeline.phase_b_lint import alias_phrase_lint
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "initiatives" / "foo.md").write_text(
        "---\ntype: initiative\ntitle: Foo Program\n---\n\n"
        "The Foo Program, later the Nonexistent Phantom Initiative, ended.\n",
        encoding="utf-8",
    )
    (wiki / "initiatives" / "bar.md").write_text(
        "---\ntype: initiative\ntitle: Bar Program\n---\n\nUnrelated.\n",
        encoding="utf-8",
    )
    assert alias_phrase_lint(str(wiki)) == []


def test_alias_phrase_lint_skips_keep_separate_pair(tmp_path):
    from pipeline.phase_b_lint import alias_phrase_lint
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "merge-log.jsonl").write_text(
        json.dumps({"action": "KEEP_SEPARATE",
                    "pages": ["initiatives/landfill-solar-project",
                              "initiatives/wheeler-center-solar-park"]}) + "\n",
        encoding="utf-8",
    )
    (wiki / "initiatives" / "landfill-solar-project.md").write_text(
        "---\ntype: initiative\ntitle: Landfill Solar Project\n---\n\n"
        "The Landfill Solar Project, later the Wheeler Center Solar Park, proposed.\n",
        encoding="utf-8",
    )
    (wiki / "initiatives" / "wheeler-center-solar-park.md").write_text(
        "---\ntype: initiative\ntitle: Wheeler Center Solar Park\n---\n\nA solar installation.\n",
        encoding="utf-8",
    )
    assert alias_phrase_lint(str(wiki)) == []


def test_load_keep_separate_pairs_reads_log(tmp_path):
    from pipeline.phase_b_lint import _load_keep_separate_pairs
    log = tmp_path / "merge-log.jsonl"
    log.write_text(
        json.dumps({"action": "MERGE", "from": "a.md", "into": "b.md"}) + "\n"
        + json.dumps({"action": "KEEP_SEPARATE",
                      "pages": ["initiatives/x.md", "initiatives/y"]}) + "\n",
        encoding="utf-8",
    )
    pairs = _load_keep_separate_pairs(str(log))
    assert frozenset({"initiatives/x", "initiatives/y"}) in pairs
    assert len(pairs) == 1  # the MERGE entry is not a keep-separate record


def test_parse_approved_proposals_recognizes_alias_redirect(tmp_path):
    from pipeline.phase_b_lint import _parse_approved_proposals
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "## Alias/Rename Detection — 2026-07-10\n\n"
        "### [ALIAS_DETECTED] initiatives/landfill-solar-project → initiatives/wheeler-center-solar-park\n"
        "- Evidence: \"...\"\n"
        "- Matched: \"Wheeler Center Solar Park\" (fuzzy 1.00)\n"
        "- Action: [x] APPROVE_REDIRECT  [ ] KEEP_SEPARATE  [ ] DEFER\n",
        encoding="utf-8",
    )
    proposals = _parse_approved_proposals(str(rq))
    assert len(proposals) == 1
    p = proposals[0]
    assert p["approved_action"] == "REDIRECT"
    assert p["old_slug"] == "initiatives/landfill-solar-project"
    assert p["canonical_slug"] == "initiatives/wheeler-center-solar-park"


def test_parse_approved_proposals_recognizes_keep_separate_pair(tmp_path):
    from pipeline.phase_b_lint import _parse_approved_proposals
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "### [MERGE_PROPOSED] initiatives/a.md + initiatives/b.md\n"
        "- Action: [ ] APPROVE_MERGE  [x] KEEP_SEPARATE  [ ] DEFER\n",
        encoding="utf-8",
    )
    proposals = _parse_approved_proposals(str(rq))
    assert len(proposals) == 1
    p = proposals[0]
    assert p["approved_action"] == "KEEP_SEPARATE"
    assert set(p["pages"]) == {"initiatives/a.md", "initiatives/b.md"}


def _redirect_wiki(tmp_path, old_body: str):
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "entity_aliases.json").write_text("{}", encoding="utf-8")
    (tmp_path / "registry" / "merge-log.jsonl").write_text("", encoding="utf-8")
    (wiki / "initiatives" / "landfill-solar-project.md").write_text(
        "---\ntype: initiative\ntitle: Landfill Solar Project\n---\n\n" + old_body,
        encoding="utf-8",
    )
    (wiki / "initiatives" / "wheeler-center-solar-park.md").write_text(
        "---\ntype: initiative\ntitle: Wheeler Center Solar Park\n---\n\n"
        "The Wheeler Center Solar Park is a 20MW solar installation on the capped landfill.\n",
        encoding="utf-8",
    )
    # A page that links to the old slug, to verify inbound-link rewrite.
    (wiki / "initiatives" / "linker.md").write_text(
        "---\ntype: initiative\ntitle: Linker\n---\n\nSee [[initiatives/landfill-solar-project]].\n",
        encoding="utf-8",
    )
    (tmp_path / "review-queue.md").write_text(
        "### [ALIAS_DETECTED] initiatives/landfill-solar-project → initiatives/wheeler-center-solar-park\n"
        "- Action: [x] APPROVE_REDIRECT  [ ] KEEP_SEPARATE  [ ] DEFER\n",
        encoding="utf-8",
    )
    return wiki


def test_apply_redirect_safe_stub_no_llm_call(tmp_path):
    """Old page is a thin stub (no substantive sentences not in canonical) →
    safe REDIRECT: delete + rewrite links + alias, and NEVER an LLM merge."""
    from unittest.mock import patch, MagicMock
    from pipeline.phase_b_lint import apply_proposals
    wiki = _redirect_wiki(tmp_path, "The Landfill Solar Project. See the newer page.\n")

    with patch("pipeline.pass2c_merge.merge_pages", MagicMock()) as mock_merge:
        apply_proposals(str(wiki),
                        str(tmp_path / "registry" / "entity_aliases.json"),
                        str(tmp_path / "registry" / "merge-log.jsonl"))
    mock_merge.assert_not_called()
    assert not (wiki / "initiatives" / "landfill-solar-project.md").exists()
    # inbound link rewritten
    linker = (wiki / "initiatives" / "linker.md").read_text(encoding="utf-8")
    assert "[[initiatives/wheeler-center-solar-park]]" in linker
    # alias registered
    aliases = json.loads((tmp_path / "registry" / "entity_aliases.json").read_text())
    assert "landfill-solar-project" in aliases
    assert aliases["landfill-solar-project"]["canonical"] == "initiatives/wheeler-center-solar-park"
    # merge-log records a REDIRECT
    log = (tmp_path / "registry" / "merge-log.jsonl").read_text()
    assert '"action": "REDIRECT"' in log


def test_apply_redirect_falls_back_to_merge_when_old_has_unique_content(tmp_path):
    """Old page has a substantive fact not in canonical → route to the full
    LLM merge (content-preservation safeguard), never a silent delete."""
    from unittest.mock import patch
    from pipeline.phase_b_lint import apply_proposals
    unique = ("The Landfill Solar Project originally targeted twenty four megawatts "
              "of capacity and included a floating solar pilot on a retention pond.\n")
    wiki = _redirect_wiki(tmp_path, unique)

    with patch("pipeline.pass2c_merge.merge_pages", return_value="MERGED BODY") as mock_merge:
        apply_proposals(str(wiki),
                        str(tmp_path / "registry" / "entity_aliases.json"),
                        str(tmp_path / "registry" / "merge-log.jsonl"))
    mock_merge.assert_called_once()
    # old page still deleted, canonical got the merged body
    assert not (wiki / "initiatives" / "landfill-solar-project.md").exists()
    canonical = (wiki / "initiatives" / "wheeler-center-solar-park.md").read_text(encoding="utf-8")
    assert "MERGED BODY" in canonical
    log = (tmp_path / "registry" / "merge-log.jsonl").read_text()
    assert '"action": "REDIRECT_MERGE"' in log


def test_apply_keep_separate_writes_log_and_semantic_lint_then_skips(tmp_path):
    """End-to-end cycling fix: approving KEEP_SEPARATE writes a durable log
    entry, and a subsequent semantic_lint run no longer proposes that pair —
    even two identical-titled pages, which normally emit at confidence 1.0."""
    from pipeline.phase_b_lint import apply_proposals, semantic_lint
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "entity_aliases.json").write_text("{}", encoding="utf-8")
    (tmp_path / "registry" / "merge-log.jsonl").write_text("", encoding="utf-8")
    # Two pages with an identical title — normally an instant MERGE_PROPOSED (conf 1.0).
    (wiki / "initiatives" / "a.md").write_text(
        "---\ntype: initiative\ntitle: Shared Title\n---\n\nBody A.\n", encoding="utf-8")
    (wiki / "initiatives" / "b.md").write_text(
        "---\ntype: initiative\ntitle: Shared Title\n---\n\nBody B.\n", encoding="utf-8")

    # Before: semantic_lint proposes the identical-title pair.
    assert any(p["type"] == "MERGE_PROPOSED" for p in semantic_lint(str(wiki)))

    # Human marks KEEP_SEPARATE and applies.
    (tmp_path / "review-queue.md").write_text(
        "### [MERGE_PROPOSED] initiatives/a.md + initiatives/b.md\n"
        "- Action: [ ] APPROVE_MERGE  [x] KEEP_SEPARATE  [ ] DEFER\n",
        encoding="utf-8",
    )
    apply_proposals(str(wiki),
                    str(tmp_path / "registry" / "entity_aliases.json"),
                    str(tmp_path / "registry" / "merge-log.jsonl"))
    log = (tmp_path / "registry" / "merge-log.jsonl").read_text()
    assert '"action": "KEEP_SEPARATE"' in log

    # After: the same pair is no longer proposed.
    assert not any(p["type"] == "MERGE_PROPOSED" for p in semantic_lint(str(wiki)))
