# Strategy Foundation/Progression Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop strategy pages from losing CAP-2020 foundational content on every ingest, and recover the content already lost during the Year 3 ingest.

**Architecture:** Split every strategy page body into a frozen `## Foundation` section (CAP-2020 targets/costs/mechanism, written once, never touched by any pipeline pass again) and a `## Progress Synthesis` section (LLM-regenerated each ingest, now fed the *full* prior Progress Synthesis text instead of the lossy digest). A one-time migration recovers the lost Foundation content from git history (commit `1f027a6`, the last known-good state before the Year 3 ingest) and performs the initial section split for all 7 strategy pages.

**Tech Stack:** Python 3.13, pytest, existing `pipeline/_llm.py` chat/stream_chat wrappers.

---

### Task 1: Section split/assemble helpers in pass1b_synthesize.py

**Files:**
- Modify: `pipeline/pass1b_synthesize.py`
- Test: `tests/test_pass1b_synthesize.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_split_strategy_sections_both_present():
    from pipeline.pass1b_synthesize import _split_strategy_sections
    body = "## Foundation\n\nFoundation text here.\n\n## Progress Synthesis\n\nProgress text here.\n"
    foundation, progress = _split_strategy_sections(body)
    assert foundation == "Foundation text here."
    assert progress == "Progress text here."


def test_split_strategy_sections_legacy_single_body():
    from pipeline.pass1b_synthesize import _split_strategy_sections
    body = "This is a legacy single-body strategy page with no section headers."
    foundation, progress = _split_strategy_sections(body)
    assert foundation is None
    assert progress is None


def test_assemble_strategy_body_round_trip():
    from pipeline.pass1b_synthesize import _split_strategy_sections, _assemble_strategy_body
    assembled = _assemble_strategy_body("Foundation text.", "Progress text.")
    foundation, progress = _split_strategy_sections(assembled)
    assert foundation == "Foundation text."
    assert progress == "Progress text."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pass1b_synthesize.py -k split_strategy_sections -v`
Expected: FAIL with `ImportError: cannot import name '_split_strategy_sections'`

- [ ] **Step 3: Implement the helpers**

Add near `_replace_wiki_page_body` (currently line 477) in `pipeline/pass1b_synthesize.py`:

```python
def _split_strategy_sections(body: str) -> tuple[str | None, str | None]:
    """Return (foundation_text, progress_text). Either is None if the page
    predates the split (legacy single-body page) or the section is absent."""
    fm = re.search(
        r"^##\s*Foundation\s*\n(.*?)(?=^##\s*Progress Synthesis\s*\n|\Z)",
        body, re.DOTALL | re.MULTILINE,
    )
    pm = re.search(r"^##\s*Progress Synthesis\s*\n(.*)\Z", body, re.DOTALL | re.MULTILINE)
    if not fm or not pm:
        return None, None
    return fm.group(1).strip(), pm.group(1).strip()


def _assemble_strategy_body(foundation: str, progress: str) -> str:
    return f"## Foundation\n\n{foundation}\n\n## Progress Synthesis\n\n{progress}\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pass1b_synthesize.py -k split_strategy_sections -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/pass1b_synthesize.py tests/test_pass1b_synthesize.py
git commit -m "feat: add strategy section split/assemble helpers"
```

---

### Task 2: `_write_synthesis` refuses full-body overwrite, writes Progress Synthesis only

