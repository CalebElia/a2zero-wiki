# A2Zero Wiki V3 — Holistic Pipeline Redesign

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the wiki pipeline from chunked-extraction-first to a holistic-read-first three-pass architecture matching the canonical Karpathy LLM-wiki pattern, adding mandatory index.md / log.md infrastructure and strict output validation before any disk write.

**Architecture:** Pass 1 (holistic synthesizer) reads the entire source document and writes one overview page + all 7 strategy synthesis bodies + seeds wiki/index.md and wiki/log.md. Pass 2 (chunked extraction, conditional on document complexity) extracts leaf-node pages — initiatives, actors, locations — and appends to index.md. Pass 3 (finalization) rebuilds index.md from all existing pages and seals the log entry. The `silver/` folder is renamed `sources/` throughout the vault so wikilink citations are semantically self-documenting.

**Tech Stack:** Python 3.11+, anthropic SDK (claude-sonnet-4-6), PyYAML, pathlib, pytest. No new dependencies.

---

## Amendments (2026-06-24 — from discovery interview)

Three design decisions were added after a structured discovery interview. These amendments are integrated directly into the relevant tasks below.

### Amendment A — Read-Understand-Integrate model (all pages)

**The principle:** the wiki is a living encyclopedia. Every write to an existing page is an integration pass, not an append. This applies to **all page types**: strategy pages (Pass 1) and initiative, actor, location, framing, and all other pages (Pass 2).

**Problem:** the original plan wrote strategy bodies with `append_to_wiki_page()`. For the first source this is correct. For the second and subsequent sources (annual reports, news), it produced the v2 failure: four near-identical paragraphs accumulated from blind appending. The same failure would occur for any page type without this principle enforced.

**Pass 1 solution (strategy pages):** `synthesize_source()` reads existing strategy page bodies before calling the Writer. They are passed as `[EXISTING STRATEGY WIKI CONTENT]` in the document block. The Writer and Editor are instructed to integrate, not append. `_write_synthesis()` detects whether a strategy page already has real content (beyond the initial stub comment); if it does, it calls `_replace_wiki_page_body()` rather than `append_to_wiki_page()`.

**Pass 2 solution (all other pages):** when the chunk extraction LLM produces content for an entity whose page already has content, the existing page body is included in the chunk context header. The `WIKI_PAGES_SYSTEM` prompt instructs the LLM to produce integrated body content for those entities. `write_wiki_page` calls `_replace_wiki_page_body()` rather than appending when content already exists.

The term is **read-understand-integrate**, not rewrite. "Integrate" preserves existing structure and facts while adding new depth. "Rewrite" implies permission to tear down.

**Files changed:** Task 3 (`holistic_synthesizer.py` — `synthesize_source`, `_write_synthesis`, new `_replace_wiki_page_body` helper; `HOLISTIC_WRITER_SYSTEM` prompt; test suite). Task 4 (`wiki_writer.py` — `WIKI_PAGES_SYSTEM` prompt; `extract_wiki_pages_from_chunk` context header; `write_wiki_page` integration behavior).

### Amendment B — `projections:` and `outcomes:` frontmatter

**Problem:** a projection ("22% GHG reduction by 2030" from the CAP) and a measured outcome ("6.8% reduction as of 2023" from Year 3 Annual Report) were both buried in prose, indistinguishable to a querying LLM or dashboard extraction call.

**Solution:** initiative and strategy pages get structured `projections:` and `outcomes:` YAML lists. Each entry: `{value, date, source}`. New ingests append entries; nothing is overwritten. The narrative body provides synthesis; the frontmatter lists enable machine-readable trajectory extraction for dashboard cards and funder queries.

**Files changed:** `HOLISTIC_WRITER_SYSTEM` prompt (extract projections from planning sources); stub creation in `_write_synthesis` (initialize empty lists); SCHEMA.md (updated YAML examples and rules).

### Amendment C — `framing` type formally defined

**Problem:** `framing` was listed in `VALID_PAGE_TYPES` and `WIKI_PAGES_SYSTEM` but had no specification. Communications strategy, advocacy coalition behavior, and messaging approach are first-class information for the Advocates audience.

**Solution:** `framing` is now fully defined in SCHEMA.md with frontmatter spec and body guidance. No code changes required — the type was already approved in Pass 2. The prompt already allows it. The definition ensures LLMs know when to use it and what to put in it.

**Files changed:** SCHEMA.md only.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Rename** | `silver/` → `sources/` | Immutable source documents (CAP, annual reports, transcripts) |
| **Create** | `pipeline/wiki_index.py` | index.md / log.md / hot.md read-write helpers |
| **Create** | `pipeline/holistic_synthesizer.py` | Pass 1 — full-document holistic read and synthesis |
| **Create** | `tests/test_wiki_index.py` | Tests for wiki_index.py |
| **Create** | `tests/test_holistic_synthesizer.py` | Tests for holistic_synthesizer.py |
| **Modify** | `pipeline/silver_to_gold.py` | Add "overview" to VALID_PAGE_TYPES; remove "plan" |
| **Modify** | `pipeline/wiki_writer.py` | Rename PASS3_FORBIDDEN → PASS2_FORBIDDEN; add "strategy"+"overview"; add schema-drift logging; rename Silver path → Source path in prompt; remove strategy slug whitelist |
| **Modify** | `pipeline/ldp.py` | Rename `silver_relative_path` → `source_rel_path` throughout |
| **Modify** | `pipeline/run_ingest.py` | Three-pass orchestration; rename `silver_path` → `source_path`; remove plan_extractor import |
| **Delete** | `pipeline/plan_extractor.py` | Replaced by holistic_synthesizer.py |
| **Delete** | `tests/test_plan_extractor.py` | Replaced by test_holistic_synthesizer.py |

---

## Task 1: Rename `silver/` → `sources/` throughout

**Files:**
- Rename: `silver/` directory → `sources/`
- Modify: `pipeline/run_ingest.py`
- Modify: `pipeline/ldp.py`
- Modify: `pipeline/wiki_writer.py`
- Modify: all `wiki/**/*.md` files with `[[silver/` references
- Modify: `tests/test_wiki_extractor.py`, `tests/test_ldp.py`, `tests/test_run_ingest.py`

- [ ] **Step 1: Rename the folder on disk**

```bash
mv silver sources
```

Verify:
```bash
ls sources/cap/
# Expected: cap-2020.md
```

- [ ] **Step 1b: Rename `bronze/` → `raw/` and `bronze_to_silver.py` → `raw_to_sources.py`**

```bash
mv bronze raw
mv pipeline/bronze_to_silver.py pipeline/raw_to_sources.py
mv tests/test_bronze_to_silver.py tests/test_raw_to_sources.py
```

Verify:
```bash
ls raw/
ls pipeline/raw_to_sources.py tests/test_raw_to_sources.py
# Expected: both files exist at new paths
```

- [ ] **Step 1c: Update module internals in `pipeline/raw_to_sources.py`**

Change all internal references from `bronze` to `raw`:

```python
# Old parameter name and frontmatter field:
def build_frontmatter(..., bronze_path: str, ...):
    return { ..., "bronze_path": bronze_path, ... }

# New:
def build_frontmatter(..., raw_path: str, ...):
    return { ..., "raw_path": raw_path, ... }
```

Also update the `convert_annual_report` function: rename the `bronze_path=` kwarg to `raw_path=` everywhere inside `raw_to_sources.py`.

- [ ] **Step 1d: Update `pipeline/run_ingest.py` — module import and parameter**

```python
# Old:
from pipeline.bronze_to_silver import convert_annual_report

# New:
from pipeline.raw_to_sources import convert_annual_report
```

If `run_ingest.py` passes `bronze_path=` anywhere, rename to `raw_path=`.

- [ ] **Step 1e: Update `tests/test_raw_to_sources.py` — paths and field names**

```python
# Old:
from pipeline.bronze_to_silver import write_silver, build_frontmatter
...
bronze_path="bronze/annual-reports/a2zero-year1.pdf"
...
assert fm["bronze_path"] == "bronze/annual-reports/a2zero-year1.pdf"

# New:
from pipeline.raw_to_sources import write_silver, build_frontmatter
...
raw_path="raw/annual-reports/a2zero-year1.pdf"
...
assert fm["raw_path"] == "raw/annual-reports/a2zero-year1.pdf"
```

Update all `bronze/` path strings and `bronze_path` field assertions throughout the test file.

- [ ] **Step 1f: Update `tests/fixtures/sample_annual_report.md` frontmatter**

```yaml
# Old:
bronze_path: "bronze/annual-reports/test-year1.pdf"

# New:
raw_path: "raw/annual-reports/test-year1.pdf"
```

- [ ] **Step 1g: Update `tests/test_run_ingest.py` — import and path strings**

```python
# Old:
@patch("pipeline.bronze_to_silver.extract_pdf_text", ...)
import pipeline.bronze_to_silver as b2s
pdf_path="bronze/annual-reports/a2zero-year1.pdf"

# New:
@patch("pipeline.raw_to_sources.extract_pdf_text", ...)
import pipeline.raw_to_sources as rts
pdf_path="raw/annual-reports/a2zero-year1.pdf"
```

- [ ] **Step 2: Update the frontmatter inside source files**

The `silver_path:` field in `sources/cap/cap-2020.md` frontmatter should read `sources/cap/cap-2020.md`:

```bash
sed -i '' 's|silver_path: "silver/|silver_path: "sources/|g' sources/cap/cap-2020.md
sed -i '' 's|silver_path: "silver/|silver_path: "sources/|g' sources/annual-reports/*.md 2>/dev/null || true
```

- [ ] **Step 3: Update `pipeline/run_ingest.py` — rename parameter and path logic**

In `run_silver_ingest()`, change the parameter name and derived path:
```python
# Old:
def run_silver_ingest(
    silver_path: str,
    ...
):
    silver_content = Path(silver_path).read_text(encoding="utf-8")
    silver_relative_path = str(Path(silver_path).with_suffix(""))

# New:
def run_silver_ingest(
    source_path: str,      # e.g. "sources/cap/cap-2020.md"
    ...
):
    source_content = Path(source_path).read_text(encoding="utf-8")
    source_rel_path = str(Path(source_path).with_suffix(""))  # e.g. "sources/cap/cap-2020"
```

Update every use of `silver_content` → `source_content`, `silver_relative_path` → `source_rel_path`, `silver_path` → `source_path` throughout the function body.

