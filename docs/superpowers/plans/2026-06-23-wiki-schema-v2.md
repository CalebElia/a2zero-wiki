# Wiki Schema V2 — Wikilinks, Hierarchy, Plan Extractor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the wiki generation pipeline to produce a fully interlinked Obsidian graph with Plan → Strategy → Initiative hierarchy, wikilink citations to silver files, and a dedicated first-pass plan page extractor.

**Architecture:** Replace the `commitment` page type with `initiative` (which absorbs all discrete CAP actions), remove `strategy` from the forbidden list (add slug-whitelist guard instead), add a new `plan` type created by a dedicated pre-chunk LLM call, and rewrite the prompt throughout to output `[[wikilinks]]` everywhere including citations pointing back to silver source files. All entity references in frontmatter and body become navigable graph edges in Obsidian.

**Tech Stack:** Python 3.11, Anthropic claude-sonnet-4-6, PyYAML, pytest, Obsidian vault at `a2zero-wiki/`

---

## Pre-Task: Archive current wiki output (manual — run before any code task)

The current wiki output has no wikilinks, empty strategy pages, and the wrong type hierarchy. Archive it before re-ingesting.

```bash
# From a2zero-wiki/
mkdir -p archive/wiki-v2-ingest-1
cp -r wiki/actors wiki/commitments wiki/initiatives wiki/technology \
      wiki/locations wiki/meetings wiki/political-events \
      wiki/contradictions wiki/funding-events \
      archive/wiki-v2-ingest-1/

# Remove the generated pages — keep strategies/ and topics/ (hand-curated stubs)
rm -rf wiki/actors wiki/commitments wiki/initiatives wiki/technology \
       wiki/locations wiki/meetings wiki/political-events \
       wiki/contradictions wiki/funding-events

# Create the new plans directory
mkdir -p wiki/plans
```

Keep `wiki/strategies/` and `wiki/topics/` intact — they are hand-curated stubs.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `pipeline/silver_to_gold.py` | Modify | Update `VALID_PAGE_TYPES`: remove `commitment`, add `plan` |
| `pipeline/wiki_writer.py` | Modify | Update `PASS3_FORBIDDEN_TYPES`; add whitelist guard; thread `silver_relative_path`; rewrite `WIKI_PAGES_SYSTEM` prompt |
| `pipeline/plan_extractor.py` | Create | New module: `extract_plan_page()` — dedicated first-pass plan page extraction |
| `pipeline/ldp.py` | Modify | Thread `silver_relative_path` through `run_ldp_ingest` → `extract_quads_chunked` → `extract_wiki_pages_from_chunk` |
| `pipeline/run_ingest.py` | Modify | Call `extract_plan_page()` before chunk loop; thread `silver_relative_path` |
| `tests/test_wiki_extractor.py` | Modify | Update `MOCK_PAGES` (commitment → initiative); update forbidden/allowed type tests; add whitelist test |
| `tests/test_plan_extractor.py` | Create | Tests for `extract_plan_page()` |

---

## Task 1: Update VALID_PAGE_TYPES and PASS3_FORBIDDEN_TYPES

**Files:**
- Modify: `pipeline/silver_to_gold.py:119-125`
- Modify: `pipeline/wiki_writer.py:14-21`
- Modify: `tests/test_wiki_extractor.py:30-68, 122-147`

- [ ] **Step 1: Write failing tests**

In `tests/test_wiki_extractor.py`, update the constants and three test functions. Replace the entire `MOCK_PAGES` block and the three type-checking tests:

```python
# Replace the MOCK_PAGES constant (lines 30-68) with:
MOCK_PAGES = [
    {
        "page_type": "initiative",
        "slug": "initiatives/community-choice-aggregation",
        "frontmatter": {
            "type": "initiative",
            "title": "Community Choice Aggregation",
            "parent-strategy": "[[strategies/strategy-1-renewable-grid]]",
            "related-strategies": [],
            "party-responsible": "[[actors/osi]]",
            "partners": [],
            "status": "committed",
            "launched": None,
            "locations": [],
            "funding-events": [],
            "milestones": [
                {
                    "year": 2027,
                    "target": "CCA program launched",
                    "status": "unverified",
                    "source": "[[silver/cap/cap-2020]]",
                }
            ],
            "tags": ["cca", "renewable-energy", "strategy-1"],
            "source-first-seen": "[[silver/cap/cap-2020]]",
            "last-updated": "2026-06-23",
        },
        "body": "Community Choice Aggregation allows Ann Arbor to procure renewable electricity for all residents. ([[silver/cap/cap-2020|cap-2020]])",
    },
    {
        "page_type": "actor",
        "slug": "actors/osi",
        "frontmatter": {
            "type": "actor",
            "title": "Office of Sustainability and Innovations",
            "actor-type": "government-office",
            "role": "Lead implementer of A2Zero programs",
            "affiliation": "[[actors/city-of-ann-arbor]]",
            "elected": None,
            "active-years": [2020],
            "programs-involved": ["[[initiatives/community-choice-aggregation]]"],
            "tags": ["osi", "city-staff", "leadership"],
            "source-first-seen": "[[silver/cap/cap-2020]]",
            "last-updated": "2026-06-23",
        },
        "body": "OSI is the primary city department responsible for implementing A2Zero. ([[silver/cap/cap-2020|cap-2020]])",
    },
]


# Replace test_validate_page_spec_accepts_valid_commitment (line 92) with:
def test_validate_page_spec_accepts_valid_initiative():
    from pipeline.wiki_writer import validate_page_spec
    errors = validate_page_spec(MOCK_PAGES[0])
    assert errors == []


# Replace test_validate_page_spec_rejects_forbidden_types (line 122) with:
def test_validate_page_spec_rejects_forbidden_types():
    """Plan, topic, mechanism, synthesis must never be created by Pass 3."""
    from pipeline.wiki_writer import validate_page_spec
    for forbidden in ("plan", "topic", "synthesis", "mechanism"):
        spec = {**MOCK_PAGES[0], "page_type": forbidden}
        errors = validate_page_spec(spec)
        assert any("forbidden" in e for e in errors), (
            f"Expected forbidden error for page_type={forbidden!r}, got: {errors}"
        )


# Replace test_validate_page_spec_accepts_all_ten_llm_writable_types (line 133) with:
def test_validate_page_spec_accepts_all_llm_writable_types():
    """All 10 LLM-writable types pass type validation (commitment removed, strategy added)."""
    from pipeline.wiki_writer import validate_page_spec
    for pt in ("strategy", "initiative", "actor", "funding-event",
               "technology", "location", "meeting", "framing",
               "political-event", "contradiction"):
        spec = {
            "page_type": pt,
            "slug": f"test/{pt}-slug",
            "frontmatter": {"type": pt},
            "body": "Test body. ([[silver/cap/cap-2020|cap-2020]])",
        }
        errors = validate_page_spec(spec)
        type_errors = [e for e in errors if "page_type" in e or "forbidden" in e]
        assert type_errors == [], f"Unexpected type error for {pt!r}: {type_errors}"


# Add new test — commitment is now rejected:
def test_validate_page_spec_rejects_commitment_type():
    """The 'commitment' type is eliminated in V2 — all actions are initiatives."""
    from pipeline.wiki_writer import validate_page_spec
    spec = {**MOCK_PAGES[0], "page_type": "commitment"}
    errors = validate_page_spec(spec)
    assert any("page_type" in e for e in errors), (
        f"Expected invalid page_type error for 'commitment', got: {errors}"
    )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/calebjohnson/Desktop/Grapevine/a2zero-wiki
python -m pytest tests/test_wiki_extractor.py::test_validate_page_spec_rejects_forbidden_types \
    tests/test_wiki_extractor.py::test_validate_page_spec_accepts_all_llm_writable_types \
    tests/test_wiki_extractor.py::test_validate_page_spec_rejects_commitment_type \
    -v 2>&1 | head -40
```