**Files:**
- Modify: `pipeline/pass1b_synthesize.py` (lines 514–528)
- Test: `tests/test_pass1b_synthesize.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_write_synthesis_refuses_when_foundation_missing(tmp_path):
    from pipeline.pass1b_synthesize import _write_synthesis
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    (strategies_dir / "strategy-1-renewable-grid.md").write_text(
        "---\ntype: strategy\n---\nLegacy single-body content, no sections.\n"
    )
    result = {
        "overview": {"slug": "overviews/test", "frontmatter": {
            "type": "overview", "title": "Test", "source-ref": "[[sources/test]]"
        }, "body": "Test overview."},
        "strategy_bodies": [
            {"slug": "strategies/strategy-1-renewable-grid", "body": "New progress text."}
        ],
        "stub_pages": [],
    }
    import pytest
    with pytest.raises(RuntimeError, match="no Foundation section"):
        _write_synthesis(result, wiki_root=str(tmp_path), source_uuid="test",
                          source_rel_path="sources/test.md", run_date="2026-07-01")


def test_write_synthesis_updates_progress_preserves_foundation(tmp_path):
    from pipeline.pass1b_synthesize import _write_synthesis, _split_strategy_sections
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    (strategies_dir / "strategy-1-renewable-grid.md").write_text(
        "---\ntype: strategy\n---\n"
        "## Foundation\n\nOriginal CAP-2020 target text.\n\n"
        "## Progress Synthesis\n\nOld progress text.\n"
    )
    result = {
        "overview": {"slug": "overviews/test", "frontmatter": {
            "type": "overview", "title": "Test", "source-ref": "[[sources/test]]"
        }, "body": "Test overview."},
        "strategy_bodies": [
            {"slug": "strategies/strategy-1-renewable-grid", "body": "New progress text, building on the old."}
        ],
        "stub_pages": [],
    }
    _write_synthesis(result, wiki_root=str(tmp_path), source_uuid="test",
                      source_rel_path="sources/test.md", run_date="2026-07-01")
    written = (strategies_dir / "strategy-1-renewable-grid.md").read_text()
    foundation, progress = _split_strategy_sections(
        re.sub(r"^---\n.*?\n---\n", "", written, flags=re.DOTALL)
    )
    assert foundation == "Original CAP-2020 target text."
    assert progress == "New progress text, building on the old."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pass1b_synthesize.py -k write_synthesis_refuses or write_synthesis_updates -v`
Expected: FAIL — current `_write_synthesis` does an unconditional overwrite, doesn't raise, doesn't preserve Foundation

- [ ] **Step 3: Modify `_write_synthesis`**

Replace the strategy-writing loop in `pipeline/pass1b_synthesize.py` (currently lines 514–528):

```python
    for sb in result.get("strategy_bodies", []):
        strat_path = Path(wiki_root) / (sb["slug"] + ".md")
        if not strat_path.exists():
            print(f"[holistic] WARNING: strategy stub missing: {strat_path} — skipping")
            continue
        existing = strat_path.read_text(encoding="utf-8")
        existing_body = re.sub(r"^---\n.*?\n---\n", "", existing, flags=re.DOTALL).strip()
        foundation, _ = _split_strategy_sections(existing_body)

        if foundation is None:
            raise RuntimeError(
                f"{strat_path} has no Foundation section. Run the one-time "
                f"Foundation migration (docs/architecture/strategy-foundation-progression.md) "
                f"before ingesting further sources."
            )

        new_body = _assemble_strategy_body(foundation, sb["body"])
        _replace_wiki_page_body(str(strat_path), new_body)
        print(f"[holistic] Progress Synthesis updated: {strat_path.name}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pass1b_synthesize.py -k write_synthesis_refuses or write_synthesis_updates -v`
Expected: 2 passed

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `pytest tests/ -q`
Expected: some pre-existing tests referencing the old stub-write behavior may now fail if they use single-body fixtures without Foundation sections — update those fixtures to include `## Foundation` / `## Progress Synthesis` headers.

- [ ] **Step 6: Commit**

```bash
git add pipeline/pass1b_synthesize.py tests/test_pass1b_synthesize.py
git commit -m "fix: _write_synthesis refuses full-body overwrite, preserves Foundation section"
```

---

### Task 3: Inject full existing Progress Synthesis into Writer context (not digest-gated)