Update the CLI arg in `__main__`:
```python
# Old:
p_silver.add_argument("--silver", required=True, help="Path to Silver .md file")
# New:
p_silver.add_argument("--source", required=True, help="Path to source .md file (e.g. sources/cap/cap-2020.md)")
```

Update the CLI dispatch:
```python
# Old:
run_silver_ingest(silver_path=args.silver, ...)
# New:
run_silver_ingest(source_path=args.source, ...)
```

- [ ] **Step 4: Update `pipeline/ldp.py` — rename parameter throughout**

In `extract_quads_chunked()`:
```python
# Old signature:
def extract_quads_chunked(
    ...
    silver_relative_path: str = "",
    ...
) -> tuple[list[dict], int]:

# New signature:
def extract_quads_chunked(
    ...
    source_rel_path: str = "",
    ...
) -> tuple[list[dict], int]:
```

Rename every use of `silver_relative_path` → `source_rel_path` in the body and in the call to `extract_wiki_pages_from_chunk`.

Same rename in `run_ldp_ingest()`:
```python
# Old:
def run_ldp_ingest(..., silver_relative_path: str = "", ...):

# New:
def run_ldp_ingest(..., source_rel_path: str = "", ...):
```

- [ ] **Step 5: Update `pipeline/wiki_writer.py` — rename parameter + prompt string**

In `extract_wiki_pages_from_chunk()`:
```python
# Old:
def extract_wiki_pages_from_chunk(
    chunk_text: str,
    source_uuid: str,
    silver_relative_path: str,
    context_header: str,
    source_type: str,
    wiki_root: str,
    run_date: str,
) -> list[dict]:
    ...
    f"Silver path: {silver_relative_path}\n"

# New:
def extract_wiki_pages_from_chunk(
    chunk_text: str,
    source_uuid: str,
    source_rel_path: str,
    context_header: str,
    source_type: str,
    wiki_root: str,
    run_date: str,
) -> list[dict]:
    ...
    f"Source path: {source_rel_path}\n"
```

Also update the `WIKI_PAGES_SYSTEM` example citation:
```python
# Old (line ~48):
#   Source citation (REQUIRED):  ([[silver/cap/cap-2020|cap-2020]])
# New:
#   Source citation (REQUIRED):  ([[sources/cap/cap-2020|cap-2020]])
```

And all occurrences of `{silver_path}` in the prompt template strings — these are runtime-interpolated strings where the variable name `silver_path` is used as a placeholder label inside the prompt. Change to `{source_path}`:
```python
# In WIKI_PAGES_SYSTEM, replace every instance of:
#   {silver_path}
# with:
#   {source_path}
# and every instance of:
#   Silver path
# with:
#   Source path
```

- [ ] **Step 6: Fix all `[[silver/` wikilinks in existing wiki pages**

```bash
find wiki -name "*.md" -exec sed -i '' 's|\[\[silver/|\[\[sources/|g' {} +
```

Verify one file:
```bash
grep "silver/" wiki/initiatives/community-choice-aggregation.md
# Expected: no output (all replaced)
grep "sources/" wiki/initiatives/community-choice-aggregation.md | head -3
# Expected: lines showing [[sources/cap/cap-2020|cap-2020]]
```

- [ ] **Step 7: Update test files**

In `tests/test_wiki_extractor.py`, update:
- `silver_relative_path="silver/cap/cap-2020"` → `source_rel_path="sources/cap/cap-2020"`
- `"[[silver/cap/cap-2020]]"` → `"[[sources/cap/cap-2020]]"`
- `"[[silver/cap/cap-2020|cap-2020]]"` → `"[[sources/cap/cap-2020|cap-2020]]"`

In `tests/test_ldp.py`, update any `silver_relative_path` kwargs.

In `tests/test_run_ingest.py`, update any `silver_path` kwargs and `--silver` CLI args.

- [ ] **Step 8: Run full test suite**

```bash
python -m pytest tests/ -x -q
```
Expected: 89 passed, 1 skipped (same as before). Fix any failures before continuing.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: rename silver/ → sources/ and bronze/ → raw/ throughout vault and pipeline"
```

---

## Task 2: Add `pipeline/wiki_index.py` — index.md / log.md / hot.md helpers

**Files:**
- Create: `pipeline/wiki_index.py`
- Create: `tests/test_wiki_index.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wiki_index.py`:

```python
import pytest
from pathlib import Path


def test_append_index_entry_creates_file(tmp_path):
    from pipeline.wiki_index import append_index_entry
    append_index_entry(str(tmp_path), "initiative", "initiatives/cca", "Community Choice Aggregation", "CCA program")
    idx = (tmp_path / "index.md").read_text()
    assert "## initiative" in idx
    assert "[[initiatives/cca|Community Choice Aggregation]]" in idx
    assert "CCA program" in idx


def test_append_index_entry_adds_to_existing_section(tmp_path):
    from pipeline.wiki_index import append_index_entry
    append_index_entry(str(tmp_path), "initiative", "initiatives/cca", "CCA")
    append_index_entry(str(tmp_path), "initiative", "initiatives/solar", "Community Solar")
    idx = (tmp_path / "index.md").read_text()
    assert idx.count("## initiative") == 1  # only one section header
    assert "initiatives/cca" in idx
    assert "initiatives/solar" in idx


def test_append_index_entry_creates_new_section(tmp_path):
    from pipeline.wiki_index import append_index_entry
    append_index_entry(str(tmp_path), "initiative", "initiatives/cca", "CCA")
    append_index_entry(str(tmp_path), "actor", "actors/osi", "OSI")
    idx = (tmp_path / "index.md").read_text()
    assert "## initiative" in idx
    assert "## actor" in idx


def test_append_log_creates_file(tmp_path):
    from pipeline.wiki_index import append_log
    append_log(str(tmp_path), "Ingested cap-2020", source_uuid="cap-2020", run_date="2026-06-23")
    log = (tmp_path / "log.md").read_text()
    assert "2026-06-23" in log
    assert "cap-2020" in log
    assert "Ingested cap-2020" in log


def test_append_log_is_append_only(tmp_path):
    from pipeline.wiki_index import append_log
    append_log(str(tmp_path), "First entry", run_date="2026-06-23")
    append_log(str(tmp_path), "Second entry", run_date="2026-06-24")
    log = (tmp_path / "log.md").read_text()
    assert "First entry" in log
    assert "Second entry" in log


def test_update_hot_overwrites(tmp_path):
    from pipeline.wiki_index import update_hot
    update_hot(str(tmp_path), "First summary.")
    update_hot(str(tmp_path), "Second summary.")
    hot = (tmp_path / "hot.md").read_text()
    assert "Second summary." in hot
    assert "First summary." not in hot


def test_rebuild_index_scans_pages(tmp_path):
    from pipeline.wiki_index import rebuild_index
    # Create two mock wiki pages
    (tmp_path / "initiatives").mkdir()
    (tmp_path / "initiatives" / "cca.md").write_text(
        "---\ntype: initiative\ntitle: CCA\n---\n\nBody.\n"
    )
    (tmp_path / "actors").mkdir()
    (tmp_path / "actors" / "osi.md").write_text(
        "---\ntype: actor\ntitle: OSI\n---\n\nBody.\n"
    )
    rebuild_index(str(tmp_path))
    idx = (tmp_path / "index.md").read_text()
    assert "## initiative" in idx
    assert "## actor" in idx
    assert "initiatives/cca" in idx
    assert "actors/osi" in idx
    assert "index.md" not in idx  # infrastructure file excluded


def test_rebuild_index_excludes_infrastructure_files(tmp_path):
    from pipeline.wiki_index import rebuild_index, update_hot, append_log
    update_hot(str(tmp_path), "some summary")
    append_log(str(tmp_path), "some log", run_date="2026-06-23")
    rebuild_index(str(tmp_path))
    idx = (tmp_path / "index.md").read_text()
    assert "log.md" not in idx
    assert "hot.md" not in idx
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_wiki_index.py -v
```
Expected: `ModuleNotFoundError: No module named 'pipeline.wiki_index'`

- [ ] **Step 3: Create `pipeline/wiki_index.py`**

```python
import re
import yaml
from datetime import datetime
from pathlib import Path


def _index_path(wiki_root: str) -> Path:
    return Path(wiki_root) / "index.md"


def _log_path(wiki_root: str) -> Path:
    return Path(wiki_root) / "log.md"


def _hot_path(wiki_root: str) -> Path:
    return Path(wiki_root) / "hot.md"


def append_index_entry(
    wiki_root: str,
    page_type: str,
    slug: str,
    title: str,
    summary: str = "",
) -> None:
    """Add one line to wiki/index.md under the correct type section."""
    idx = _index_path(wiki_root)
    idx.parent.mkdir(parents=True, exist_ok=True)

    line = f"- [[{slug}|{title}]]"
    if summary:
        line += f" — {summary}"

    if not idx.exists():
        idx.write_text(
            f"# Wiki Index\n\n_Updated automatically on ingest._\n\n## {page_type}\n\n{line}\n",
            encoding="utf-8",
        )
        return

    content = idx.read_text(encoding="utf-8")
    section_header = f"\n## {page_type}\n"
    if section_header in content:
        content = content.replace(section_header, section_header + f"\n{line}\n")
    else:
        content = content.rstrip("\n") + f"\n{section_header}\n{line}\n"
    idx.write_text(content, encoding="utf-8")


def append_log(
    wiki_root: str,
    message: str,
    source_uuid: str = "",
    run_date: str = "",
) -> None:
    """Append a timestamped entry to wiki/log.md (append-only)."""
    log = _log_path(wiki_root)
    log.parent.mkdir(parents=True, exist_ok=True)

    ts = run_date or datetime.utcnow().strftime("%Y-%m-%d")
    parts = [ts]
    if source_uuid:
        parts.append(source_uuid)
    header = " | ".join(parts)

    entry = f"\n## [{header}]\n\n{message}\n"

    is_new = not log.exists() or log.stat().st_size == 0
    with log.open("a", encoding="utf-8") as f:
        if is_new:
            f.write("# Ingest Log\n\nAppend-only record of all pipeline operations.\n")
        f.write(entry)


def update_hot(wiki_root: str, summary: str) -> None:
    """Overwrite wiki/hot.md with a fresh recent-context summary (~500 words)."""
    hot = _hot_path(wiki_root)
    hot.parent.mkdir(parents=True, exist_ok=True)
    hot.write_text(f"# Hot Cache\n\n{summary}\n", encoding="utf-8")