Expected: FAIL — strategy is still in forbidden, commitment still valid, plan not yet added.

- [ ] **Step 3: Update VALID_PAGE_TYPES in silver_to_gold.py**

Replace lines 119-125 in `pipeline/silver_to_gold.py`:

```python
VALID_PAGE_TYPES = frozenset({
    # LLM-writable via wiki_writer.py (Pass 3) — chunk extraction:
    "strategy", "initiative", "actor", "funding-event", "technology",
    "location", "meeting", "framing", "political-event", "contradiction", "mechanism",
    # First-pass extraction (plan_extractor.py), never by Pass 3 chunk extraction:
    "plan",
    # Pre-created by data team or generated by post-ingest pipeline:
    "topic", "synthesis",
})
```

- [ ] **Step 4: Update PASS3_FORBIDDEN_TYPES in wiki_writer.py**

Replace lines 14-21 in `pipeline/wiki_writer.py`:

```python
# Types that Pass 3 chunk extraction must NEVER create.
# "strategy" is allowed (with slug-whitelist guard in validate_page_spec).
# "plan" is created by plan_extractor.py before chunking, not here.
PASS3_FORBIDDEN_TYPES = frozenset({
    "plan",       # created by dedicated first-pass call before chunking
    "topic",      # human-declared only; LLM never creates topic pages
    "mechanism",  # requires cross-source corroboration; not created per-chunk
    "synthesis",  # generated by post-ingest pipeline, not during extraction
})
```

- [ ] **Step 5: Run the tests — expect pass**

```bash
python -m pytest tests/test_wiki_extractor.py::test_validate_page_spec_rejects_forbidden_types \
    tests/test_wiki_extractor.py::test_validate_page_spec_accepts_all_llm_writable_types \
    tests/test_wiki_extractor.py::test_validate_page_spec_rejects_commitment_type \
    -v
```

Expected: PASS

- [ ] **Step 6: Fix remaining test breakage from MOCK_PAGES change**

Run the full extractor test suite to find broken tests:

```bash
python -m pytest tests/test_wiki_extractor.py -v 2>&1 | grep -E "FAILED|ERROR|PASSED"
```

Update `test_write_or_append_page_creates_new_file` and similar tests that reference the old commitment slug path. Find all assertions referencing `"commitments/implement-community-choice-aggregation"` and change them to `"initiatives/community-choice-aggregation"`:

```python
def test_write_or_append_page_creates_new_file(tmp_path):
    from pipeline.wiki_writer import write_or_append_page
    write_or_append_page(MOCK_PAGES[0], wiki_root=str(tmp_path), source_uuid="cap-2020")
    out = tmp_path / "initiatives" / "community-choice-aggregation.md"  # was commitments/
    assert out.exists()
    content = out.read_text()
    assert "Community Choice Aggregation" in content
    assert "---" in content


def test_write_or_append_page_appends_to_existing(tmp_path):
    from pipeline.wiki_writer import write_or_append_page
    write_or_append_page(MOCK_PAGES[0], wiki_root=str(tmp_path), source_uuid="cap-2020")
    original_path = tmp_path / "initiatives" / "community-choice-aggregation.md"  # was commitments/
    original_content = original_path.read_text()

    updated_spec = {**MOCK_PAGES[0], "body": "Additional context from year1 report."}
    write_or_append_page(updated_spec, wiki_root=str(tmp_path), source_uuid="a2zero-year1")

    new_content = original_path.read_text()
    assert "procure renewable electricity" in new_content
    assert "Additional context from year1" in new_content
    assert new_content.startswith(original_content[:50])
    assert "<!-- source: a2zero-year1 -->" in new_content


def test_write_or_append_page_frontmatter_is_valid_yaml(tmp_path):
    from pipeline.wiki_writer import write_or_append_page
    write_or_append_page(MOCK_PAGES[1], wiki_root=str(tmp_path), source_uuid="cap-2020")
    out = tmp_path / "actors" / "osi.md"
    content = out.read_text()
    parts = content.split("---\n")
    parsed = yaml.safe_load(parts[1])
    assert parsed["type"] == "actor"
    assert parsed["actor-type"] == "government-office"


# Update the LLM mock test — it asserts on the initiative path now:
@patch("pipeline.wiki_writer.anthropic.Anthropic")
def test_extract_wiki_pages_from_chunk_calls_llm(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=json.dumps(MOCK_PAGES))]
    mock_client.messages.create.return_value = mock_response

    from pipeline.wiki_writer import extract_wiki_pages_from_chunk
    pages = extract_wiki_pages_from_chunk(
        chunk_text=SAMPLE_CHUNK,
        source_uuid="cap-2020",
        silver_relative_path="silver/cap/cap-2020",
        context_header="[DOCUMENT CONTEXT]\nDocument: Test CAP\n[END CONTEXT]",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )
    assert mock_client.messages.create.called
    assert len(pages) == 2
    assert (tmp_path / "initiatives" / "community-choice-aggregation.md").exists()  # was commitments/
    assert (tmp_path / "actors" / "osi.md").exists()
```

- [ ] **Step 7: Run full extractor suite — expect all pass**

```bash
python -m pytest tests/test_wiki_extractor.py -v
```