**Files:**
- Modify: `pipeline/pass1b_synthesize.py` (context-injection block, currently lines 340–375; system prompt, lines 58–82)
- Test: `tests/test_pass1b_synthesize.py`

- [ ] **Step 1: Write the failing test**

```python
def test_context_injection_includes_progress_synthesis_regardless_of_digest(tmp_path, monkeypatch):
    """Existing Progress Synthesis text must be injected into the Writer prompt
    even when a digest is present — this was the root cause of the content-loss bug."""
    from pipeline import pass1b_synthesize as mod
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    (strategies_dir / "strategy-1-renewable-grid.md").write_text(
        "---\ntype: strategy\n---\n"
        "## Foundation\n\nCAP-2020 target: 41% reduction, $4.1M cost.\n\n"
        "## Progress Synthesis\n\nYear 1 baseline established.\n"
    )
    captured = {}
    def fake_llm_call(*args, **kwargs):
        captured["prompt"] = kwargs.get("messages", args[1] if len(args) > 1 else "")
        raise SystemExit("stop after capturing prompt")
    monkeypatch.setattr(mod, "_llm_call", fake_llm_call)

    with pytest.raises(SystemExit):
        mod.synthesize_source(
            source_content="New source text.", source_uuid="test",
            source_type="annual-report", wiki_root=str(tmp_path),
            digest_content="[compressed digest — should NOT be the only context]",
            run_date="2026-07-01",
        )
    prompt_text = str(captured["prompt"])
    assert "Year 1 baseline established" in prompt_text
    assert "CAP-2020 target: 41% reduction" not in prompt_text  # Foundation is NOT injected — frozen, not context
```