def rebuild_index(wiki_root: str) -> None:
    """Rebuild wiki/index.md from scratch by scanning all wiki pages."""
    wiki = Path(wiki_root)
    entries: dict[str, list[dict]] = {}
    infrastructure = {"index.md", "log.md", "hot.md"}

    for md_file in sorted(wiki.rglob("*.md")):
        if md_file.name in infrastructure:
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
            m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
            fm = yaml.safe_load(m.group(1)) if m else {}
            page_type = (fm or {}).get("type", "unknown")
            title = (fm or {}).get("title", md_file.stem)
            slug = str(md_file.relative_to(wiki).with_suffix(""))
            entries.setdefault(page_type, []).append({"slug": slug, "title": title})
        except Exception:
            pass

    total = sum(len(v) for v in entries.values())
    today = datetime.utcnow().strftime("%Y-%m-%d")
    lines = [
        "# Wiki Index\n\n",
        f"_{total} pages — rebuilt {today}_\n",
    ]
    for pt in sorted(entries):
        lines.append(f"\n## {pt}\n\n")
        for p in sorted(entries[pt], key=lambda x: x["title"]):
            lines.append(f"- [[{p['slug']}|{p['title']}]]\n")

    _index_path(wiki_root).write_text("".join(lines), encoding="utf-8")
    print(f"[wiki_index] Rebuilt index: {total} pages across {len(entries)} types")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_wiki_index.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/wiki_index.py tests/test_wiki_index.py
git commit -m "feat: add wiki_index.py — index.md / log.md / hot.md helpers"
```

---

## Task 3: Add `pipeline/holistic_synthesizer.py` — Pass 1 (Writer → Evaluator → Editor)

**Files:**
- Create: `pipeline/holistic_synthesizer.py`
- Create: `tests/test_holistic_synthesizer.py`
- Modify: `pipeline/silver_to_gold.py` — add "overview" to VALID_PAGE_TYPES, remove "plan"

The holistic synthesizer uses a **three-call loop** rather than a single LLM call:

1. **Writer** — reads the full document, produces a draft with four sections:
   `overview`, `strategy_bodies`, `stub_pages`, `topic_candidates`
2. **Evaluator** — reads the source AND the draft, produces a structured critique
   (accuracy, completeness, format, redundancy, score, `proceed_to_edit`)
3. **Editor** — reads the source, draft, and critique, produces the final revised JSON

Structural validation (`_validate_synthesis_output`) runs after the Editor call. If it
fails, the error list is appended to the Editor prompt and the Editor retries (up to
`max_retries` times). If the Evaluator scores the draft too low (`proceed_to_edit: false`),
the Writer re-runs with the evaluator's `accuracy_issues` fed back as context before the
Editor step.

**Model**: `claude-sonnet-4-6` for all three steps.
**max_tokens**: Writer 16384, Evaluator 4096, Editor 16384.
The `[FULL DOCUMENT]` block uses `cache_control` so Evaluator and Editor pay cache-read
price on the document (same block sent to all three calls).

- [ ] **Step 1: Update VALID_PAGE_TYPES in `pipeline/silver_to_gold.py`**

```python
# Old:
VALID_PAGE_TYPES = frozenset({
    "strategy", "initiative", "actor", "funding-event", "technology",
    "location", "meeting", "framing", "political-event", "contradiction", "mechanism",
    "plan",
    "topic", "synthesis",
})

# New:
VALID_PAGE_TYPES = frozenset({
    # LLM-writable via wiki_writer.py (Pass 2) — chunked leaf-node extraction:
    "initiative", "actor", "funding-event", "technology",
    "location", "meeting", "framing", "political-event", "contradiction", "mechanism",
    # Written by holistic_synthesizer.py (Pass 1) — never by chunked extraction:
    "overview",   # one per source document (replaces "plan")
    "strategy",   # synthesis bodies written by holistic synthesizer
    # Pre-created by data team or generated by post-ingest pipeline:
    "topic", "synthesis",
})
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_holistic_synthesizer.py`:

```python
import json
import pytest
from unittest.mock import MagicMock, patch


MOCK_SYNTHESIS = {
    "overview": {
        "slug": "overviews/cap-2020",
        "frontmatter": {
            "type": "overview",
            "title": "Ann Arbor A2Zero Living Carbon Neutrality Plan",
            "source-type": "strategic-plan",
            "source-ref": "[[sources/cap/cap-2020]]",
            "date": "2020-04",
            "scope": "community-wide",
            "structure": ["Executive Summary", "Seven Strategies", "Implementation Actions"],
            "tags": ["cap", "a2zero", "carbon-neutrality"],
            "source-first-seen": "[[sources/cap/cap-2020]]",
            "last-updated": "2026-06-23",
        },
        "body": "The A2Zero plan is Ann Arbor's roadmap to carbon neutrality by 2030. ([[sources/cap/cap-2020|cap-2020]])",
    },
    "strategy_bodies": [
        {
            "slug": "strategies/strategy-1-renewable-grid",
            "body": "Strategy 1 focuses on 100% renewable electricity via CCA and solar programs. ([[sources/cap/cap-2020|cap-2020]])",
        },
    ],
    "stub_pages": [
        {
            "type": "initiative",
            "title": "Community Choice Aggregation",
            "slug": "initiatives/community-choice-aggregation",
            "parent-strategy": "strategy-1-renewable-grid",
            "one-liner": "Municipal bulk renewable energy purchasing for all residents",
        },
    ],
    "topic_candidates": [
        {"title": "Environmental Justice", "rationale": "Equity framing spans Strategies 1, 3, and 7"},
    ],
    "log_summary": "Ingested cap-2020: 7 strategies, 44 actions, community-wide 2030 target.",
}

MOCK_CRITIQUE = {
    "accuracy_issues": [],
    "completeness_gaps": [],
    "format_issues": [],
    "redundancy_issues": [],
    "overall_score": 9,
    "proceed_to_edit": True,
}


def _make_response(payload):
    r = MagicMock()
    r.stop_reason = "end_turn"
    r.content = [MagicMock(text=json.dumps(payload))]
    return r


def _strategy_stub(tmp_path):
    (tmp_path / "strategies").mkdir(exist_ok=True)
    (tmp_path / "strategies" / "strategy-1-renewable-grid.md").write_text(
        "---\ntype: strategy\ntitle: Strategy 1\n---\n\n<!-- stub -->\n"
    )
    (tmp_path / "overviews").mkdir(exist_ok=True)


@patch("pipeline.holistic_synthesizer.anthropic.Anthropic")
def test_synthesize_source_makes_three_calls(mock_anthropic_class, tmp_path):
    """Writer → Evaluator → Editor: exactly 3 API calls on the happy path."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.side_effect = [
        _make_response(MOCK_SYNTHESIS),   # Writer
        _make_response(MOCK_CRITIQUE),    # Evaluator
        _make_response(MOCK_SYNTHESIS),   # Editor
    ]
    _strategy_stub(tmp_path)

    from pipeline.holistic_synthesizer import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDocument body.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is not None
    assert mock_client.messages.create.call_count == 3


@patch("pipeline.holistic_synthesizer.anthropic.Anthropic")
def test_synthesize_source_writes_overview(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.side_effect = [
        _make_response(MOCK_SYNTHESIS),
        _make_response(MOCK_CRITIQUE),
        _make_response(MOCK_SYNTHESIS),
    ]
    _strategy_stub(tmp_path)

    from pipeline.holistic_synthesizer import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDocument body.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is not None
    overview_path = tmp_path / "overviews" / "cap-2020.md"
    assert overview_path.exists()
    content = overview_path.read_text()
    assert "Ann Arbor A2Zero" in content
    assert "type: overview" in content


@patch("pipeline.holistic_synthesizer.anthropic.Anthropic")
def test_synthesize_source_appends_strategy_body(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.side_effect = [
        _make_response(MOCK_SYNTHESIS),
        _make_response(MOCK_CRITIQUE),
        _make_response(MOCK_SYNTHESIS),
    ]
    _strategy_stub(tmp_path)
    stub = tmp_path / "strategies" / "strategy-1-renewable-grid.md"

    from pipeline.holistic_synthesizer import synthesize_source
    synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDoc.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    content = stub.read_text()
    assert "Strategy 1 focuses on 100% renewable electricity" in content


@patch("pipeline.holistic_synthesizer.anthropic.Anthropic")
def test_synthesize_source_skips_if_overview_exists(mock_anthropic_class, tmp_path):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client

    (tmp_path / "overviews").mkdir()
    (tmp_path / "overviews" / "cap-2020.md").write_text("existing overview")

    from pipeline.holistic_synthesizer import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDoc.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is None
    assert not mock_client.messages.create.called


@patch("pipeline.holistic_synthesizer.anthropic.Anthropic")
def test_evaluator_proceed_false_reruns_writer(mock_anthropic_class, tmp_path):
    """If evaluator says proceed_to_edit=False, Writer re-runs, then Editor runs."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    bad_critique = {**MOCK_CRITIQUE, "overall_score": 2, "proceed_to_edit": False}
    mock_client.messages.create.side_effect = [
        _make_response(MOCK_SYNTHESIS),   # Writer (first attempt)
        _make_response(bad_critique),     # Evaluator — says don't proceed
        _make_response(MOCK_SYNTHESIS),   # Writer (retry)
        _make_response(MOCK_SYNTHESIS),   # Editor
    ]
    _strategy_stub(tmp_path)

    from pipeline.holistic_synthesizer import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDoc.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
    )

    assert result is not None
    assert mock_client.messages.create.call_count == 4