Expected: All tests PASS (some may still fail on `silver_relative_path` — that's fixed in Task 3).

- [ ] **Step 8: Commit**

```bash
git add pipeline/silver_to_gold.py pipeline/wiki_writer.py tests/test_wiki_extractor.py
git commit -m "feat: remove commitment type, add plan type, remove strategy from Pass 3 forbidden list"
```

---

## Task 2: Add Strategy Slug Whitelist Guard

**Files:**
- Modify: `pipeline/wiki_writer.py` — `validate_page_spec()` and `extract_wiki_pages_from_chunk()`
- Modify: `tests/test_wiki_extractor.py` — add whitelist tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_wiki_extractor.py`:

```python
def test_validate_page_spec_rejects_unknown_strategy_slug():
    """A strategy slug not in the pre-existing set must be rejected."""
    from pipeline.wiki_writer import validate_page_spec
    spec = {
        "page_type": "strategy",
        "slug": "strategies/strategy-8-invented",
        "frontmatter": {"type": "strategy"},
        "body": "This strategy does not exist. ([[silver/cap/cap-2020|cap-2020]])",
    }
    allowed = frozenset({"strategies/strategy-1-renewable-grid",
                         "strategies/strategy-2-electrification"})
    errors = validate_page_spec(spec, allowed_strategy_slugs=allowed)
    assert any("strategy" in e and "not a pre-existing" in e for e in errors), (
        f"Expected whitelist error, got: {errors}"
    )


def test_validate_page_spec_accepts_known_strategy_slug():
    """A strategy slug in the pre-existing set must be accepted."""
    from pipeline.wiki_writer import validate_page_spec
    spec = {
        "page_type": "strategy",
        "slug": "strategies/strategy-1-renewable-grid",
        "frontmatter": {"type": "strategy"},
        "body": "Strategy 1 focuses on renewable energy. ([[silver/cap/cap-2020|cap-2020]])",
    }
    allowed = frozenset({"strategies/strategy-1-renewable-grid",
                         "strategies/strategy-2-electrification"})
    errors = validate_page_spec(spec, allowed_strategy_slugs=allowed)
    type_errors = [e for e in errors if "strategy" in e and "not a pre-existing" in e]
    assert type_errors == [], f"Unexpected whitelist error: {type_errors}"


def test_validate_page_spec_skips_whitelist_when_not_provided():
    """If allowed_strategy_slugs is None, skip the whitelist check (test mode)."""
    from pipeline.wiki_writer import validate_page_spec
    spec = {
        "page_type": "strategy",
        "slug": "strategies/strategy-99-unknown",
        "frontmatter": {"type": "strategy"},
        "body": "Some strategy content. ([[silver/cap/cap-2020|cap-2020]])",
    }
    errors = validate_page_spec(spec, allowed_strategy_slugs=None)
    type_errors = [e for e in errors if "not a pre-existing" in e]
    assert type_errors == [], f"Unexpected error with no whitelist: {type_errors}"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_wiki_extractor.py::test_validate_page_spec_rejects_unknown_strategy_slug \
    tests/test_wiki_extractor.py::test_validate_page_spec_accepts_known_strategy_slug \
    tests/test_wiki_extractor.py::test_validate_page_spec_skips_whitelist_when_not_provided \
    -v 2>&1 | head -30
```

Expected: FAIL — `validate_page_spec` doesn't accept `allowed_strategy_slugs` yet.

- [ ] **Step 3: Update validate_page_spec() in wiki_writer.py**

Replace the `validate_page_spec` function (lines 255-273):

```python
def validate_page_spec(
    spec: dict,
    allowed_strategy_slugs: frozenset[str] | None = None,
) -> list[str]:
    errors = []
    for field in ("page_type", "slug", "frontmatter", "body"):
        if field not in spec:
            errors.append(f"missing required field: {field}")
    if "body" in spec and not spec.get("body"):
        errors.append("body must not be empty")
    if "page_type" in spec:
        pt = spec["page_type"]
        if pt not in VALID_PAGE_TYPES:
            errors.append(
                f"invalid page_type: {pt!r} — must be one of {sorted(VALID_PAGE_TYPES)}"
            )
        elif pt in PASS3_FORBIDDEN_TYPES:
            errors.append(
                f"page_type {pt!r} is forbidden in Pass 3 — "
                f"these pages are created by a separate process"
            )
        elif pt == "strategy" and allowed_strategy_slugs is not None:
            slug = spec.get("slug", "")
            if slug not in allowed_strategy_slugs:
                errors.append(
                    f"strategy slug {slug!r} is not a pre-existing strategy stub — "
                    f"only these slugs are allowed: {sorted(allowed_strategy_slugs)}"
                )
    return errors
```

- [ ] **Step 4: Thread allowed_strategy_slugs through extract_wiki_pages_from_chunk()**

In `extract_wiki_pages_from_chunk()`, scan the strategy stubs once at the top and pass to `validate_page_spec()`. Replace the `written = []` loop section (lines 328-342):

```python
    # Build allowed strategy slugs from wiki_root/strategies/ for whitelist guard.
    strategy_dir = Path(wiki_root) / "strategies"
    allowed_strategy_slugs: frozenset[str] = frozenset(
        f"strategies/{p.stem}" for p in strategy_dir.glob("*.md")
    ) if strategy_dir.exists() else frozenset()

    written = []
    for spec in specs:
        errors = validate_page_spec(spec, allowed_strategy_slugs=allowed_strategy_slugs)
        if errors:
            print(
                f"[wiki_writer] WARNING: invalid page spec skipped: {errors} "
                f"— {spec.get('slug', '?')}"
            )
            continue
        try:
            write_or_append_page(spec, wiki_root=wiki_root, source_uuid=source_uuid)
            written.append(spec)
        except Exception as e:
            print(f"[wiki_writer] WARNING: failed to write page {spec.get('slug', '?')}: {e}")

    return written
```

- [ ] **Step 5: Run whitelist tests — expect pass**

```bash
python -m pytest tests/test_wiki_extractor.py::test_validate_page_spec_rejects_unknown_strategy_slug \
    tests/test_wiki_extractor.py::test_validate_page_spec_accepts_known_strategy_slug \
    tests/test_wiki_extractor.py::test_validate_page_spec_skips_whitelist_when_not_provided \
    tests/test_wiki_extractor.py -v
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/wiki_writer.py tests/test_wiki_extractor.py
git commit -m "feat: strategy slug whitelist guard in validate_page_spec"
```

---

## Task 3: Thread silver_relative_path Through Extraction Chain

The extraction chain needs to know the vault-relative path to the silver source file (e.g., `silver/cap/cap-2020`) so the LLM can construct `[[silver/cap/cap-2020|cap-2020]]` citations.

**Files:**
- Modify: `pipeline/wiki_writer.py` — `extract_wiki_pages_from_chunk()` signature
- Modify: `pipeline/ldp.py` — `extract_quads_chunked()` and `run_ldp_ingest()` signatures
- Modify: `pipeline/run_ingest.py` — `run_silver_ingest()` caller

- [ ] **Step 1: Add silver_relative_path to extract_wiki_pages_from_chunk()**

In `pipeline/wiki_writer.py`, update the function signature and prompt construction. Replace lines 295-312:

```python
def extract_wiki_pages_from_chunk(
    chunk_text: str,
    source_uuid: str,
    silver_relative_path: str,
    context_header: str,
    source_type: str,
    wiki_root: str,
    run_date: str,
) -> list[dict]:
    try:
        client = anthropic.Anthropic()
        prompt = (
            f"{context_header}\n\n"
            f"[SECTION CONTENT]\n{chunk_text}\n[END SECTION]\n\n"
            f"Source UUID: {source_uuid}\n"
            f"Silver path: {silver_relative_path}\n"
            f"Source type: {source_type}\n"
            f"Today's date: {run_date}"
        )
```

- [ ] **Step 2: Thread through ldp.py extract_quads_chunked()**

In `pipeline/ldp.py`, add `silver_relative_path` to `extract_quads_chunked()` signature and pass it to `extract_wiki_pages_from_chunk()`. Replace lines 180-188:

```python
def extract_quads_chunked(
    silver_content: str,
    section_map: dict,
    source_uuid: str,
    document_title: str,
    silver_relative_path: str,
    source_type: str = "cap",
    wiki_root: str = "wiki",
    run_date: str | None = None,
) -> tuple[list[dict], int]:
```

And in the body, update the `extract_wiki_pages_from_chunk` call (around line 239):

```python
        pages_written = extract_wiki_pages_from_chunk(
            chunk_text=chunk_text,
            source_uuid=source_uuid,
            silver_relative_path=silver_relative_path,
            context_header=context_header,
            source_type=source_type,
            wiki_root=wiki_root,
            run_date=run_date,
        )
```

- [ ] **Step 3: Thread through ldp.py run_ldp_ingest()**

In `pipeline/ldp.py`, add `silver_relative_path` to `run_ldp_ingest()` and pass to `extract_quads_chunked()`. Replace lines 252-260:

```python
def run_ldp_ingest(
    silver_content: str,
    uuid: str,
    title: str,
    quads_path: str,
    silver_relative_path: str,
    wiki_root: str = "wiki",
    source_type: str = "cap",
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
):
    """Full LDP pipeline: parse section map → chunked extraction → append quads."""
    section_map = parse_section_map(silver_content, uuid)
    save_section_map(section_map, section_maps_dir)
    print(f"[ldp] {uuid}: {len(section_map['sections'])} sections, "
          f"{len(get_chunks(section_map))} chunks to extract")
    quads, pages_written = extract_quads_chunked(
        silver_content=silver_content,
        section_map=section_map,
        source_uuid=uuid,
        document_title=title,
        silver_relative_path=silver_relative_path,
        source_type=source_type,
        wiki_root=wiki_root,
        run_date=run_date,
    )
    append_quads(quads, quads_path)
    print(f"[ldp] {uuid}: {len(quads)} quads, {pages_written} wiki pages written")
    return quads
```

- [ ] **Step 4: Thread through run_ingest.py run_silver_ingest()**

In `pipeline/run_ingest.py`, derive `silver_relative_path` from `silver_path` and pass to both branches. Replace `run_silver_ingest()` function:

```python
def run_silver_ingest(
    silver_path: str,
    uuid: str,
    title: str,
    quads_path: str,
    wiki_root: str,
    review_queue_path: str,
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
):
    """Ingest a pre-built Silver markdown file, auto-routing to LDP for long docs."""
    if run_date is None:
        run_date = date.today().isoformat()

    silver_content = Path(silver_path).read_text(encoding="utf-8")

    # Derive vault-relative path without extension for wikilink citations.
    # e.g. "silver/cap/cap-2020.md" → "silver/cap/cap-2020"
    silver_relative_path = str(Path(silver_path).with_suffix(""))

    # Extract source_type from frontmatter once, before routing.
    source_type = "unknown"
    m = re.match(r"^---\n(.*?)\n---\n", silver_content, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1))
            if fm:
                source_type = fm.get("source_type", "unknown")
        except Exception:
            pass

    if _should_use_ldp(silver_content):
        run_ldp_ingest(
            silver_content=silver_content,
            uuid=uuid,
            title=title,
            quads_path=quads_path,
            silver_relative_path=silver_relative_path,
            wiki_root=wiki_root,
            source_type=source_type,
            section_maps_dir=section_maps_dir,
            run_date=run_date,
        )
    else:
        extract_quads_from_silver(
            silver_content=silver_content,
            source_uuid=uuid,
            out_path=quads_path,
        )
        from pipeline.wiki_writer import extract_wiki_pages_from_chunk
        body = re.sub(r"^---\n.*?\n---\n", "", silver_content, flags=re.DOTALL).strip()
        extract_wiki_pages_from_chunk(
            chunk_text=body,
            source_uuid=uuid,
            silver_relative_path=silver_relative_path,
            context_header="",
            source_type=source_type,
            wiki_root=wiki_root,
            run_date=run_date,
        )

    report = run_post_ingest(
        quads_path=quads_path,
        source_uuid=uuid,
        out_path=review_queue_path,
        run_date=run_date,
    )
    print(f"[ingest] {uuid}: {report.total_quads} quads, "
          f"{len(report.schema_errors)} errors, "
          f"{len(report.dark_matter_ids)} dark matter")
    return report