*(Adjust the mock target to whatever `synthesize_source`'s actual internal LLM-call function signature is — verify against the real code before writing this test; the point is to assert the full prior Progress Synthesis text appears in the outbound prompt even when `digest_content` is non-None.)*

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pass1b_synthesize.py -k context_injection_includes_progress -v`
Expected: FAIL — "Year 1 baseline established" absent from prompt when digest_content is set (current bug)

- [ ] **Step 3: Modify the context-injection logic**

In `pipeline/pass1b_synthesize.py`, locate the branch around line 340–375 (`if digest_content: ... else: # legacy fallback`). Replace the `if/else` exclusivity with unconditional Progress Synthesis injection, keeping digest injection additive:

```python
    lines = [...]  # existing digest-related lines, unchanged, still gated on `if digest_content:`
    if digest_content:
        lines.extend([
            "\n[WIKI DIGEST — current state of the wiki]",
            "READ-UNDERSTAND-INTEGRATE: this digest reflects what the wiki already",
            "knows. Build on it rather than re-stating known facts.\n",
            digest_content,
            "[END WIKI DIGEST]",
        ])
    integration_block = "\n".join(lines)

    # Always inject full existing Progress Synthesis text — regardless of
    # whether a digest exists. The digest is cross-strategy narrative context;
    # this is the actual full-fidelity source of truth for what NOT to lose.
    existing_progress: dict[str, str] = {}
    strategies_dir = Path(wiki_root) / "strategies"
    if strategies_dir.exists():
        for strat_file in sorted(strategies_dir.glob("*.md")):
            content = strat_file.read_text(encoding="utf-8")
            body = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL).strip()
            _, progress = _split_strategy_sections(body)
            if progress:
                existing_progress[f"strategies/{strat_file.stem}"] = progress

    if existing_progress:
        prog_lines = [
            "\n\n[EXISTING PROGRESS SYNTHESIS — every strategy]",
            "READ-UNDERSTAND-INTEGRATE: this is the FULL prior Progress Synthesis text",
            "for each strategy, not a summary. Preserve every fact in it. Add new depth",
            "from THIS source. Do not discard anything. The Foundation section (not",
            "shown here, and NOT yours to write) already holds each strategy's original",
            "design intent — your job is only to extend the progress narrative.\n",
        ]
        for slug, text in sorted(existing_progress.items()):
            prog_lines.append(f"--- {slug} ---\n{text}\n")
        prog_lines.append("[END EXISTING PROGRESS SYNTHESIS]")
        integration_block += "\n".join(prog_lines)
```

Remove the old `else:` legacy-fallback branch entirely (lines ~355–375 in the current file) — it's superseded by the always-on Progress Synthesis injection above.

- [ ] **Step 4: Update the system prompt**

In `HOLISTIC_WRITER_SYSTEM` (starting line 30), update the `STRATEGY BODY RULES` section (lines 58–70) and `READ-UNDERSTAND-INTEGRATE` block (lines 73–82):

```python
STRATEGY BODY RULES:
- Write 2-4 paragraphs of PROGRESS SYNTHESIS narrative per strategy — NOT the
  strategy's original design, target, or cost estimate. That content lives in
  a separate, frozen "Foundation" section you never see and never write.
- SYNTHESIZE, do not list: what programs are proposed? what are measured outcomes?
  what dependencies exist?
- If the document says little about a strategy, write one honest sentence
- Cite with inline wikilinks: ([[{source_path}|{source_uuid}]])
- REQUIRED — entity wikilinks: every initiative, actor, organization, location, and
  technology you name MUST be linked using the slug you assigned it in stub_pages.
  Link on FIRST MENTION of each entity; subsequent mentions may be plain text.
- Include all 7 strategy slugs in strategy_bodies, even if coverage is thin
- Your response body is PLAIN PROSE ONLY — never emit a markdown heading (a line
  starting with "##") inside strategy_bodies[].body. The pipeline adds section
  headers itself; a heading in your output will be rejected by validation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
READ-UNDERSTAND-INTEGRATE (applies when EXISTING PROGRESS SYNTHESIS is provided):
The section [EXISTING PROGRESS SYNTHESIS] below contains the FULL prior progress
narrative for each strategy, not a summary — preserve every fact in it verbatim
or near-verbatim, add new depth from THIS source, and do not duplicate paragraphs
that already say the same thing. Your output REPLACES the existing Progress
Synthesis, so it must be complete: a reader who has not seen the prior version
should find it fully coherent.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

- [ ] **Step 5: Add validation that no `##` heading appears in strategy body output**

In `_validate_synthesis_output` (line 255), inside the `for sb in result.get("strategy_bodies", []):` loop (around line 294–304), add:

```python
        if re.search(r"^##\s", sb.get("body", ""), re.MULTILINE):
            errors.append(
                f"strategy_bodies body for {s!r} contains a markdown heading — "
                f"the LLM must return plain prose only; headers are added by the pipeline"
            )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_pass1b_synthesize.py -v`
Expected: all pass, including the new context-injection test

- [ ] **Step 7: Run full suite**

Run: `pytest tests/ -q`
Expected: all green

- [ ] **Step 8: Commit**

```bash
git add pipeline/pass1b_synthesize.py tests/test_pass1b_synthesize.py
git commit -m "fix: always inject full prior Progress Synthesis into Writer context, not gated on digest absence"
```

---

### Task 4: Thread Foundation text + ingest history into Phase C synthesis

**Files:**
- Modify: `pipeline/phase_c_synthesize.py`
- Test: `tests/test_phase_c_synthesize.py`

- [ ] **Step 1: Write failing tests**

```python
def test_extract_ingest_history_returns_all_entries(tmp_path):
    from pipeline.phase_c_synthesize import extract_ingest_history
    log_path = tmp_path / "log.md"
    log_path.write_text(
        "## [2026-06-01 | a2zero-year1]\nsome entry\n\n"
        "## [2026-06-15 | a2zero-year2]\nsome entry\n\n"
        "## [2026-06-30 | a2zero-year3]\nsome entry\n"
    )
    history = extract_ingest_history(str(log_path))
    assert history == [
        {"date": "2026-06-01", "source_uuid": "a2zero-year1"},
        {"date": "2026-06-15", "source_uuid": "a2zero-year2"},
        {"date": "2026-06-30", "source_uuid": "a2zero-year3"},
    ]


def test_build_strategy_synthesis_prompt_includes_foundation_and_history(monkeypatch):
    from pipeline import phase_c_synthesize as mod
    captured = {}
    def fake_chat(**kwargs):
        captured["user_msg"] = kwargs["messages"][0]["content"]
        return '{"core-initiatives": [], "core-actors": [], "year-over-year-arc": "x", "open-questions": [], "cross-strategy-links": []}'
    monkeypatch.setattr(mod, "chat", fake_chat)

    mod.build_strategy_synthesis(
        strategy_slug="strategies/strategy-1-renewable-grid",
        strategy_title="Strategy 1",
        entities=[],
        foundation_text="CAP-2020 target: 41% reduction.",
        ingest_history=[
            {"date": "2026-06-01", "source_uuid": "a2zero-year1"},
            {"date": "2026-06-30", "source_uuid": "a2zero-year3"},
        ],
    )
    assert "CAP-2020 target: 41% reduction." in captured["user_msg"]
    assert "2026-06-01" in captured["user_msg"]
    assert "a2zero-year3" in captured["user_msg"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_phase_c_synthesize.py -k extract_ingest_history or includes_foundation -v`
Expected: FAIL — `extract_ingest_history` doesn't exist; `build_strategy_synthesis` doesn't accept the new kwargs

- [ ] **Step 3: Add `extract_ingest_history`**

In `pipeline/phase_c_synthesize.py`, add next to `extract_recent_delta` (line 67):

```python
def extract_ingest_history(log_path: str) -> list[dict]:
    """Return [{date, source_uuid}, ...] for every ingest in log.md, chronological."""
    try:
        text = Path(log_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [
        {"date": date, "source_uuid": uuid.strip()}
        for date, uuid in _LOG_ENTRY_RE.findall(text)
    ]
```

- [ ] **Step 4: Extend `build_strategy_synthesis` signature and prompt**

Modify `pipeline/phase_c_synthesize.py` (line 119–145):

```python
def build_strategy_synthesis(
    strategy_slug: str,
    strategy_title: str,
    entities: list[dict],
    foundation_text: str = "",
    ingest_history: list[dict] | None = None,
) -> dict:
    """LLM call: produce the synthesis dict for one strategy."""
    entity_lines = "\n".join(
        f"- [{e['type']}] {e['slug']} — {e['title']}: {e.get('one-liner','')}"
        for e in entities
    )
    history_lines = "\n".join(
        f"- {h['date']}: {h['source_uuid']}" for h in (ingest_history or [])
    )
    user_msg = (
        f"Strategy: {strategy_title} ({strategy_slug})\n\n"
        + (f"[FOUNDATION — original design intent, frozen, for reference only]\n"
           f"{foundation_text}\n[END FOUNDATION]\n\n" if foundation_text else "")
        + (f"[INGEST HISTORY — sources contributing to this synthesis, chronological]\n"
           f"{history_lines}\n[END INGEST HISTORY]\n\n" if history_lines else "")
        + f"Entity inventory ({len(entities)} pages):\n{entity_lines}\n\n"
        "Produce the synthesis JSON now."
    )
    try:
        raw = chat(
            system=_STRATEGY_SYNTHESIS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
            model_hint="synthesis",
            temperature=0.0,
        )
        return json.loads(_strip_code_fence(raw))
    except Exception as e:
        print(f"[synthesize_wiki] build_strategy_synthesis failed for {strategy_slug}: {e}")
        return _empty_synthesis()
```

Update `_STRATEGY_SYNTHESIS_SYSTEM` (line 80–97) to mention the new optional FOUNDATION and INGEST HISTORY blocks and instruct the model to use ingest history dates to write a real `year-over-year-arc` (e.g. "Y1 (2026-06-01) established baseline; Y3 (2026-06-30) shows...") instead of boilerplate, and to reference Foundation targets/mechanisms in a new synthesis field:

```python
- core-target: one sentence citing the Foundation's original numeric target or
  cost estimate for this strategy, if FOUNDATION context is provided (else "—")
```

Add `"core-target": "—"` to `_empty_synthesis()` (line 109–116) as the default.

- [ ] **Step 5: Wire the new params into `synthesize_wiki`'s orchestration loop**

Modify `synthesize_wiki` (line 322+), inside the `else:` branch (non-digest_only, around line 361–366):

```python
        else:
            page = Path(wiki_root) / (strategy_slug + ".md")
            foundation_text = ""
            if page.exists():
                body = re.sub(r"^---\n.*?\n---\n", "", page.read_text(encoding="utf-8"), flags=re.DOTALL).strip()
                from pipeline.pass1b_synthesize import _split_strategy_sections
                foundation_text, _ = _split_strategy_sections(body) or ("", "")
            ingest_history = extract_ingest_history(str(Path(wiki_root) / "log.md"))

            synthesis = build_strategy_synthesis(
                strategy_slug=strategy_slug,
                strategy_title=title,
                entities=entities,
                foundation_text=foundation_text or "",
                ingest_history=ingest_history,
            )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_phase_c_synthesize.py -v`
Expected: all pass

- [ ] **Step 7: Run full suite**

Run: `pytest tests/ -q`
Expected: all green

- [ ] **Step 8: Commit**

```bash
git add pipeline/phase_c_synthesize.py tests/test_phase_c_synthesize.py
git commit -m "feat: thread Foundation text + ingest history into strategy synthesis (fixes stale year-over-year-arc)"
```

---

### Task 5: One-time Foundation migration — extract directly from CAP-2020

**Files:**
- Create: `scripts/migrate_strategy_foundation.py` (one-off, not part of the permanent pipeline — do not wire into orchestrator.py)

**Rationale for this approach (revised 2026-07-01):** Foundation is CAP-2020's original design intent, so it must come from CAP-2020 alone — not from git-recovered wiki content, which was already a CAP-2020/Year-1/Year-2 blend by the time it was captured. CAP-2020 has a clean, page-cited target/cost sentence within each of the 7 strategy sections (verified below and independently re-verified after migration).

**Correction (2026-07-01, post-migration):** this plan originally claimed "Other Actions" (Strategy 7) had no quantified target. That was wrong. Direct source verification found line 3481 explicitly states a 14%/$6M combined target for Other Actions — same pattern as Strategies 1–6. All 7 strategies have an explicit target in CAP-2020. Also corrected: Strategy 6's target sentence is at line 3035 ("In total, these actions contribute...", different phrasing than 1–5's "Combined, these N actions..." pattern), not line 3481 as originally guessed — line 3481 belongs to the Other Actions section. The migration script was robust to this line-number imprecision because it extracts from the full section range, not a single line; the LLM correctly located the real target sentence within Strategy 6's actual range regardless.