@patch("pipeline.holistic_synthesizer.anthropic.Anthropic")
def test_editor_retries_on_validation_failure(mock_anthropic_class, tmp_path):
    """Editor output that fails structural validation causes Editor to retry."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    bad_editor_output = {"overview": None, "strategy_bodies": []}
    mock_client.messages.create.side_effect = [
        _make_response(MOCK_SYNTHESIS),       # Writer
        _make_response(MOCK_CRITIQUE),        # Evaluator
        _make_response(bad_editor_output),    # Editor attempt 1 — fails validation
        _make_response(MOCK_SYNTHESIS),       # Editor attempt 2 — passes
    ]
    _strategy_stub(tmp_path)

    from pipeline.holistic_synthesizer import synthesize_source
    result = synthesize_source(
        source_content="---\nuuid: cap-2020\n---\n\nDoc.",
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        source_type="cap",
        wiki_root=str(tmp_path),
        run_date="2026-06-23",
        max_retries=2,
    )

    assert result is not None
    assert mock_client.messages.create.call_count == 4


def test_validate_synthesis_output_catches_missing_overview(tmp_path):
    from pipeline.holistic_synthesizer import _validate_synthesis_output
    errors = _validate_synthesis_output(
        {"strategy_bodies": []}, source_uuid="cap-2020", wiki_root=str(tmp_path)
    )
    assert any("overview" in e for e in errors)


def test_validate_synthesis_output_catches_bad_source_ref(tmp_path):
    from pipeline.holistic_synthesizer import _validate_synthesis_output
    result = {
        "overview": {
            "slug": "overviews/cap-2020",
            "frontmatter": {
                "type": "overview",
                "title": "Test",
                "source-ref": "silver/cap/cap-2020",  # missing [[...]] wikilink format
            },
            "body": "Some body.",
        },
        "strategy_bodies": [],
    }
    errors = _validate_synthesis_output(result, source_uuid="cap-2020", wiki_root=str(tmp_path))
    assert any("source-ref" in e for e in errors)


@patch("pipeline.holistic_synthesizer.anthropic.Anthropic")
def test_synthesize_source_integrates_existing_strategy_body(mock_anthropic_class, tmp_path):
    """When a strategy page already has real content, body is replaced not appended."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.side_effect = [
        _make_response(MOCK_SYNTHESIS),
        _make_response(MOCK_CRITIQUE),
        _make_response(MOCK_SYNTHESIS),
    ]
    _strategy_stub(tmp_path)
    # Write existing real content to strategy page (not a stub comment)
    strat_path = tmp_path / "strategies" / "strategy-1-renewable-grid.md"
    strat_path.write_text(
        "---\ntype: strategy\ntitle: Strategy 1\n---\n\nExisting synthesis paragraph.\n"
    )
    (tmp_path / "overviews").mkdir(exist_ok=True)

    from pipeline.holistic_synthesizer import synthesize_source
    synthesize_source(
        source_content="---\nuuid: annual-report-year1\n---\n\nNew content.",
        source_uuid="annual-report-year1",
        source_rel_path="sources/annual-reports/year1",
        source_type="annual-report",
        wiki_root=str(tmp_path),
        run_date="2026-06-24",
    )

    result = strat_path.read_text()
    # Integrated body from MOCK_SYNTHESIS should be present
    assert "Strategy 1 focuses on 100% renewable electricity" in result
    # Old body should NOT appear alongside new body (replacement, not append)
    assert result.count("Existing synthesis paragraph.") == 0


def test_replace_wiki_page_body_preserves_frontmatter(tmp_path):
    from pipeline.holistic_synthesizer import _replace_wiki_page_body
    page = tmp_path / "test.md"
    page.write_text("---\ntype: strategy\ntitle: Test\n---\n\nOld body.\n")
    _replace_wiki_page_body(str(page), "New integrated body.")
    content = page.read_text()
    assert "type: strategy" in content
    assert "New integrated body." in content
    assert "Old body." not in content


def test_validate_synthesis_output_catches_unknown_strategy_slug(tmp_path):
    from pipeline.holistic_synthesizer import _validate_synthesis_output
    (tmp_path / "strategies").mkdir()
    result = {
        "overview": {
            "slug": "overviews/cap-2020",
            "frontmatter": {
                "type": "overview",
                "title": "Test",
                "source-ref": "[[sources/cap/cap-2020]]",
            },
            "body": "Body.",
        },
        "strategy_bodies": [
            {"slug": "strategies/strategy-8-invented", "body": "Body."}
        ],
    }
    errors = _validate_synthesis_output(result, source_uuid="cap-2020", wiki_root=str(tmp_path))
    assert any("strategy-8-invented" in e for e in errors)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python -m pytest tests/test_holistic_synthesizer.py -v
```
Expected: `ModuleNotFoundError: No module named 'pipeline.holistic_synthesizer'`

- [ ] **Step 4: Create `pipeline/holistic_synthesizer.py`**

```python
import anthropic
import json
import re
from pathlib import Path

from pipeline.silver_to_gold import build_wiki_page, write_wiki_page, append_to_wiki_page
from pipeline.wiki_index import append_index_entry, append_log


# ── System prompts ────────────────────────────────────────────────────────────

HOLISTIC_WRITER_SYSTEM = """You are a policy intelligence curator building the A2Zero knowledge wiki for the City of Ann Arbor.

You will read an ENTIRE source document and produce a structured JSON first draft.
This is HOLISTIC EDITORIAL UNDERSTANDING, not chunked extraction.

Your output has three parts:
1. An OVERVIEW page — what this document IS (scope, structure, commitments)
2. STRATEGY BODIES — what this document says about each A2Zero strategy (narrative synthesis)
3. A LOG SUMMARY — one sentence describing the ingest

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A2ZERO STRATEGIES — use these exact slugs in strategy_bodies:
  strategies/strategy-1-renewable-grid
  strategies/strategy-2-electrification
  strategies/strategy-3-building-efficiency
  strategies/strategy-4-vmt-reduction
  strategies/strategy-5-materials-waste
  strategies/strategy-6-resilience
  strategies/strategy-7-engagement

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OVERVIEW PAGE RULES:
- type: "overview" (exactly)
- source-type: one of "strategic-plan", "annual-report", "council-transcript", "news", "research"
- source-ref: MUST be a wikilink string "[[sources/<path>]]" — not a plain path
- body: 3-5 paragraphs answering: what is this document, who produced it, when,
  what does it commit to or report, how is its content structured?

STRATEGY BODY RULES:
- Write 2-4 paragraphs of narrative synthesis per strategy
- SYNTHESIZE, do not list: what is the dominant approach? what programs are proposed?
  what are projected GHG reductions or costs? what dependencies exist?
- If the document says little about a strategy, write one honest sentence
- Cite with inline wikilinks: ([[{source_path}|{source_uuid}]])
- Reference named initiatives where possible: [[initiatives/community-choice-aggregation]]
- Include all 7 strategy slugs in strategy_bodies, even if coverage is thin

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
READ-UNDERSTAND-INTEGRATE (applies when EXISTING STRATEGY WIKI CONTENT is provided):
If the section [EXISTING STRATEGY WIKI CONTENT] appears below the document, it contains
synthesis already written from prior source ingests into this wiki.
  - Preserve all prior facts — they came from earlier sources and are still true
  - Add new depth, nuance, and evidence from THIS source document only
  - Do NOT duplicate paragraphs that already say the same thing
  - Do NOT discard prior synthesis — the Editor will produce a coherent whole
  - Your strategy body REPLACES the existing body, so it must be complete: a reader
    who has not seen the prior version should find it fully coherent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROJECTIONS AND OUTCOMES:
When this source contains quantitative targets or projections for a strategy or
initiative (e.g. "Strategy 1 will contribute 40% of A2Zero reductions by 2030"),
surface them explicitly in the strategy body prose and mark them clearly:
  "Projected: [figure and timeframe] ([[{source_path}|{source_uuid}]])"
When this source contains measured results or reported progress
(e.g. "As of 2022, Strategy 1 has achieved X% of its target"), mark them:
  "Outcome as of [date]: [figure] ([[{source_path}|{source_uuid}]])"
The pipeline will extract these into structured frontmatter. Clear labeling in
prose is required for the Editor to extract them correctly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WIKILINK FORMAT:
  In YAML frontmatter: quoted string   "[[path/slug]]"
  In body prose:       bare wikilink   [[path/slug]] or [[path/slug|display text]]
  Inline citation:     ([[{source_path}|{source_uuid}]])

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT: A single JSON object — no markdown fence, no prose outside the JSON:
{{
  "overview": {{
    "slug": "overviews/{source_uuid}",
    "frontmatter": {{
      "type": "overview",
      "title": "<descriptive title of the document>",
      "source-type": "<strategic-plan|annual-report|council-transcript|news|research>",
      "source-ref": "[[{source_path}]]",
      "date": "<YYYY or YYYY-MM>",
      "scope": "<community-wide|city-only|neighborhood|other>",
      "tags": ["<tag1>", "<tag2>"],
      "source-first-seen": "[[{source_path}]]",
      "last-updated": "{run_date}"
    }},
    "body": "<3-5 paragraphs of synthesis prose>"
  }},
  "strategy_bodies": [
    {{"slug": "strategies/strategy-1-renewable-grid", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-2-electrification", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-3-building-efficiency", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-4-vmt-reduction", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-5-materials-waste", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-6-resilience", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-7-engagement", "body": "<2-4 paragraphs>"}}
  ],
  "stub_pages": [
    {{
      "type": "<initiative|actor|location|meeting|political-event|technology>",
      "title": "<entity name>",
      "slug": "<type-plural>/<kebab-slug>",
      "parent-strategy": "<strategies/slug or null>",
      "one-liner": "<one sentence description>"
    }}
  ],
  "topic_candidates": [
    {{
      "title": "<cross-cutting topic name>",
      "rationale": "<why this topic spans multiple strategies or sources>"
    }}
  ],
  "log_summary": "<one sentence: what was ingested and what it covers>"
}}

STUB PAGES RULES:
- Include 20-50 entities you are confident are worth tracking over time
- Threshold: proper name + (named org OR budget/timeline OR implies future tracking)
- When uncertain, include — a missed entity is worse than a thin stub
- Do NOT include one-off mentions with no forward continuity
- Prefer these types for stubs: initiative, actor (for major orgs only)

TOPIC CANDIDATES RULES:
- Include 2-8 cross-cutting themes that appear across multiple strategies or sections
- Only surface themes a human analyst would find genuinely useful to track
- Do NOT include topics that are simply strategy titles"""