```

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest tests/ -v 2>&1 | tail -30
```

Fix any remaining failures from the signature changes. The `test_ldp.py` mocks `extract_wiki_pages_from_chunk` — verify they still pass since the mock patches the function regardless of signature.

- [ ] **Step 6: Commit**

```bash
git add pipeline/wiki_writer.py pipeline/ldp.py pipeline/run_ingest.py
git commit -m "feat: thread silver_relative_path through extraction chain for wikilink citations"
```

---

## Task 4: Rewrite WIKI_PAGES_SYSTEM Prompt

This is the core behavioral change. The new prompt produces wikilinks everywhere, enforces the Plan→Strategy→Initiative hierarchy, and uses the correct citation format.

**Files:**
- Modify: `pipeline/wiki_writer.py` — replace `WIKI_PAGES_SYSTEM` constant (lines 24-243)

- [ ] **Step 1: Replace WIKI_PAGES_SYSTEM in wiki_writer.py**

Replace the entire `WIKI_PAGES_SYSTEM` constant (lines 24-243) with:

```python
WIKI_PAGES_SYSTEM = """You are a wiki page generator for the A2Zero climate wiki.
You receive one section of an A2Zero source document and generate wiki page specs
for entities mentioned in the section.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEVER CREATE these page types:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- type: plan      — extracted by a dedicated first-pass call before chunking. Never create.
- type: topic     — declared manually by the research team. Never create.
- type: mechanism — requires evidence from ≥2 independent sources. Never create per-chunk.
- type: synthesis — generated by post-ingest pipeline. Never create during extraction.
- type: commitment — this type is eliminated. Use "initiative" for all CAP actions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WIKILINK FORMAT — mandatory everywhere:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All entity references MUST use Obsidian wikilink format.
The "Silver path" in the user message gives the vault-relative path for citations.

  Single frontmatter value:    "[[actors/osi]]"
  Frontmatter list item:       "[[actors/osi]]"  ← each list item is a quoted wikilink string
  Body first mention:          [[actors/osi|Office of Sustainability and Innovations]]
  Body later mentions:         [[actors/osi|OSI]]
  Source citation (REQUIRED):  ([[silver/cap/cap-2020|cap-2020]])

CITATIONS: Every factual sentence in "body" must end with a source citation:
  ([[{silver_path}|{source_uuid}]])
Replace {silver_path} and {source_uuid} with the values from the user message.
Exceptions: transitional sentences, section headers, cross-references to other wiki pages.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A2ZERO HIERARCHY — use to assign parent-strategy:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[[strategies/strategy-1-renewable-grid]] — 100% Renewable Energy Grid
  Includes: CCA, Landfill Solar, Community Solar, Onsite Renewables Bulk Buy

[[strategies/strategy-2-electrification]] — Building Electrification
  Includes: heat pump programs, appliance electrification, EV fleet, building fuel switching

[[strategies/strategy-3-building-efficiency]] — Building Energy Efficiency
  Includes: weatherization, energy audits, efficiency retrofits, building standards

[[strategies/strategy-4-vmt-reduction]] — Vehicle Miles Traveled Reduction
  Includes: transit expansion, non-motorized transport, parking reform, mixed-use development

[[strategies/strategy-5-materials-waste]] — Materials & Waste
  Includes: zero waste plan, composting, recycling expansion, circular economy, food waste

[[strategies/strategy-6-resilience]] — Community Resilience
  Includes: Resilience Hubs, emergency preparedness, environmental monitoring, tree canopy

[[strategies/strategy-7-engagement]] — Community Engagement & Equity
  Includes: Equity Program, Sustaining Ann Arbor Together grants, Carbon Offsets, Internal Carbon Price

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UNIVERSAL RULES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Extract ONLY what the text explicitly states — never invent details
- Slugify names: lowercase, hyphens for spaces, drop special chars
  "Office of Sustainability and Innovations" → "office-of-sustainability-and-innovations"
  Use acronym when it IS the canonical name: "OSI" → "osi", "DTE Energy" → "dte-energy"
- One page spec per entity — do not create the same entity twice in one response
- Return [] if no qualifying entities are found in this section

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PAGE TYPES TO CREATE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. STRATEGY — one of the 7 pre-existing A2Zero strategy pages. Append context only.
   ONLY create a strategy spec if this section explicitly describes a strategy's goal or actions.
   The slug MUST exactly match one of the 7 slugs listed above — no other strategy slugs exist.
   Slug: "strategies/{exact-pre-existing-slug}"
   Frontmatter:
     type: strategy
     title: (exact strategy title from source)
     strategy-number: (integer 1-7)
     parent-plan: "[[plans/cap-2020]]"
     goal: (1-sentence goal statement for this strategy, from source)
     initiatives: ["[[initiatives/slug1]]", "[[initiatives/slug2]]"]
     source-first-seen: "[[{silver_path}]]"
     tags: [3-5 keywords]
     last-updated: (today's date YYYY-MM-DD)

2. INITIATIVE — a named, bounded program or project. THIS REPLACES "commitment".
   Every numbered CAP Action (### heading) MUST become an initiative page.
   Every annual report "Next Steps" item becomes an initiative page.
   Do NOT create for passing mentions or unnamed policy considerations.
   Slug: "initiatives/{kebab-program-name}"
   Frontmatter:
     type: initiative
     title: (program name)
     parent-strategy: "[[strategies/{slug}]]"
     related-strategies: ["[[strategies/{slug}]]"]
     party-responsible: "[[actors/{slug}]]"
     partners: ["[[actors/{slug}]]"]
     status: (planned | committed | active | complete | abandoned | unknown)
     launched: (year as integer, or null)
     locations: ["[[locations/{slug}]]"]
     funding-events: ["[[funding-events/{slug}]]"]
     milestones:
       - year: (integer)
         target: (string describing the milestone — extract from timelines or "Next Steps")
         status: unverified
         source: "[[{silver_path}]]"
     source-first-seen: "[[{silver_path}]]"
     tags: [3-6 keywords]
     last-updated: (today's date YYYY-MM-DD)

3. ACTOR — a person or organization with a named role in A2Zero.
   Create only when a clear role is described. Do NOT create for passing mentions.
   Slug: "actors/{kebab-name}"
   Frontmatter:
     type: actor
     title: (full name)
     actor-type: (person | government-office | nonprofit | utility | university | funder | company)
     role: (their role in A2Zero, one phrase)
     affiliation: "[[actors/{parent-org-slug}]]"
     elected: (true | false | null)
     active-years: [list of integer years, or []]
     programs-involved: ["[[initiatives/{slug}]]"]
     tags: [3-5 keywords]
     source-first-seen: "[[{silver_path}]]"
     last-updated: (today's date YYYY-MM-DD)

4. FUNDING-EVENT — a specific dollar allocation with named source AND recipient.
   Create only when both amount AND funding source are explicitly stated.
   Slug: "funding-events/{kebab-fund-name-year}"
   Frontmatter:
     type: funding-event
     title: (fund name including org and year)
     date: (YYYY or YYYY-MM)
     amount: (integer in dollars)
     currency: USD
     fund-type: (federal-grant | state-grant | local-millage | philanthropic-grant | utility-program | federal-incentive | budget-allocation)
     funder: "[[actors/{slug}]]"
     recipient: "[[actors/{slug}]]"
     funds-initiatives: ["[[initiatives/{slug}]]"]
     status: (announced | awarded | disbursed | completed | terminated | on-hold)
     transferable: (true | false)
     tags: [3-5 keywords]
     source-first-seen: "[[{silver_path}]]"
     last-updated: (today's date YYYY-MM-DD)

5. TECHNOLOGY — a technology type Ann Arbor is deploying in A2Zero programs.
   Create when barriers, costs, or deployment details are documented — not for passing mentions.
   Create only for actual technical systems (solar PV, heat pumps, battery storage, EVs).
   Do NOT create for policy mechanisms like Community Choice Aggregation — that is an initiative.
   Slug: "technology/{kebab-tech-common-name}"
   Frontmatter:
     type: technology
     title: (full technology name)
     common-name: (short common name, e.g. "geothermal" | "heat-pump" | "solar-pv")
     tech-type: (heating-cooling | solar | storage | efficiency | grid | ev | building-envelope | other)
     a2zero-context: (1-sentence describing how Ann Arbor uses this technology)
     initiatives: ["[[initiatives/{slug}]]"]
     locations: ["[[locations/{slug}]]"]
     deployment-status: (planned | in-progress | operational | completed | abandoned)
     cost-context: (string summarizing known costs, or null)
     barriers-encountered: [list of barrier keyword strings, or []]
     transferability: (high | medium | low)
     tags: [3-6 keywords]
     source-first-seen: "[[{silver_path}]]"
     last-updated: (today's date YYYY-MM-DD)

6. LOCATION — a specific named site of A2Zero program activity.
   Create when a location is named as a site of initiative activity, not just mentioned in passing.
   Slug: "locations/{kebab-location-name}"
   Frontmatter:
     type: location
     title: (full location name)
     location-type: (county | city | neighborhood | park | facility | infrastructure | district | school)
     parent-location: "[[locations/{slug}]]"
     owned-by: (city | county | nonprofit | university | school-district | private | null)
     initiatives: ["[[initiatives/{slug}]]"]
     tags: [3-5 keywords]
     source-first-seen: "[[{silver_path}]]"
     last-updated: (today's date YYYY-MM-DD)

7. CONTRADICTION — conflicting claims about the same fact, broadly interpreted.
   Create when numbers, dates, status claims, targets, costs, or actor roles conflict within or
   across sources. Do NOT silently resolve conflicts — surface them here for human review.
   Slug: "contradictions/{kebab-brief-description}"
   Frontmatter:
     type: contradiction
     title: (brief description of the conflict)
     sources: ["[[{silver_path}]]"]
     cross-source: (true if conflict spans different source documents; false if within same source)
     status: unresolved
     related-initiatives: ["[[initiatives/{slug}]]"]
     tags: [3-5 keywords]
     source-first-seen: "[[{silver_path}]]"
     last-updated: (today's date YYYY-MM-DD)
   Body: document both conflicting claims side by side, each ending with a citation.

8. MEETING — a deliberative body meeting where A2Zero items were discussed.
   Distinguish from POLITICAL-EVENT: MEETING = where debate happened; POLITICAL-EVENT = the outcome.
   For significant votes, create BOTH a meeting page AND a political-event page.
   Slug: "meetings/YYYY-MM-DD-{body-slug}"
   Frontmatter:
     type: meeting
     title: "{Body} — {YYYY-MM-DD} ({brief A2Zero topic})"
     date: (YYYY-MM-DD)
     body: (city-council | sustainability-commission | planning-commission | other)
     source-uuid: (source UUID string — not a wikilink)
     agenda-items: ["[[initiatives/{slug}]]"]
     decisions: [list of decision strings, or []]
     actors: ["[[actors/{slug}]]"]
     tags: [3-5 keywords]
     source-first-seen: "[[{silver_path}]]"
     last-updated: (today's date YYYY-MM-DD)

9. FRAMING — how an A2Zero issue is deliberately talked about by stakeholders.
   Create only for named framing strategies with documented strategic intent — not every
   communications mention. The framing must be deliberate and politically significant.
   Slug: "framing/{kebab-framing-title}"
   Frontmatter:
     type: framing
     title: (descriptive framing title)
     initiative: "[[initiatives/{slug}]]"
     period: (YYYY-YYYY or YYYY)
     actors: ["[[actors/{slug}]]"]
     audiences: [list of audience strings]
     evolution: (true | false)
     tags: [3-5 keywords]
     source-first-seen: "[[{silver_path}]]"
     last-updated: (today's date YYYY-MM-DD)

10. POLITICAL-EVENT — a discrete political outcome with lasting legal or political effect.
    Create for council resolutions, referendums, elections, key appointments.
    Slug: "political-events/YYYY-MM-DD-{slug}"
    Frontmatter:
      type: political-event
      title: (descriptive title including body and outcome)
      date: (YYYY-MM-DD)
      event-type: (referendum | council-resolution | election | appointment | legal-ruling | regulatory-decision)
      outcome: (passed | failed | approved | rejected | appointed | other)
      margin: (vote margin string, or null)
      legal-effect: (1-sentence description of what this authorizes or prohibits, or null)
      programs-authorized: ["[[initiatives/{slug}]]"]
      actors: ["[[actors/{slug}]]"]
      tags: [3-5 keywords]
      source-first-seen: "[[{silver_path}]]"
      last-updated: (today's date YYYY-MM-DD)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT SCHEMA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every element of the returned JSON array must have exactly these four keys:
{
  "page_type": "<one of the 10 types above>",
  "slug": "<category/kebab-name>",
  "frontmatter": { <required fields per type; all entity refs as "[[wikilinks]]"> },
  "body": "<2-4 factual sentences; every factual sentence ends with ([[silver/path|uuid]])>"
}
Return ONLY the JSON array. No prose, no markdown fence, no explanation."""
```