```
Strategy 1 — cap-2020.md:407  (target sentence at line 416:  41% / $4,100,000)
Strategy 2 — cap-2020.md:745  (target sentence at line 755:  23% / $143,000,000)
Strategy 3 — cap-2020.md:1242 (target sentence at line 1258: 13.4% / $14,500,000)
Strategy 4 — cap-2020.md:2040 (target sentence at line 2052: 8% / $901,000,000)
Strategy 5 — cap-2020.md:2638 (target sentence at line 2649: 0.3% / $45,000,000)
Strategy 6 — cap-2020.md:3024 (target sentence at line 3035: 0.1% / $7,500,000)
Strategy 7 — cap-2020.md:3472 "## Other Actions" (target sentence at line 3481: 14% / $6,000,000)
```

- [ ] **Step 1: Confirm section boundaries**

```bash
grep -n "^## Strategy\|^## Other Actions\|^## Postponed" wiki/sources/cap/cap-2020.md
```

Expected: the 8 headings above, in order (Strategy 1 through 6, Other Actions, Postponed or Delayed Events — the last marks the end of Strategy 7's content range).

- [ ] **Step 2: Write the extraction script**

```python
"""One-time migration: build Foundation sections directly from cap-2020.md
(the sole source of truth for original design intent), and split each
strategy page into Foundation (new) + Progress Synthesis (current body,
preserved as the Year 1-3 starting point for Pass 1B's next regeneration).

Run once. Not part of the ongoing pipeline. See
docs/architecture/strategy-foundation-progression.md for rationale.
"""
import re
from pathlib import Path

from pipeline._llm import chat

WIKI_ROOT = Path("wiki")
CAP_2020_PATH = WIKI_ROOT / "sources" / "cap" / "cap-2020.md"

# (strategy_slug, cap_2020_start_line, cap_2020_end_line) — 1-indexed, inclusive
SECTIONS = [
    ("strategies/strategy-1-renewable-grid", 407, 744),
    ("strategies/strategy-2-electrification", 745, 1241),
    ("strategies/strategy-3-building-efficiency", 1242, 2039),
    ("strategies/strategy-4-vmt-reduction", 2040, 2637),
    ("strategies/strategy-5-materials-waste", 2638, 3023),
    ("strategies/strategy-6-resilience", 3024, 3471),
    ("strategies/strategy-7-engagement", 3472, 3845),  # "Other Actions" through end
]

_FOUNDATION_SYSTEM = """You extract ONLY explicitly-stated facts from a section of \
Ann Arbor's CAP-2020 carbon neutrality plan, to build a frozen "Foundation" \
reference for one strategy. This will never be regenerated after this run — \
accuracy matters more than completeness.

Return 2-4 sentences of prose covering, if and only if stated in the text:
- The combined GHG emissions reduction target and cost estimate (quote numbers
  and the page citation exactly as written, e.g. "41%" and "$4,100,000 [Source: Page 21]")
- The dominant mechanism or policy tool (e.g. Community Choice Aggregation)
- The named actions/initiatives this strategy comprises

If the section contains NO quantified target (this is expected and correct for
some sections — e.g. cross-cutting "Other Actions" content), do not invent one.
Say so plainly: "This section has no quantified emissions or cost target in
CAP-2020; it covers [describe the actual content]."

Cite the source inline: ([[sources/cap/cap-2020|cap-2020]])
Return ONLY the prose. No preamble, no headers, no bullet points.
"""


def extract_foundation(strategy_slug: str, section_text: str) -> str:
    return chat(
        system=_FOUNDATION_SYSTEM,
        messages=[{"role": "user", "content": section_text}],
        max_tokens=1024,
        model_hint="extraction",
        temperature=0.0,
    ).strip()


def main():
    all_lines = CAP_2020_PATH.read_text(encoding="utf-8").splitlines()

    for slug, start, end in SECTIONS:
        section_text = "\n".join(all_lines[start - 1:end])
        foundation_text = extract_foundation(slug, section_text)

        page_path = WIKI_ROOT / f"{slug}.md"
        current = page_path.read_text(encoding="utf-8")
        fm_match = re.match(r"^(---\n.*?\n---\n)", current, re.DOTALL)
        frontmatter = fm_match.group(1) if fm_match else ""
        current_body = re.sub(r"^---\n.*?\n---\n", "", current, flags=re.DOTALL).strip()

        # Current body becomes the Progress Synthesis starting point — it's
        # real Year-3 narrative, just incomplete. Pass 1B's next ingest
        # (with Task 3's fix) will extend it properly across all sources.
        new_body = (
            f"## Foundation\n\n{foundation_text}\n\n"
            f"## Progress Synthesis\n\n{current_body}\n"
        )
        page_path.write_text(frontmatter + "\n" + new_body, encoding="utf-8")
        print(f"[migrate] {slug}: Foundation written ({len(foundation_text)} chars)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the script**

```bash
LLM_PROVIDER=anthropic python scripts/migrate_strategy_foundation.py
```

- [ ] **Step 4: Human review of all 7 Foundation sections**

Read each `## Foundation` section written. Cross-check the quoted numbers against the source lines identified in Step 1 (e.g. Strategy 1's Foundation should state "41%" and "$4,100,000" — verify these appear verbatim, not paraphrased or drifted). Confirm Strategy 7's Foundation correctly states it has no numeric target rather than fabricating one. Fix any discrepancy by hand before proceeding — this is the one human checkpoint that guarantees Foundation's accuracy going forward.

- [ ] **Step 5: Verify structural integrity**

```bash
python -m pytest tests/ -q
python -m pipeline.phase_b_lint --wiki-root wiki --structural
```

Expected: tests green (fixture files that predate the split may need `## Foundation`/`## Progress Synthesis` headers added — see Task 2 Step 5), 0 broken links.

- [ ] **Step 6: Commit**

```bash
git add wiki/strategies/*.md scripts/migrate_strategy_foundation.py
git commit -m "data: build Foundation sections directly from cap-2020.md, split strategy pages"
```

---

### Task 6: Rebuild digest + final verification

**Files:**
- Run: `pipeline/phase_c_synthesize.py` via CLI
- Modify: `CLAUDE.md`, `CHANGELOG.md`

- [ ] **Step 1: Rebuild Phase C synthesis with the new Foundation-aware logic**

```bash
LLM_PROVIDER=anthropic python -m pipeline.phase_c_synthesize --wiki-root wiki
```

Expected output: `[synthesize_wiki] rebuilt 7 strategies`, digest written. Manually inspect `wiki/digest.md` — confirm it now cites CAP-2020 targets/mechanisms alongside progress, and `year-over-year-arc` fields describe an actual trajectory instead of "no multi-year trend data yet ingested."

- [ ] **Step 2: Full verification**

```bash
python -m pytest tests/ -q
python -m pipeline.phase_b_lint --wiki-root wiki --structural
```

Expected: all green, 0 broken links.

- [ ] **Step 3: Update CLAUDE.md**

Add a note under "Active Architectural Direction" (or a new section) documenting the Foundation/Progression split, referencing `docs/architecture/strategy-foundation-progression.md`, and stating clearly: strategy page bodies now have two sections; `## Foundation` is never regenerated after the one-time migration; `## Progress Synthesis` is the only section Pass 1B touches.

- [ ] **Step 4: Update CHANGELOG.md**

Add an entry documenting: the content-quality audit finding, the root cause, the fix, and the recovery of lost CAP-2020 content.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md CHANGELOG.md wiki/digest.md
git commit -m "docs: document Foundation/Progression split; rebuild digest with recovered content"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1–3 implement the core structural fix (pass1b_synthesize.py). Task 4 implements the Foundation-field + year-over-year-arc fix in phase_c_synthesize.py. Task 5 recovers lost content. Task 6 verifies and documents. All three "Decisions" from the spec are covered: Foundation-derived synthesis field (Task 4), future-CAP out of scope (no task needed), plain-prose no-`##`-headers enforcement (Task 3 step 5).
- **Placeholder scan:** Task 5's migration is intentionally semi-manual with a clear human-judgment boundary explained — not a placeholder, a deliberate design choice documented in the spec's Migration section.
- **Type consistency:** `_split_strategy_sections` returns `tuple[str | None, str | None]` consistently across all call sites (Task 1, 2, 3, 4).

## Execution Handoff

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, spec-compliance + code-quality review between tasks.

**2. Inline Execution** — batch execution in this session with checkpoints for review.

Which approach?