HOLISTIC_EVALUATOR_SYSTEM = """You are a rigorous editorial reviewer for the A2Zero knowledge wiki.

You will receive:
1. A full source document
2. A writer's draft synthesis (JSON) of that document

Your job: evaluate the draft for accuracy, completeness, format correctness, and redundancy.
Be specific — quote the draft text you're critiquing and the source text that contradicts or extends it.

A2ZERO STRATEGIES — the 7 valid strategy slugs:
  strategy-1-renewable-grid, strategy-2-electrification, strategy-3-building-efficiency,
  strategy-4-vmt-reduction, strategy-5-materials-waste, strategy-6-resilience, strategy-7-engagement

WHAT TO CHECK:
1. ACCURACY: Are all claims in the draft supported by the source? Flag hallucinations or misattributions.
2. COMPLETENESS: Did the writer miss significant sections, numbers, programs, or commitments?
3. FORMAT: Is source-ref in "[[sources/...]]" wikilink format? Are strategy slugs from the allowed list?
4. REDUNDANCY: Do strategy bodies repeat each other or duplicate overview content?

OUTPUT: A single JSON object — no markdown fence, no prose outside the JSON:
{{
  "accuracy_issues": ["<draft claim not supported by source — quote both>", ...],
  "completeness_gaps": ["<fact or section from source missing from draft>", ...],
  "format_issues": ["<specific format problem with exact location>", ...],
  "redundancy_issues": ["<specific repeated content — name the strategy bodies>", ...],
  "overall_score": <integer 1-10, where 10 = no issues>,
  "proceed_to_edit": <true if score >= 4 and draft is worth editing; false if too poor to salvage>
}}

If no issues in a category, return an empty array [].
overall_score >= 7: minor cleanup needed. 4-6: significant gaps. < 4: fundamental problems."""


HOLISTIC_EDITOR_SYSTEM = """You are the final editor for the A2Zero knowledge wiki.

You will receive:
1. A full source document
2. A writer's draft synthesis (JSON)
3. An evaluator's critique (JSON listing accuracy issues, gaps, format problems, and redundancies)

Your job: produce a FINAL, REVISED synthesis that addresses every issue the evaluator identified.

RULES:
- Fix every issue listed by the evaluator (accuracy, completeness, format, redundancy)
- Do NOT invent content not present in the source document — fix, don't fabricate
- Do NOT carry forward hallucinations from the draft — check each claim against the source
- Maintain the exact same JSON schema as the writer draft
- source-ref MUST be a wikilink: "[[sources/<path>]]"
- Strategy slugs must match exactly: strategy-1-renewable-grid through strategy-7-engagement
- Inline citations: ([[sources/<path>|<uuid>]])
- Include all 7 strategy slugs in strategy_bodies

OUTPUT: A single JSON object with the SAME SCHEMA as the writer draft — no markdown fence, no prose:
{{
  "overview": {{
    "slug": "overviews/<source-uuid>",
    "frontmatter": {{ ... }},
    "body": "<3-5 paragraphs>"
  }},
  "strategy_bodies": [
    {{"slug": "strategies/strategy-1-renewable-grid", "body": "<revised 2-4 paragraphs>"}},
    ... (all 7 strategies) ...
  ],
  "log_summary": "<one sentence>"
}}"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm_call(
    client: anthropic.Anthropic,
    system: str,
    user_content: "str | list",
    step_name: str,
    source_uuid: str,
    max_tokens: int = 8192,
    model: str = "claude-sonnet-4-6",
) -> dict | None:
    """Single LLM call with JSON parsing. Returns parsed dict or None on failure.

    user_content: either a plain string or a list of content blocks
    (used when cache_control is needed on individual blocks).
    """
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            betas=["prompt-caching-2024-07-31"],
        )
        if response.stop_reason == "max_tokens":
            print(f"[holistic:{step_name}] WARNING: response truncated for {source_uuid}")
            return None
        raw = response.content[0].text
        cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```$", "", cleaned)
        result = json.loads(cleaned)
        usage = getattr(response, "usage", None)
        if usage:
            print(
                f"[holistic:{step_name}] tokens in={usage.input_tokens} out={usage.output_tokens}"
            )
        return result
    except Exception as e:
        print(f"[holistic:{step_name}] WARNING: call failed for {source_uuid}: {e}")
        return None


def _validate_synthesis_output(
    result: dict,
    source_uuid: str,
    wiki_root: str,
) -> list[str]:
    """Structural validation of synthesis JSON before any disk writes.

    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []

    overview = result.get("overview")
    if not overview:
        errors.append("missing 'overview' key in output")
        return errors

    slug = overview.get("slug", "")
    if not slug.startswith("overviews/"):
        errors.append(f"overview.slug must start with 'overviews/', got: {slug!r}")

    fm = overview.get("frontmatter") or {}
    for required in ("type", "title", "source-ref"):
        if not fm.get(required):
            errors.append(f"overview.frontmatter.{required!r} is missing or empty")

    if fm.get("type") != "overview":
        errors.append(f"overview.frontmatter.type must be 'overview', got: {fm.get('type')!r}")

    source_ref = fm.get("source-ref", "")
    if source_ref and not re.match(r"^\[\[sources/.+\]\]$", source_ref):
        errors.append(
            f"overview.frontmatter.source-ref must be a [[sources/...]] wikilink, "
            f"got: {source_ref!r}"
        )

    if not overview.get("body", "").strip():
        errors.append("overview.body is empty")

    existing_slugs = frozenset(
        f"strategies/{p.stem}"
        for p in (Path(wiki_root) / "strategies").glob("*.md")
    )
    for sb in result.get("strategy_bodies", []):
        s = sb.get("slug", "")
        if not s.startswith("strategies/"):
            errors.append(f"strategy_bodies slug must start with 'strategies/', got: {s!r}")
        elif s not in existing_slugs:
            errors.append(
                f"strategy_bodies slug {s!r} has no matching stub in wiki/strategies/ "
                f"— valid slugs: {sorted(existing_slugs)}"
            )
        if not sb.get("body", "").strip():
            errors.append(f"strategy_bodies body is empty for slug: {s!r}")

    return errors


# ── Main entry point ──────────────────────────────────────────────────────────

def synthesize_source(
    source_content: str,
    source_uuid: str,
    source_rel_path: str,
    source_type: str,
    wiki_root: str,
    run_date: str,
    max_retries: int = 2,
) -> dict | None:
    """Pass 1 — Writer → Evaluator → Editor holistic synthesis.

    Writes:
      wiki/overviews/<source_uuid>.md   (new overview page)
      wiki/strategies/*.md              (strategy bodies appended to stubs)
      wiki/index.md                     (overview entry added)
      wiki/log.md                       (ingest record appended)

    Returns the final synthesis dict on success, None if already done or failed.
    """
    overview_path = Path(wiki_root) / "overviews" / f"{source_uuid}.md"
    if overview_path.exists():
        print(f"[holistic] Overview already exists: {overview_path} — skipping")
        return None

    doc_body = re.sub(r"^---\n.*?\n---\n", "", source_content, flags=re.DOTALL).strip()

    # Read existing strategy page bodies for multi-source integration (Amendment A).
    # If strategy pages already contain real synthesis from prior ingests, pass them
    # to the Writer as context so it integrates rather than duplicates.
    existing_strategy_content: dict[str, str] = {}
    strategies_dir = Path(wiki_root) / "strategies"
    if strategies_dir.exists():
        for strat_file in sorted(strategies_dir.glob("*.md")):
            content = strat_file.read_text(encoding="utf-8")
            body = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL).strip()
            if body and not body.startswith("<!--"):
                existing_strategy_content[f"strategies/{strat_file.stem}"] = body

    integration_block = ""
    if existing_strategy_content:
        lines = [
            "\n\n[EXISTING STRATEGY WIKI CONTENT]",
            "READ-UNDERSTAND-INTEGRATE: these strategy pages already contain synthesis",
            "from prior source ingests. Integrate new learnings from this source —",
            "preserve prior facts, add new depth, do not duplicate.\n",
        ]
        for slug, body in sorted(existing_strategy_content.items()):
            lines.append(f"--- {slug} ---\n{body}\n")
        lines.append("[END EXISTING STRATEGY WIKI CONTENT]")
        integration_block = "\n".join(lines)

    # Build document block once; reused across all three calls.
    # cache_control marks it for prompt caching so Evaluator and Editor pay
    # cache-read price (~10% of input cost) on the document portion.
    document_block_text = (
        f"Source UUID: {source_uuid}\n"
        f"Source path: {source_rel_path}\n"
        f"Source type: {source_type}\n"
        f"Today's date: {run_date}\n\n"
        f"[FULL DOCUMENT]\n{doc_body}\n[END DOCUMENT]"
        + integration_block
    )
    cached_document_block = {
        "type": "text",
        "text": document_block_text,
        "cache_control": {"type": "ephemeral"},
    }

    writer_system = HOLISTIC_WRITER_SYSTEM.format(
        source_uuid=source_uuid,
        source_path=source_rel_path,
        run_date=run_date,
    )

    client = anthropic.Anthropic()

    # ── Step 1: Writer ────────────────────────────────────────────────────────
    print(f"[holistic:writer] {source_uuid}")
    draft = _llm_call(
        client, writer_system,
        [cached_document_block],  # messages content as list for cache_control
        "writer", source_uuid, max_tokens=16384,
    )
    if draft is None:
        print(f"[holistic] ERROR: writer call failed for {source_uuid}")
        return None

    # ── Step 2: Evaluator ─────────────────────────────────────────────────────
    print(f"[holistic:evaluator] {source_uuid}")
    eval_content = [
        cached_document_block,
        {"type": "text", "text": "\n\n[WRITER DRAFT]\n" + json.dumps(draft, indent=2) + "\n[END DRAFT]"},
    ]
    critique = _llm_call(
        client, HOLISTIC_EVALUATOR_SYSTEM, eval_content,
        "evaluator", source_uuid, max_tokens=4096,
    )

    if critique is None or not critique.get("proceed_to_edit", True):
        score = (critique or {}).get("overall_score", "?")
        accuracy_issues = (critique or {}).get("accuracy_issues", [])
        print(f"[holistic:evaluator] Low quality score ({score}) — re-running writer with feedback")
        retry_suffix = ""
        if accuracy_issues:
            retry_suffix = (
                "\n\nIMPORTANT: A previous draft of this synthesis contained these accuracy problems. "
                "Avoid repeating them:\n" + "\n".join(f"- {i}" for i in accuracy_issues)
            )
        retry_content = [
            cached_document_block,
            {"type": "text", "text": retry_suffix},
        ]
        draft = _llm_call(
            client, writer_system, retry_content,
            "writer-retry", source_uuid, max_tokens=16384,
        )
        if draft is None:
            print(f"[holistic] ERROR: writer retry failed for {source_uuid}")
            return None
        critique = {}

    # ── Step 3: Editor (with structural validation retry) ─────────────────────
    editor_content = [
        cached_document_block,
        {"type": "text", "text": (
            "\n\n[WRITER DRAFT]\n" + json.dumps(draft, indent=2) + "\n[END DRAFT]"
            + "\n\n[EVALUATOR CRITIQUE]\n" + json.dumps(critique, indent=2) + "\n[END CRITIQUE]"
        )},
    ]

    for attempt in range(max_retries + 1):
        print(f"[holistic:editor] {source_uuid} attempt {attempt + 1}")
        final = _llm_call(
            client, HOLISTIC_EDITOR_SYSTEM, editor_content,
            f"editor-{attempt}", source_uuid, max_tokens=16384,
        )
        if final is None:
            continue

        errors = _validate_synthesis_output(final, source_uuid=source_uuid, wiki_root=wiki_root)
        if not errors:
            _write_synthesis(final, wiki_root=wiki_root, source_uuid=source_uuid, run_date=run_date)
            return final

        print(f"[holistic:editor] Validation failed (attempt {attempt + 1}): {errors}")
        # Append validation errors to the last content block for the next attempt
        editor_content[-1]["text"] += (
            "\n\nYOUR PREVIOUS RESPONSE FAILED STRUCTURAL VALIDATION. Fix these errors:\n"
            + "\n".join(f"- {e}" for e in errors)
        )

    print(f"[holistic] ERROR: editor failed after {max_retries + 1} attempts for {source_uuid}")
    return None