- [ ] **Step 2: Run the full test suite**

```bash
python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: All tests PASS. The prompt is a constant — no tests break from this change.

- [ ] **Step 3: Commit**

```bash
git add pipeline/wiki_writer.py
git commit -m "feat: rewrite WIKI_PAGES_SYSTEM with wikilinks, hierarchy, initiative replaces commitment"
```

---

## Task 5: Create pipeline/plan_extractor.py

**Files:**
- Create: `pipeline/plan_extractor.py`
- Create: `tests/test_plan_extractor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_plan_extractor.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

MOCK_PLAN_RESPONSE = {
    "page_type": "plan",
    "slug": "plans/cap-2020",
    "frontmatter": {
        "type": "plan",
        "title": "Ann Arbor A2Zero Living Carbon Neutrality Plan",
        "published": "2020-04",
        "jurisdiction": "ann-arbor",
        "source": "[[silver/cap/cap-2020]]",
        "overarching-goal": "Achieve community-wide carbon neutrality by 2030.",
        "party-responsible": "[[actors/osi]]",
        "strategies": [
            "[[strategies/strategy-1-renewable-grid]]",
            "[[strategies/strategy-2-electrification]]",
            "[[strategies/strategy-3-building-efficiency]]",
            "[[strategies/strategy-4-vmt-reduction]]",
            "[[strategies/strategy-5-materials-waste]]",
            "[[strategies/strategy-6-resilience]]",
            "[[strategies/strategy-7-engagement]]",
        ],
        "tags": ["carbon-neutrality", "cap", "2030", "a2zero"],
        "last-updated": "2026-06-23",
    },
    "body": "The A2Zero Living Carbon Neutrality Plan commits Ann Arbor to achieving community-wide carbon neutrality by 2030. ([[silver/cap/cap-2020|cap-2020]])",
}