def _replace_wiki_page_body(page_path: str, new_body: str) -> None:
    """Replace the body section of a wiki page, preserving frontmatter intact."""
    content = Path(page_path).read_text(encoding="utf-8")
    m = re.match(r"^(---\n.*?\n---\n)", content, re.DOTALL)
    frontmatter = m.group(1) if m else ""
    Path(page_path).write_text(frontmatter + "\n" + new_body.strip() + "\n", encoding="utf-8")


def _write_synthesis(
    result: dict,
    wiki_root: str,
    source_uuid: str,
    run_date: str,
) -> None:
    """Write validated synthesis to disk. Only called after _validate_synthesis_output passes."""
    ov = result["overview"]
    fm = dict(ov["frontmatter"])
    fm["last-updated"] = run_date

    page = build_wiki_page(
        page_type="overview",
        slug=ov["slug"],
        frontmatter=fm,
        body=ov["body"],
    )
    write_wiki_page(page, wiki_root=wiki_root, exist_ok=False)
    print(f"[holistic] Overview written: wiki/{ov['slug']}.md")

    append_index_entry(
        wiki_root=wiki_root,
        page_type="overview",
        slug=ov["slug"],
        title=fm.get("title", source_uuid),
        summary=fm.get("source-type", ""),
    )

    for sb in result.get("strategy_bodies", []):
        strat_path = Path(wiki_root) / (sb["slug"] + ".md")
        if not strat_path.exists():
            print(f"[holistic] WARNING: strategy stub missing: {strat_path} — skipping")
            continue
        # Amendment A: detect-and-replace vs. append.
        # If the page already has real body content (beyond the initial stub comment),
        # the Editor produced an integrated body — replace, do not append.
        existing = strat_path.read_text(encoding="utf-8")
        existing_body = re.sub(r"^---\n.*?\n---\n", "", existing, flags=re.DOTALL).strip()
        is_stub_only = not existing_body or existing_body.startswith("<!--")
        if is_stub_only:
            append_to_wiki_page(str(strat_path), sb["body"], source_uuid=source_uuid)
            print(f"[holistic] Strategy body written: {strat_path.name}")
        else:
            _replace_wiki_page_body(str(strat_path), sb["body"])
            print(f"[holistic] Strategy body integrated: {strat_path.name}")

    # Write stub pages (minimal frontmatter-only files, bodies filled by Pass 2)
    stubs_written = 0
    for sp in result.get("stub_pages", []):
        stub_slug = sp.get("slug", "")
        if not stub_slug:
            continue
        stub_path = Path(wiki_root) / (stub_slug + ".md")
        if stub_path.exists():
            continue  # already exists from prior run or Pass 2
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_fm = {
            "type": sp.get("type", "initiative"),
            "title": sp.get("title", ""),
            "source-first-seen": f"[[sources/{source_uuid}]]",
            "last-updated": run_date,
        }
        if sp.get("parent-strategy"):
            stub_fm["parent-strategy"] = sp["parent-strategy"]
        # Amendment B: initialize projections/outcomes lists on initiative stubs so
        # subsequent ingests can append structured entries rather than creating the keys.
        if sp.get("type") in ("initiative", "strategy"):
            stub_fm["projections"] = []
            stub_fm["outcomes"] = []
        stub_page = build_wiki_page(
            page_type=sp.get("type", "initiative"),
            slug=stub_slug,
            frontmatter=stub_fm,
            body=f"<!-- stub from Pass 1 holistic read ({source_uuid}) — {sp.get('one-liner', '')} -->",
        )
        write_wiki_page(stub_page, wiki_root=wiki_root, exist_ok=False)
        stubs_written += 1
    if stubs_written:
        print(f"[holistic] {stubs_written} stub pages created for Pass 2")

    # Append topic candidates to wiki/meta/topic-candidates.md (not wiki pages)
    candidates = result.get("topic_candidates", [])
    if candidates:
        meta_dir = Path(wiki_root) / "meta"
        meta_dir.mkdir(exist_ok=True)
        candidates_path = meta_dir / "topic-candidates.md"
        with candidates_path.open("a", encoding="utf-8") as f:
            for tc in candidates:
                f.write(
                    f"\n## {tc.get('title', 'Unknown')} | Source: {source_uuid} | {run_date}\n"
                    f"Rationale: {tc.get('rationale', '')}\n"
                    f"Resolution: [ ] Promote to wiki/topics/  [ ] Dismiss\n"
                )
        print(f"[holistic] {len(candidates)} topic candidates written to wiki/meta/topic-candidates.md")

    log_parts = [result.get("log_summary", f"Ingested {source_uuid}.")]
    log_parts.append(
        f"Pass 1: Writer→Evaluator→Editor complete. "
        f"{len(result.get('stub_pages', []))} stubs, "
        f"{len(candidates)} topic candidates."
    )
    append_log(
        wiki_root=wiki_root,
        message="\n".join(log_parts),
        source_uuid=source_uuid,
        run_date=run_date,
    )
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_holistic_synthesizer.py -v
```
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add pipeline/holistic_synthesizer.py pipeline/silver_to_gold.py tests/test_holistic_synthesizer.py
git commit -m "feat: add holistic_synthesizer.py — Writer → Evaluator → Editor Pass 1 synthesis"
```

---

## Task 4: Update `pipeline/wiki_writer.py` — rename to PASS2_FORBIDDEN_TYPES, add schema-drift logging

Pass 2 (chunked extraction) must never write strategy or overview pages. The strategy
slug whitelist guard is no longer needed. Also add schema-drift logging so unknown types
are flagged for HITL review rather than silently dropped.

**Files:**
- Modify: `pipeline/wiki_writer.py`
- Modify: `tests/test_wiki_extractor.py`

- [ ] **Step 1: Rename PASS3_FORBIDDEN_TYPES → PASS2_FORBIDDEN_TYPES and update values**

```python
# Old:
PASS2_FORBIDDEN_TYPES = frozenset({
    "plan",
    "topic",
    "mechanism",
    "synthesis",
})

# New (renamed + expanded):
PASS2_FORBIDDEN_TYPES = frozenset({
    "overview",   # written by holistic_synthesizer.py (Pass 1)
    "strategy",   # bodies written by holistic_synthesizer.py (Pass 1)
    "topic",      # human-declared only (candidates surfaced by Pass 1)
    "mechanism",  # requires cross-source corroboration
    "synthesis",  # post-ingest only
})
```

- [ ] **Step 2: Remove strategy slug whitelist, add schema-drift logging, add integration + proposed-type instructions to WIKI_PAGES_SYSTEM**

The `allowed_strategy_slugs` parameter is no longer needed since "strategy" is in
`PASS2_FORBIDDEN_TYPES`. Two sets of instructions are being added to `WIKI_PAGES_SYSTEM`:
(a) the read-understand-integrate model for existing pages (Amendment A), and
(b) the proposed-type ontology rule.

**2a. Add READ-UNDERSTAND-INTEGRATE instruction to `WIKI_PAGES_SYSTEM` prompt** (add before the TYPE RULES section):

```python
# Add to WIKI_PAGES_SYSTEM before the list of approved types:
"""
READ-UNDERSTAND-INTEGRATE:
If EXISTING PAGE CONTENT is shown below in [EXISTING: slug] blocks, those pages
already exist in the wiki from a prior source ingest.
  - Produce an INTEGRATED body for that page — one that a reader who has never seen
    the prior version would find fully coherent and complete
  - Preserve all prior facts (they came from earlier sources and are still valid)
  - Add new depth, evidence, and nuance from THIS chunk only
  - Do NOT duplicate paragraphs that already make the same point
  - Your body content REPLACES the existing body — write a complete whole, not an appendage
For entity pages that do NOT have existing content, write normally.
"""
```

**2b. Add instruction to `WIKI_PAGES_SYSTEM` prompt** (add to the TYPE RULES section):

```python
# Add to WIKI_PAGES_SYSTEM after the list of approved types:
"""
ONTOLOGY RULES:
- Always use an approved page_type from the list above.
- If your entity does not fit any approved type, use the closest approved type as
  page_type AND add proposed_type: "<your-intended-type>" to the frontmatter JSON.
  Example: a "zoning-application" would use page_type: "political-event" and
  frontmatter proposed_type: "zoning-application".
- NEVER use an unapproved string as the primary page_type — it will fail validation.
- Tags handle specificity; proposed_type handles structural novelty for human review.
"""
```

**2c. Add `_replace_wiki_page_body` to `wiki_writer.py`** (same helper as in `holistic_synthesizer.py` — add to the top of the file near other helpers):

```python
def _replace_wiki_page_body(page_path: str, new_body: str) -> None:
    """Replace the body section of a wiki page, preserving frontmatter intact."""
    content = Path(page_path).read_text(encoding="utf-8")
    m = re.match(r"^(---\n.*?\n---\n)", content, re.DOTALL)
    frontmatter = m.group(1) if m else ""
    Path(page_path).write_text(frontmatter + "\n" + new_body.strip() + "\n", encoding="utf-8")
```

**2d. Update `extract_wiki_pages_from_chunk` to include existing page bodies in context:**

When `known_entities` contains entities that already have real page content (not just stubs), include those bodies in the chunk context header so the LLM can integrate rather than duplicate.

```python
# In run_ingest.py, inside _build_entity_context(), after building the entity list:
# Read existing page bodies for entities that have content beyond a stub comment.
existing_pages_block = ""
for e in entities:
    slug = e.get("slug", "")
    if not slug:
        continue
    page_path = Path(wiki_root) / (slug + ".md")
    if not page_path.exists():
        continue
    content = page_path.read_text(encoding="utf-8")
    body = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL).strip()
    if body and not body.startswith("<!--"):
        existing_pages_block += f"\n[EXISTING: {slug}]\n{body}\n[END EXISTING]\n"

if existing_pages_block:
    lines.append("\nEXISTING PAGE CONTENT — READ-UNDERSTAND-INTEGRATE:")
    lines.append(existing_pages_block)
```

**2e. Update `write_wiki_page` call in `extract_wiki_pages_from_chunk` to detect-and-replace:**

```python
# When writing a page that already has content, replace rather than append.
# (The page body produced by the LLM is already integrated — it replaces, not appends.)
page_path = Path(wiki_root) / (spec["slug"] + ".md")
if page_path.exists():
    existing = page_path.read_text(encoding="utf-8")
    existing_body = re.sub(r"^---\n.*?\n---\n", "", existing, flags=re.DOTALL).strip()
    if existing_body and not existing_body.startswith("<!--"):
        _replace_wiki_page_body(str(page_path), spec["body"])
        continue  # skip write_wiki_page
# Normal write path (new page or stub-only existing page):
write_wiki_page(page, wiki_root=wiki_root, exist_ok=True)
```

**2f. Update `validate_page_spec` signature and logic:**

```python
# Old signature:
def validate_page_spec(
    spec: dict,
    allowed_strategy_slugs: frozenset[str] | None = None,
) -> list[str]:
    ...

# New signature:
def validate_page_spec(spec: dict, wiki_root: str = "") -> list[str]:

```python
# Add to WIKI_PAGES_SYSTEM after the list of approved types:
"""
ONTOLOGY RULES:
- Always use an approved page_type from the list above.
- If your entity does not fit any approved type, use the closest approved type as
  page_type AND add proposed_type: "<your-intended-type>" to the frontmatter JSON.
  Example: a "zoning-application" would use page_type: "political-event" and
  frontmatter proposed_type: "zoning-application".
- NEVER use an unapproved string as the primary page_type — it will fail validation.
- Tags handle specificity; proposed_type handles structural novelty for human review.
"""
```

- [ ] **Step 3: Remove `allowed_strategy_slugs` build from `extract_wiki_pages_from_chunk`**

```python
# Old (remove these lines from extract_wiki_pages_from_chunk):
    strategy_dir = Path(wiki_root) / "strategies"
    allowed_strategy_slugs: frozenset[str] = frozenset(
        f"strategies/{p.stem}" for p in strategy_dir.glob("*.md")
    ) if strategy_dir.exists() else frozenset()

    for spec in specs:
        errors = validate_page_spec(spec, allowed_strategy_slugs=allowed_strategy_slugs)

# New (pass wiki_root so drift logging works):
    for spec in specs:
        errors = validate_page_spec(spec, wiki_root=wiki_root)
```

- [ ] **Step 4: Update tests in `tests/test_wiki_extractor.py`**

a) Update `test_validate_page_spec_rejects_forbidden_types` — "plan" → "overview":
```python
def test_validate_page_spec_rejects_forbidden_types():
    """Overview, strategy, topic, mechanism, synthesis must never be created by Pass 2."""
    from pipeline.wiki_writer import validate_page_spec
    for forbidden in ("overview", "strategy", "topic", "synthesis", "mechanism"):
        spec = {**MOCK_PAGES[0], "page_type": forbidden}
        errors = validate_page_spec(spec)
        assert any("forbidden" in e for e in errors), (
            f"Expected forbidden error for page_type={forbidden!r}, got: {errors}"
        )
```

b) Update `test_validate_page_spec_accepts_all_llm_writable_types` — remove "strategy", add note:
```python
def test_validate_page_spec_accepts_all_llm_writable_types():
    """All Pass 2 LLM-writable types pass type validation (strategy removed — now Pass 1 only)."""
    from pipeline.wiki_writer import validate_page_spec
    for pt in ("initiative", "actor", "funding-event", "technology",
               "location", "meeting", "framing", "political-event", "contradiction"):
        spec = {
            "page_type": pt,
            "slug": f"test/{pt}-slug",
            "frontmatter": {"type": pt},
            "body": "Test body. ([[sources/cap/cap-2020|cap-2020]])",
        }
        errors = validate_page_spec(spec)
        type_errors = [e for e in errors if "page_type" in e or "forbidden" in e]
        assert type_errors == [], f"Unexpected type error for {pt!r}: {type_errors}"
```

c) Remove the three whitelist tests (`test_validate_page_spec_rejects_unknown_strategy_slug`, `test_validate_page_spec_accepts_known_strategy_slug`, `test_validate_page_spec_skips_whitelist_when_not_provided`) — the whitelist no longer exists.

d) Update `test_validate_page_spec_rejects_commitment_type` — also assert strategy is forbidden:
```python
def test_validate_page_spec_rejects_strategy_and_commitment_types():
    """strategy and commitment are forbidden in Pass 2."""
    from pipeline.wiki_writer import validate_page_spec
    for pt in ("commitment", "strategy"):
        spec = {**MOCK_PAGES[0], "page_type": pt}
        errors = validate_page_spec(spec)
        assert any("page_type" in e or "forbidden" in e for e in errors), (
            f"Expected error for {pt!r}, got: {errors}"
        )
```

e) Update all `extract_wiki_pages_from_chunk` calls in the test file — rename `silver_relative_path` → `source_rel_path`:
```python
# Old:
    pages = extract_wiki_pages_from_chunk(
        chunk_text=SAMPLE_CHUNK,
        source_uuid="cap-2020",
        silver_relative_path="silver/cap/cap-2020",
        ...
    )
# New:
    pages = extract_wiki_pages_from_chunk(
        chunk_text=SAMPLE_CHUNK,
        source_uuid="cap-2020",
        source_rel_path="sources/cap/cap-2020",
        ...
    )
```

f) Update MOCK_PAGES milestone source field:
```python
# Old:
    "source": "[[silver/cap/cap-2020]]",
# New:
    "source": "[[sources/cap/cap-2020]]",
```

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -x -q
```
Expected: all passing (count will differ — whitelist tests removed, new forbidden type tests added).

- [ ] **Step 6: Commit**

```bash
git add pipeline/wiki_writer.py tests/test_wiki_extractor.py
git commit -m "feat: strategy+overview forbidden in Pass 2; remove slug whitelist"
```

---

## Task 5: Update `pipeline/run_ingest.py` — three-pass orchestration

**Files:**
- Modify: `pipeline/run_ingest.py`
- Modify: `tests/test_run_ingest.py`, `tests/test_ldp.py`

- [ ] **Step 1: Rewrite `run_silver_ingest()` with three-pass flow**

```python
import re
import yaml
from datetime import date
from pathlib import Path
from pipeline.silver_to_gold import extract_quads_from_silver
from pipeline.post_ingest import run_post_ingest
from pipeline.ldp import run_ldp_ingest
from pipeline.holistic_synthesizer import synthesize_source
from pipeline.wiki_index import rebuild_index, append_log


def _should_use_ldp(source_content: str) -> bool:
    m = re.match(r"^---\n(.*?)\n---\n", source_content, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1))
            if fm is not None and "ldp" in fm:
                return bool(fm["ldp"])
        except Exception:
            pass
    lines = source_content.splitlines()
    headings = sum(1 for line in lines if re.match(r"^#{1,4}\s", line))
    return len(lines) > 1000 and headings > 10


def run_silver_ingest(
    source_path: str,
    uuid: str,
    title: str,
    quads_path: str,
    wiki_root: str,
    review_queue_path: str,
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
    wiki_only: bool = False,
):
    """Ingest a source markdown file through the three-pass wiki pipeline.

    Pass 1 (holistic): full-document read → overview + strategy synthesis + index seed
    Pass 2 (chunked, conditional): section-by-section → initiative/actor/location pages
    Pass 3 (finalize): rebuild index.md; seal log.md

    wiki_only=True skips quad extraction (Pass 2 quads) and post-ingest reporting.
    quads_path and review_queue_path are untouched in wiki_only mode.
    """
    if run_date is None:
        run_date = date.today().isoformat()

    source_content = Path(source_path).read_text(encoding="utf-8")
    source_rel_path = str(Path(source_path).with_suffix(""))  # e.g. "sources/cap/cap-2020"

    # Extract source_type from frontmatter
    source_type = "unknown"
    m = re.match(r"^---\n(.*?)\n---\n", source_content, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1))
            if fm:
                source_type = fm.get("source_type", "unknown")
        except Exception:
            pass

    # ── Pass 1: Holistic synthesis (always runs) ──────────────────────────────
    synthesis_result = synthesize_source(
        source_content=source_content,
        source_uuid=uuid,
        source_rel_path=source_rel_path,
        source_type=source_type,
        wiki_root=wiki_root,
        run_date=run_date,
    )

    # Collect stub descriptors from Pass 1 for Pass 2 context.
    # Stubs are already written to disk by _write_synthesis. We pass the full
    # descriptor (slug + title + one-liner) — not just slugs — so Pass 2 can
    # recognize entities even when a chunk uses a different name or abbreviation.
    # Quality and entity resolution accuracy take priority over token economy here.
    known_entities: list[dict] = []
    if synthesis_result:
        known_entities = [
            sp for sp in synthesis_result.get("stub_pages", [])
            if sp.get("slug") and sp.get("title")
        ]

    def _build_entity_context(entities: list[dict]) -> str:
        """Build the known-entity block for Pass 2 chunk context headers."""
        if not entities:
            return ""
        lines = [
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "KNOWN ENTITIES FROM HOLISTIC READ",
            "These entities were identified from the full document by a prior holistic read.",
            "When you encounter any of them — even under a different name or abbreviation —",
            "populate the existing stub rather than creating a duplicate page.",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for e in entities:
            lines.append(
                f"  [[{e['slug']}|{e['title']}]] — {e.get('one-liner', '')}"
            )
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        return "\n".join(lines)

    entity_context = _build_entity_context(known_entities)

    # ── Pass 2: Extraction (conditional on document complexity) ───────────────
    if _should_use_ldp(source_content):
        run_ldp_ingest(
            silver_content=source_content,
            uuid=uuid,
            title=title,
            quads_path=quads_path,
            source_rel_path=source_rel_path,
            wiki_root=wiki_root,
            source_type=source_type,
            section_maps_dir=section_maps_dir,
            run_date=run_date,
            wiki_only=wiki_only,
            entity_context=entity_context,   # prepended to every chunk context header
        )
    else:
        if not wiki_only:
            extract_quads_from_silver(
                silver_content=source_content,
                source_uuid=uuid,
                out_path=quads_path,
            )
        from pipeline.wiki_writer import extract_wiki_pages_from_chunk
        body = re.sub(r"^---\n.*?\n---\n", "", source_content, flags=re.DOTALL).strip()
        extract_wiki_pages_from_chunk(
            chunk_text=body,
            source_uuid=uuid,
            source_rel_path=source_rel_path,
            context_header=entity_context,   # full entity list; 200K window has headroom
            source_type=source_type,
            wiki_root=wiki_root,
            run_date=run_date,
        )

    # ── Pass 3: Finalize index + log ──────────────────────────────────────────
    rebuild_index(wiki_root)
    append_log(
        wiki_root=wiki_root,
        message=f"Pass 3 complete — index rebuilt.",
        source_uuid=uuid,
        run_date=run_date,
    )

    if wiki_only:
        print(f"[ingest] {uuid}: wiki-only run complete — quads and review-queue untouched")
        return None

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

- [ ] **Step 2: Update the CLI `__main__` block**

```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A2Zero ingest pipeline")
    sub = parser.add_subparsers(dest="command")

    p_silver = sub.add_parser("silver", help="Ingest a source markdown file")
    p_silver.add_argument("--source", required=True, help="Path to source .md file")
    p_silver.add_argument("--uuid", required=True)
    p_silver.add_argument("--title", required=True)
    p_silver.add_argument("--quads-path", default="blackboard/quads.jsonl")
    p_silver.add_argument("--wiki-root", default="wiki")
    p_silver.add_argument("--review-queue", default="review-queue.md")
    p_silver.add_argument("--section-maps-dir", default="blackboard/section_maps")
    p_silver.add_argument(
        "--wiki-only", action="store_true", default=False,
        help="Run only Pass 1 + Pass 2 wiki extraction; skip quad extraction and review-queue",
    )

    # ... pdf subparser unchanged ...

    args = parser.parse_args()

    if args.command == "silver":
        run_silver_ingest(
            source_path=args.source,
            uuid=args.uuid,
            title=args.title,
            quads_path=args.quads_path,
            wiki_root=args.wiki_root,
            review_queue_path=args.review_queue,
            section_maps_dir=args.section_maps_dir,
            wiki_only=args.wiki_only,
        )