SAMPLE_SILVER = """---
source_type: cap
---

# Ann Arbor A2Zero Living Carbon Neutrality Plan

Ann Arbor commits to achieving carbon neutrality by 2030.

## Introduction

This is the plan.
"""


@patch("pipeline.plan_extractor.anthropic.Anthropic")
def test_extract_plan_page_writes_file(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=json.dumps(MOCK_PLAN_RESPONSE))]
    mock_client.messages.create.return_value = mock_response

    from pipeline.plan_extractor import extract_plan_page
    result = extract_plan_page(
        silver_content=SAMPLE_SILVER,
        source_uuid="cap-2020",
        silver_relative_path="silver/cap/cap-2020",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is not None
    assert result["page_type"] == "plan"
    plan_file = tmp_path / "plans" / "cap-2020.md"
    assert plan_file.exists()
    content = plan_file.read_text()
    assert "type: plan" in content
    assert "A2Zero Living Carbon Neutrality Plan" in content
    assert "[[silver/cap/cap-2020]]" in content


@patch("pipeline.plan_extractor.anthropic.Anthropic")
def test_extract_plan_page_skips_if_exists(mock_anthropic_class, tmp_path):
    """Plan extractor is idempotent — skip if plan page already exists."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client

    # Pre-create the plan file
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "cap-2020.md").write_text("---\ntype: plan\n---\n\nExisting plan.\n")

    from pipeline.plan_extractor import extract_plan_page
    result = extract_plan_page(
        silver_content=SAMPLE_SILVER,
        source_uuid="cap-2020",
        silver_relative_path="silver/cap/cap-2020",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is None
    assert not mock_client.messages.create.called


@patch("pipeline.plan_extractor.anthropic.Anthropic")
def test_extract_plan_page_returns_none_on_api_failure(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API error")

    from pipeline.plan_extractor import extract_plan_page
    result = extract_plan_page(
        silver_content=SAMPLE_SILVER,
        source_uuid="cap-2020",
        silver_relative_path="silver/cap/cap-2020",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )
    assert result is None


@patch("pipeline.plan_extractor.anthropic.Anthropic")
def test_extract_plan_page_rejects_wrong_type(mock_anthropic_class, tmp_path):
    """If LLM returns wrong page_type, return None without writing file."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    wrong_response = {**MOCK_PLAN_RESPONSE, "page_type": "initiative"}
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=json.dumps(wrong_response))]
    mock_client.messages.create.return_value = mock_response

    from pipeline.plan_extractor import extract_plan_page
    result = extract_plan_page(
        silver_content=SAMPLE_SILVER,
        source_uuid="cap-2020",
        silver_relative_path="silver/cap/cap-2020",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )
    assert result is None
    assert not (tmp_path / "plans" / "cap-2020.md").exists()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_plan_extractor.py -v 2>&1 | head -20