```

- [ ] **Step 3: Update tests in `tests/test_run_ingest.py` and `tests/test_ldp.py`**

In `tests/test_run_ingest.py`:
- Replace `patch("pipeline.run_ingest.extract_plan_page")` with `patch("pipeline.run_ingest.synthesize_source")`
- Rename `silver_path=` kwargs to `source_path=`
- Add `patch("pipeline.run_ingest.rebuild_index")` and `patch("pipeline.run_ingest.append_log")` to prevent filesystem writes in tests

In `tests/test_ldp.py`:
- Replace `patch("pipeline.run_ingest.extract_plan_page")` with `patch("pipeline.run_ingest.synthesize_source")`
- Rename `silver_relative_path=` to `source_rel_path=` in any direct ldp calls

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -x -q
```
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add pipeline/run_ingest.py tests/test_run_ingest.py tests/test_ldp.py
git commit -m "feat: three-pass orchestration in run_silver_ingest — holistic → chunked → finalize"
```

---

## Task 6: Remove `pipeline/plan_extractor.py`

**Files:**
- Delete: `pipeline/plan_extractor.py`
- Delete: `tests/test_plan_extractor.py`

- [ ] **Step 1: Verify no remaining imports**

```bash
grep -rn "plan_extractor\|extract_plan_page" pipeline/ tests/ --include="*.py"
```
Expected: no output. If any remain, remove them before deleting.

- [ ] **Step 2: Delete the files**

```bash
rm pipeline/plan_extractor.py tests/test_plan_extractor.py
```

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -x -q
```
Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove plan_extractor.py — replaced by holistic_synthesizer.py"
```

---

## Task 7: Archive current wiki output and run clean re-ingest

This task is operational (not code). Run after all prior tasks pass tests.

- [ ] **Step 1: Archive current generated wiki pages (preserve hand-curated stubs)**

```bash
mkdir -p archive/wiki-v3-pre-ingest
cp -r wiki/initiatives wiki/actors wiki/locations wiki/meetings \
      wiki/political-events wiki/technology wiki/plans \
      archive/wiki-v3-pre-ingest/ 2>/dev/null || true

# Remove generated folders from wiki/
rm -rf wiki/initiatives wiki/actors wiki/locations wiki/meetings \
       wiki/political-events wiki/technology wiki/plans \
       wiki/overviews wiki/index.md wiki/log.md wiki/hot.md
```

Strategy stubs and topics are NOT removed — they are hand-curated and will receive bodies from the holistic synthesizer.

- [ ] **Step 2: Verify strategy stubs are clean (no appended bodies from prior runs)**

```bash
cat wiki/strategies/strategy-1-renewable-grid.md
```
Expected: only frontmatter + `<!-- stub -->` comment. If body content exists from prior runs, truncate each stub to frontmatter only.

To reset a stub body:
```bash
# For each strategy file, keep only frontmatter
python3 -c "
import re
from pathlib import Path
for f in Path('wiki/strategies').glob('*.md'):
    content = f.read_text()
    m = re.match(r'^(---\n.*?\n---\n)', content, re.DOTALL)
    if m:
        f.write_text(m.group(1) + '\n<!-- Body populated by holistic synthesizer. Pre-created stub — do not write prose here manually. -->\n')
        print(f'Reset: {f}')
"
```

- [ ] **Step 3: Run the full re-ingest (wiki-only)**

```bash
python -m pipeline.run_ingest silver \
  --source sources/cap/cap-2020.md \
  --uuid cap-2020 \
  --title "Ann Arbor A2Zero Living Carbon Neutrality Plan" \
  --quads-path blackboard/quads.jsonl \
  --wiki-root wiki \
  --review-queue review-queue.md \
  --section-maps-dir blackboard/section_maps \
  --wiki-only
```

Expected console output (in order):
```
[holistic] Overview written: wiki/overviews/cap-2020.md
[holistic] Strategy body appended: strategy-1-renewable-grid.md
... (7 strategy bodies)
[ldp] cap-2020: 148 sections, 28 chunks to extract [wiki-only]
... (chunk-by-chunk page counts)
[wiki_index] Rebuilt index: N pages across M types
[ingest] cap-2020: wiki-only run complete — quads and review-queue untouched
```

- [ ] **Step 4: Verify output quality**

```bash
# Overview page exists and has content
wc -l wiki/overviews/cap-2020.md

# Strategy pages have synthesis bodies (not just stubs)
wc -l wiki/strategies/strategy-1-renewable-grid.md

# Index lists all page types
cat wiki/index.md | head -40

# Log has an entry
cat wiki/log.md
```

- [ ] **Step 5: Final commit**

```bash
git add wiki/ archive/wiki-v3-pre-ingest/
git commit -m "feat: v3 wiki re-ingest — holistic synthesis + chunked extraction + index"
```

---

## Self-Review

**Spec coverage:**
- ✅ `silver/` → `sources/` rename (Task 1)
- ✅ `wiki/index.md` infrastructure (Task 2)
- ✅ `wiki/log.md` infrastructure (Task 2)
- ✅ `wiki/hot.md` infrastructure (Task 2)
- ✅ Holistic read first — Writer → Evaluator → Editor loop (Task 3)
- ✅ `stub_pages` from Writer → stubs written before Pass 2 (Task 3, `_write_synthesis`)
- ✅ `topic_candidates` from Writer → `wiki/meta/topic-candidates.md` (Task 3, `_write_synthesis`)
- ✅ `structure:` field in overview frontmatter (Writer system prompt, Task 3)
- ✅ Prompt caching on `[FULL DOCUMENT]` block via `cache_control` (Task 3, `_llm_call`)
- ✅ Per-step max_tokens: Writer 16384, Evaluator 4096, Editor 16384 (Task 3)
- ✅ Per-step token usage logged to console (Task 3, `_llm_call`)
- ✅ Writer retry receives accuracy_issues feedback from Evaluator (Task 3, `synthesize_source`)
- ✅ Overview page replaces plan page (Task 3, VALID_PAGE_TYPES)
- ✅ Strategy bodies holistic only — `PASS2_FORBIDDEN_TYPES` (Task 4, renamed from PASS3)
- ✅ Schema-drift logging for unknown types → `wiki/meta/schema-drift.md` (Task 4)
- ✅ Known entity list from Pass 1 stubs passed to Pass 2 context (Task 5)
- ✅ Three-pass orchestration with `synthesis_result` threaded through (Task 5)
- ✅ `plan_extractor.py` removed (Task 6)
- ✅ Clean re-ingest (Task 7)

**Gaps noted:**
- `hot.md` is created by `update_hot()` (Task 2) but no caller invokes it yet.
  Add a call at the end of `run_silver_ingest()` Pass 3, assembling the summary from
  the overview body's first paragraph + ingest counts. Implement in a follow-up.
- `wiki/meta/relationship-lexicon.md` is referenced in SCHEMA.md but not created by
  the pipeline. Pre-seed it manually before first ingest (one-time setup, not automated).
- The Writer system prompt uses `.format()` with `{source_uuid}`, `{source_path}`,
  `{run_date}` — all literal JSON braces in the prompt must use `{{` `}}`.
  The implementation above does this correctly; implementer should verify no
  brace-escape issues after writing the file.
- `uuid:` field (SHA-256 of type + normalized title) is specified in SCHEMA.md but
  not yet implemented in `build_wiki_page()`. Add in a follow-up to `silver_to_gold.py`.