```

Expected: FAIL — `pipeline.plan_extractor` does not exist yet.

- [ ] **Step 3: Create pipeline/plan_extractor.py**

```python
import anthropic
import json
import re
from pathlib import Path
from pipeline.silver_to_gold import build_wiki_page, write_wiki_page

PLAN_EXTRACTION_SYSTEM = """You are a wiki page generator for the A2Zero climate wiki.
You receive the introductory section of a strategic planning document and generate
a single "plan" wiki page spec as a JSON object.

WIKILINK FORMAT — use everywhere:
- Source citation: ([[{silver_path}|{source_uuid}]])  ← replace with values from user message
- Entity refs: "[[actors/osi]]", "[[strategies/strategy-1-renewable-grid]]"

A2ZERO STRATEGY SLUGS (use exactly these in the strategies list):
  [[strategies/strategy-1-renewable-grid]]
  [[strategies/strategy-2-electrification]]
  [[strategies/strategy-3-building-efficiency]]
  [[strategies/strategy-4-vmt-reduction]]
  [[strategies/strategy-5-materials-waste]]
  [[strategies/strategy-6-resilience]]
  [[strategies/strategy-7-engagement]]

OUTPUT: Return a single JSON object with exactly these four keys:
{
  "page_type": "plan",
  "slug": "plans/{source_uuid}",
  "frontmatter": {
    "type": "plan",
    "title": "(exact document title)",
    "published": "(YYYY-MM or YYYY)",
    "jurisdiction": "(city or region slug, e.g. 'ann-arbor')",
    "source": "[[{silver_relative_path}]]",
    "overarching-goal": "(1-sentence goal statement from the document)",
    "party-responsible": "[[actors/{slug}]]",
    "strategies": ["[[strategies/strategy-1-renewable-grid]]", ... all 7],
    "tags": [3-6 keywords],
    "last-updated": "(today's date YYYY-MM-DD)"
  },
  "body": "4-6 sentences covering: what this plan is and its goal, how it was created, who is responsible, and its core structure. Every factual sentence ends with ([[{silver_path}|{source_uuid}]])."
}
Return ONLY the JSON object. No prose, no markdown fence, no explanation."""

# Number of body lines to send for plan extraction — enough to cover the intro section.
_PLAN_INTRO_LINES = 200


def extract_plan_page(
    silver_content: str,
    source_uuid: str,
    silver_relative_path: str,
    wiki_root: str,
    run_date: str,
) -> dict | None:
    """Extract a plan page from the intro section of a silver document.

    Idempotent: returns None without calling the API if the plan page already exists.
    Returns the page spec dict on success, None on failure or skip.
    """
    plan_slug = f"plans/{source_uuid}"
    plan_path = Path(wiki_root) / (plan_slug + ".md")
    if plan_path.exists():
        print(f"[plan_extractor] Plan page already exists: {plan_path} — skipping")
        return None

    # Strip frontmatter and take first N lines of body for the intro.
    body = re.sub(r"^---\n.*?\n---\n", "", silver_content, flags=re.DOTALL).strip()
    intro = "\n".join(body.splitlines()[:_PLAN_INTRO_LINES])

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            temperature=0,
            system=PLAN_EXTRACTION_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Source UUID: {source_uuid}\n"
                    f"Silver path: {silver_relative_path}\n"
                    f"Today's date: {run_date}\n\n"
                    f"[DOCUMENT INTRO]\n{intro}\n[END INTRO]"
                ),
            }],
        )
    except Exception as e:
        print(f"[plan_extractor] WARNING: plan extraction failed for {source_uuid}: {e}")
        return None

    raw = response.content[0].text
    cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        spec = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[plan_extractor] WARNING: invalid JSON from LLM for {source_uuid}: {e}")
        return None

    if spec.get("page_type") != "plan":
        print(
            f"[plan_extractor] WARNING: expected page_type 'plan', "
            f"got {spec.get('page_type')!r} — skipping"
        )
        return None

    try:
        page = build_wiki_page(
            page_type="plan",
            slug=plan_slug,
            frontmatter=spec["frontmatter"],
            body=spec["body"],
        )
        write_wiki_page(page, wiki_root=wiki_root, exist_ok=False)
        print(f"[plan_extractor] Plan page written: {plan_path}")
    except Exception as e:
        print(f"[plan_extractor] WARNING: failed to write plan page: {e}")
        return None

    return spec
```

- [ ] **Step 4: Run plan extractor tests — expect pass**

```bash
python -m pytest tests/test_plan_extractor.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/plan_extractor.py tests/test_plan_extractor.py
git commit -m "feat: plan_extractor.py — dedicated first-pass plan page extraction"
```

---

## Task 6: Wire Plan Extractor into run_ingest.py

**Files:**
- Modify: `pipeline/run_ingest.py`

- [ ] **Step 1: Add the plan extractor call before routing**

In `pipeline/run_ingest.py`, import and call `extract_plan_page` before the LDP/short-doc routing in `run_silver_ingest()`. Add the import at the top of the file:

```python
from pipeline.plan_extractor import extract_plan_page
```

Then in `run_silver_ingest()`, add the plan extraction call immediately after `silver_relative_path` is set (before the `_should_use_ldp` check):

```python
    # Derive vault-relative path without extension for wikilink citations.
    silver_relative_path = str(Path(silver_path).with_suffix(""))

    # First pass: extract plan page (idempotent — skips if already exists).
    extract_plan_page(
        silver_content=silver_content,
        source_uuid=uuid,
        silver_relative_path=silver_relative_path,
        wiki_root=wiki_root,
        run_date=run_date,
    )

    # Extract source_type from frontmatter once, before routing.
    source_type = "unknown"
    ...
```

- [ ] **Step 2: Verify run_ingest tests still pass**

```bash
python -m pytest tests/test_run_ingest.py -v
```

Expected: PASS. The plan extractor call is fire-and-forget (returns None on skip or failure).

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add pipeline/run_ingest.py
git commit -m "feat: wire plan_extractor into run_silver_ingest before chunk loop"
```

---

## Task 7: Final Test Suite Pass

- [ ] **Step 1: Run the complete test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1
```

Expected output should end with something like:
```
===================== N passed in Xs ======================
```

- [ ] **Step 2: Fix any remaining failures**

If any tests fail, read the error output and fix the root cause. Common issues:
- Mock patch paths updated — verify `@patch("pipeline.wiki_writer.anthropic.Anthropic")` paths are still correct after the signature changes
- `test_ldp.py` mocks `extract_wiki_pages_from_chunk` — verify the mock still works with the new `silver_relative_path` parameter (mocks patch the function, so the parameter is ignored in test)

- [ ] **Step 3: Commit final fixes**

```bash
git add -p  # stage only test fixes
git commit -m "fix: update test mocks after silver_relative_path parameter addition"
```

---

## Task 8: Archive Wiki and Re-Ingest

- [ ] **Step 1: Run the pre-task archive commands** (from top of plan)

```bash
mkdir -p archive/wiki-v2-ingest-1
cp -r wiki/actors wiki/commitments wiki/initiatives wiki/technology \
      wiki/locations wiki/meetings wiki/political-events \
      wiki/contradictions wiki/funding-events \
      archive/wiki-v2-ingest-1/ 2>/dev/null || true
rm -rf wiki/actors wiki/commitments wiki/initiatives wiki/technology \
       wiki/locations wiki/meetings wiki/political-events \
       wiki/contradictions wiki/funding-events
mkdir -p wiki/plans
```

- [ ] **Step 2: Re-ingest the CAP**

```bash
ANTHROPIC_API_KEY=<your-key> python -m pipeline.run_ingest silver \
  --silver silver/cap/cap-2020.md \
  --uuid cap-2020 \
  --title "Ann Arbor A2Zero Living Carbon Neutrality Plan" \
  --quads-path blackboard/quads.jsonl \
  --wiki-root wiki \
  --review-queue review-queue.md \
  --section-maps-dir blackboard/section_maps
```

- [ ] **Step 3: Spot-check output**

Verify the following in the Obsidian vault graph view and file system:

```bash
# Plan page exists
ls wiki/plans/

# Strategy pages have content (not just the stub comment)
grep -l "goal:" wiki/strategies/*.md

# Initiative pages replaced commitments
ls wiki/initiatives/ | head -10

# No commitments directory
ls wiki/commitments/ 2>/dev/null && echo "ERROR: commitments dir still exists" || echo "OK"

# Wikilinks present in a sample initiative
grep "\[\[" wiki/initiatives/$(ls wiki/initiatives/ | head -1)

# Source citation format in body
grep "silver/cap" wiki/initiatives/$(ls wiki/initiatives/ | head -1)
```

- [ ] **Step 4: Commit the re-ingest output**

```bash
git add wiki/ blackboard/ review-queue.md
git commit -m "ingest: cap-2020 re-ingest with V2 schema — wikilinks, hierarchy, plan page"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| Wikilinks everywhere in frontmatter and body | Task 4 |
| Citations point to silver files (`[[silver/...]]`) | Tasks 3 + 4 |
| Plan → Strategy → Initiative hierarchy | Task 4 (prompt) |
| `commitment` type removed | Task 1 |
| `plan` type added | Tasks 1 + 5 |
| `strategy` allowed (whitelist guard) | Tasks 1 + 2 |
| `party-responsible` + `partners` distinction | Task 4 |
| `milestones:` field on initiatives | Task 4 |
| `plan_extractor.py` first-pass call | Task 5 |
| Plan extractor wired before chunk loop | Task 6 |
| Technology ≠ policy mechanism note | Task 4 |
| Contradiction broadly interpreted | Task 4 |
| `funding-events/` slug prefix (not `funding/`) | Task 4 |
| `silver_relative_path` threaded through | Task 3 |

**No placeholders found** — all code blocks are complete.

**Type consistency:** `silver_relative_path` parameter name is consistent across `extract_wiki_pages_from_chunk`, `extract_quads_chunked`, `run_ldp_ingest`, `run_silver_ingest`, and `extract_plan_page`.
