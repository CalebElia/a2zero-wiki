# synthesize_wiki Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase C synthesis command — `python -m pipeline.synthesize_wiki` — which reads the clean post-lint wiki, rebuilds strategy synthesis sections (L1), and writes `wiki/digest.md` (L2) for injection into the next ingest's Comprehend pass.

**Architecture:** This is Step 1 of the four-step knowledge synthesis architecture defined in `docs/architecture/knowledge-synthesis-architecture.md`. It introduces the L1→L2 hierarchy. Subsequent steps (digest injection into Comprehend, Comprehend/Plan split, schema formalization) build on top of this foundation in later plans.

**Tech Stack:** Python 3.13, `anthropic` SDK (mocked in tests), `pyyaml`, `pytest`.

**Reference reading:** Before starting, read:
- `docs/architecture/knowledge-synthesis-architecture.md` — locked design decisions
- `pipeline/merge_pages.py` + `tests/test_merge_pages.py` — canonical pattern for LLM call + mock
- `pipeline/lint_wiki.py` — pattern for reading entity frontmatter at scale
- `pipeline/wiki_index.py` — pattern for writing structured artifacts to the vault root

---

## File Structure

**Create:**
- `pipeline/synthesize_wiki.py` — the new module
- `tests/test_synthesize_wiki.py` — test suite
- `tests/fixtures/synthesize_wiki/` — fixture wiki tree for integration test

**Modify (final task only):**
- `CLAUDE.md` — add command to the on-demand commands list
- `CHANGELOG.md` — top entry for this feature

---

## Domain Notes (read before writing tests)

**Strategy slug → frontmatter key.** Every entity page may carry a `related-strategies:` field listing one or more strategy slugs. The format in existing pages is a YAML list:

```yaml
related-strategies:
  - strategies/strategy-1-renewable-grid
  - strategies/strategy-3-building-efficiency
```

The 7 canonical strategy slugs (full vault paths):
- `strategies/strategy-1-renewable-grid`
- `strategies/strategy-2-electrification`
- `strategies/strategy-3-building-efficiency`
- `strategies/strategy-4-vmt-reduction`
- `strategies/strategy-5-materials-waste`
- `strategies/strategy-6-resilience`
- `strategies/strategy-7-engagement`

**Stub detection** (matches existing pattern, e.g. `pipeline/wiki_writer.py`):
```python
body_stripped = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
is_stub = not bool(body_stripped)
```

**LLM call pattern** (from `pipeline/merge_pages.py`):
```python
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}],
)
text = response.content[0].text
```

For prompts producing structured output, parse JSON from the response with a code-fence stripper (see existing `lint_wiki._llm_filter_candidates` for the canonical strip + parse pattern).

**Synthesis block schema.** What `build_strategy_synthesis()` produces and `write_strategy_synthesis()` injects:

```yaml
synthesis:
  core-initiatives:
    - initiatives/solarize-ann-arbor
    - initiatives/wheeler-center-solar-park
  core-actors:
    - actors/great-lakes-renewable-energy-association
    - actors/office-of-sustainability-and-innovations
  year-over-year-arc: "Residential solar grew 31% Y1→Y2; commercial pilot just launched."
  open-questions:
    - "DTE intervention outcomes (cases u-20713, u-20836) pending"
    - "5MW Y3 target — on track?"
  cross-strategy-links:
    - initiatives/bryant-neighborhood-decarbonization
    - initiatives/sustainable-energy-utility
  last-rebuilt: "2026-06-26"
```

**Digest schema** (`wiki/digest.md`):

```markdown
---
generated-by: synthesize_wiki
last-rebuilt: 2026-06-26
sources-covered: 3
entity-count: 399
---

# Wiki Digest
*State of A2Zero knowledge as of 2026-06-26 (post-Year-2 ingest, post-lint).*

## Cross-strategy synthesis
<LLM-written prose narrative — 1 paragraph per strategy + closing
paragraph on cross-strategy connections.>

## Strategy entity map
### [[strategies/strategy-1-renewable-grid|Strategy 1 — Renewable Grid]]
- **core initiatives:** [[initiatives/solarize-ann-arbor]], [[initiatives/wheeler-center-solar-park]], ...
- **core actors:** [[actors/glrea]], [[actors/osi]], ...
- **arc:** Residential solar grew 31% Y1→Y2.
- **open:** DTE intervention outcomes pending.

### Strategy 2 — ...

## Recent delta
**Last ingest:** [[sources/annual-reports/a2zero-year2|a2zero-year2]] (2026-06-26).
- Added 148 pages.
- Notable new entities: [[initiatives/a2r3-reduce-reuse-return]], [[initiatives/electrification-expo]], ...
```

---

## Task 1: Module skeleton + CLI entry point

**Files:**
- Create: `pipeline/synthesize_wiki.py`
- Create: `tests/test_synthesize_wiki.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synthesize_wiki.py
import pytest
from unittest.mock import MagicMock


def test_module_imports():
    """Smoke test: the module exists and exposes the expected public API."""
    from pipeline import synthesize_wiki
    assert hasattr(synthesize_wiki, "synthesize_wiki")
    assert callable(synthesize_wiki.synthesize_wiki)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_synthesize_wiki.py::test_module_imports -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# pipeline/synthesize_wiki.py
"""Phase C of the ingest cycle: build the L1 strategy synthesis sections
and the L2 wiki/digest.md from the clean post-lint entity layer.

See docs/architecture/knowledge-synthesis-architecture.md for design rationale.
"""
from pathlib import Path


def synthesize_wiki(
    wiki_root: str,
    strategies: list[str] | None = None,
    digest_only: bool = False,
    aliases_path: str = "registry/entity_aliases.json",
) -> dict:
    """Phase C orchestration: rebuild L1 synthesis sections + write digest.md.

    Args:
        wiki_root: vault root path (typically "wiki").
        strategies: optional list of strategy slugs to rebuild. If None,
            rebuild all 7 strategy pages.
        digest_only: skip L1 rebuild, just regenerate digest.md from existing
            synthesis: blocks.

    Returns:
        dict with keys: `strategies_rebuilt` (list of slugs), `digest_path`.
    """
    raise NotImplementedError("Pending tasks 2-9")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="A2Zero wiki synthesis — Phase C of the ingest cycle"
    )
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help="rebuild only this strategy (repeatable). Default: all 7.",
    )
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="skip L1 rebuild; regenerate digest.md from existing synthesis: blocks",
    )
    args = parser.parse_args()

    result = synthesize_wiki(
        wiki_root=args.wiki_root,
        strategies=args.strategies,
        digest_only=args.digest_only,
    )
    print(f"[synthesize_wiki] rebuilt {len(result['strategies_rebuilt'])} strategies")
    print(f"[synthesize_wiki] wrote digest → {result['digest_path']}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_synthesize_wiki.py::test_module_imports -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py
git commit -m "feat(synthesize_wiki): module skeleton + CLI entry point"
```

---

## Task 2: `gather_strategy_entities()` — collect entities by strategy

Scans entity pages and returns those whose `related-strategies:` frontmatter includes the given strategy slug.

**Files:**
- Modify: `pipeline/synthesize_wiki.py`
- Modify: `tests/test_synthesize_wiki.py`
- Create: `tests/fixtures/synthesize_wiki/wiki/` (minimal entity tree)

- [ ] **Step 1: Build the test fixture**

```bash
mkdir -p tests/fixtures/synthesize_wiki/wiki/initiatives
mkdir -p tests/fixtures/synthesize_wiki/wiki/actors
```

Create `tests/fixtures/synthesize_wiki/wiki/initiatives/solarize-ann-arbor.md`:
```markdown
---
title: "Solarize Ann Arbor"
type: initiative
slug: initiatives/solarize-ann-arbor
related-strategies:
  - strategies/strategy-1-renewable-grid
source-first-seen: "[[sources/cap/cap-2020]]"
one-liner: "Residential rooftop solar bulk-buy program — 430+ homes through Year 2."
---

Solarize Ann Arbor is a residential rooftop solar program. ([[sources/cap/cap-2020|cap-2020]])
```

Create `tests/fixtures/synthesize_wiki/wiki/actors/glrea.md`:
```markdown
---
title: "Great Lakes Renewable Energy Association"
type: actor
slug: actors/glrea
related-strategies:
  - strategies/strategy-1-renewable-grid
source-first-seen: "[[sources/cap/cap-2020]]"
one-liner: "Nonprofit advancing renewable energy across the Great Lakes region."
---

GLREA leads the Solarize Ann Arbor program. ([[sources/cap/cap-2020|cap-2020]])
```

Create `tests/fixtures/synthesize_wiki/wiki/initiatives/electrification-campaign.md`:
```markdown
---
title: "Electrification Campaign"
type: initiative
slug: initiatives/electrification-campaign
related-strategies:
  - strategies/strategy-2-electrification
source-first-seen: "[[sources/annual-reports/a2zero-year2]]"
one-liner: "Public-facing campaign promoting home electrification."
---

The campaign drives residential heat pump and induction stove adoption.
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_synthesize_wiki.py`:

```python
def test_gather_strategy_entities_filters_by_strategy(tmp_path):
    """Returns only entities tagged to the given strategy."""
    import shutil
    from pipeline.synthesize_wiki import gather_strategy_entities

    fixture = "tests/fixtures/synthesize_wiki/wiki"
    shutil.copytree(fixture, tmp_path / "wiki")

    entities = gather_strategy_entities(
        wiki_root=str(tmp_path / "wiki"),
        strategy_slug="strategies/strategy-1-renewable-grid",
    )
    titles = sorted(e["title"] for e in entities)
    assert titles == ["Great Lakes Renewable Energy Association", "Solarize Ann Arbor"]

    # Each entity dict carries the keys the downstream LLM prompt expects
    for e in entities:
        assert set(e.keys()) >= {"slug", "title", "type", "one-liner"}


def test_gather_strategy_entities_returns_empty_for_unknown_strategy(tmp_path):
    import shutil
    from pipeline.synthesize_wiki import gather_strategy_entities
    shutil.copytree("tests/fixtures/synthesize_wiki/wiki", tmp_path / "wiki")
    entities = gather_strategy_entities(
        wiki_root=str(tmp_path / "wiki"),
        strategy_slug="strategies/strategy-99-nonexistent",
    )
    assert entities == []
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python -m pytest tests/test_synthesize_wiki.py::test_gather_strategy_entities_filters_by_strategy -v
```
Expected: FAIL with `ImportError: cannot import name 'gather_strategy_entities'`.

- [ ] **Step 4: Implement**

Add to `pipeline/synthesize_wiki.py`:

```python
import re
import yaml

_ENTITY_DIRS = [
    "actors", "initiatives", "locations", "technology",
    "funding-events", "meetings", "political-events",
]


def _parse_frontmatter(text: str) -> dict:
    """Return the YAML frontmatter as a dict, or {} if missing/invalid."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def gather_strategy_entities(wiki_root: str, strategy_slug: str) -> list[dict]:
    """Return entity dicts for every page tagged with this strategy.

    Each dict has: slug, title, type, one-liner.
    Used by build_strategy_synthesis() to feed the LLM the entity inventory.
    """
    root = Path(wiki_root)
    out: list[dict] = []
    for type_dir in _ENTITY_DIRS:
        for page in (root / type_dir).glob("*.md"):
            text = page.read_text(encoding="utf-8", errors="replace")
            fm = _parse_frontmatter(text)
            related = fm.get("related-strategies") or []
            if isinstance(related, str):
                related = [related]
            if strategy_slug not in related:
                continue
            out.append({
                "slug": fm.get("slug") or f"{type_dir}/{page.stem}",
                "title": fm.get("title", page.stem),
                "type": fm.get("type", type_dir.rstrip("s")),
                "one-liner": fm.get("one-liner", ""),
            })
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_synthesize_wiki.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py tests/fixtures/synthesize_wiki/
git commit -m "feat(synthesize_wiki): gather_strategy_entities() — scan entity layer by strategy"
```

---

## Task 3: `extract_recent_delta()` — pull last ingest from log.md

The digest's "recent delta" section needs to know which source was most recently ingested and what notable entities it added. We extract this from `wiki/log.md`, which the existing `wiki_index.append_log()` maintains.

**Files:**
- Modify: `pipeline/synthesize_wiki.py`
- Modify: `tests/test_synthesize_wiki.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesize_wiki.py`:

```python
LOG_FIXTURE = """# Ingest Log

## 2026-06-15 — cap-2020
Pass 3 complete — index rebuilt.

## 2026-06-25 — a2zero-year1
Pass 3 complete — index rebuilt.

## 2026-06-26 — a2zero-year2
Pass 3 complete — index rebuilt.
"""


def test_extract_recent_delta_returns_last_entry(tmp_path):
    from pipeline.synthesize_wiki import extract_recent_delta
    log_path = tmp_path / "log.md"
    log_path.write_text(LOG_FIXTURE, encoding="utf-8")
    delta = extract_recent_delta(str(log_path))
    assert delta["source_uuid"] == "a2zero-year2"
    assert delta["date"] == "2026-06-26"


def test_extract_recent_delta_handles_empty_log(tmp_path):
    from pipeline.synthesize_wiki import extract_recent_delta
    log_path = tmp_path / "log.md"
    log_path.write_text("# Ingest Log\n", encoding="utf-8")
    delta = extract_recent_delta(str(log_path))
    assert delta == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_synthesize_wiki.py::test_extract_recent_delta_returns_last_entry -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Add to `pipeline/synthesize_wiki.py`:

```python
_LOG_ENTRY_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+?)$", re.MULTILINE)


def extract_recent_delta(log_path: str) -> dict:
    """Return {date, source_uuid} for the most recent ingest in log.md, or {}."""
    try:
        text = Path(log_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    matches = _LOG_ENTRY_RE.findall(text)
    if not matches:
        return {}
    date, source_uuid = matches[-1]
    return {"date": date, "source_uuid": source_uuid.strip()}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_synthesize_wiki.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py
git commit -m "feat(synthesize_wiki): extract_recent_delta() — parse last ingest from log.md"
```

---

## Task 4: `build_strategy_synthesis()` — LLM call producing the synthesis dict

Takes the entity inventory for one strategy and asks the LLM to produce a structured synthesis: core initiatives, core actors, year-over-year arc, open questions, cross-strategy links.

**Files:**
- Modify: `pipeline/synthesize_wiki.py`
- Modify: `tests/test_synthesize_wiki.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesize_wiki.py`:

```python
import json
from unittest.mock import patch, MagicMock


def _mock_response(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.stop_reason = "end_turn"
    return msg


SAMPLE_ENTITIES = [
    {"slug": "initiatives/solarize-ann-arbor", "title": "Solarize Ann Arbor",
     "type": "initiative", "one-liner": "Residential solar bulk-buy."},
    {"slug": "actors/glrea", "title": "Great Lakes Renewable Energy Association",
     "type": "actor", "one-liner": "Nonprofit leading Solarize."},
]


def test_build_strategy_synthesis_calls_anthropic_and_returns_dict():
    from pipeline.synthesize_wiki import build_strategy_synthesis

    llm_output = json.dumps({
        "core-initiatives": ["initiatives/solarize-ann-arbor"],
        "core-actors": ["actors/glrea"],
        "year-over-year-arc": "Residential solar grew 31% Y1→Y2.",
        "open-questions": ["5MW Y3 target on track?"],
        "cross-strategy-links": [],
    })
    with patch("pipeline.synthesize_wiki.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = _mock_response(llm_output)
        result = build_strategy_synthesis(
            strategy_slug="strategies/strategy-1-renewable-grid",
            strategy_title="Strategy 1 — Renewable Grid",
            entities=SAMPLE_ENTITIES,
        )
    assert result["core-initiatives"] == ["initiatives/solarize-ann-arbor"]
    assert result["year-over-year-arc"].startswith("Residential")


def test_build_strategy_synthesis_handles_fenced_json():
    from pipeline.synthesize_wiki import build_strategy_synthesis
    llm_output = "```json\n" + json.dumps({
        "core-initiatives": [], "core-actors": [],
        "year-over-year-arc": "—", "open-questions": [], "cross-strategy-links": [],
    }) + "\n```"
    with patch("pipeline.synthesize_wiki.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = _mock_response(llm_output)
        result = build_strategy_synthesis(
            strategy_slug="strategies/strategy-1-renewable-grid",
            strategy_title="Strategy 1 — Renewable Grid",
            entities=SAMPLE_ENTITIES,
        )
    assert result["core-initiatives"] == []


def test_build_strategy_synthesis_returns_empty_skeleton_on_api_failure():
    from pipeline.synthesize_wiki import build_strategy_synthesis
    with patch("pipeline.synthesize_wiki.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = Exception("api error")
        result = build_strategy_synthesis(
            strategy_slug="strategies/strategy-1-renewable-grid",
            strategy_title="Strategy 1 — Renewable Grid",
            entities=SAMPLE_ENTITIES,
        )
    assert "core-initiatives" in result
    assert result["core-initiatives"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_synthesize_wiki.py::test_build_strategy_synthesis_calls_anthropic_and_returns_dict -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Add to `pipeline/synthesize_wiki.py`:

```python
import json
import anthropic


_STRATEGY_SYNTHESIS_SYSTEM = """You are synthesizing one strategy of Ann Arbor's A2Zero \
carbon neutrality plan into a compact structured summary that will be injected into \
future LLM ingest passes as prior context.

Given the strategy and its inventory of entity pages, return JSON with EXACTLY these keys:
- core-initiatives: list of up to 8 slugs of the most important initiatives (most \
central to the strategy's outcomes)
- core-actors: list of up to 6 slugs of the most important actors
- year-over-year-arc: one sentence describing the trajectory across ingested sources \
(e.g. "Residential solar grew 31% Y1→Y2; commercial pilot launched"). If only one \
source is ingested, describe the baseline state.
- open-questions: list of 2–4 short strings flagging what is unresolved or pending
- cross-strategy-links: list of slugs of entities you would expect to also appear in \
other strategies' core-initiatives (initiatives spanning multiple strategies)

Return ONLY the JSON object. Slugs use the form `actors/foo` or `initiatives/bar` — \
the same format as the inputs.
"""


def _strip_code_fence(text: str) -> str:
    """Strip ```json fences if present."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:-1]) if len(lines) > 2 else t
    return t.strip()


def _empty_synthesis() -> dict:
    return {
        "core-initiatives": [],
        "core-actors": [],
        "year-over-year-arc": "—",
        "open-questions": [],
        "cross-strategy-links": [],
    }


def build_strategy_synthesis(
    strategy_slug: str,
    strategy_title: str,
    entities: list[dict],
) -> dict:
    """LLM call: produce the synthesis dict for one strategy."""
    entity_lines = "\n".join(
        f"- [{e['type']}] {e['slug']} — {e['title']}: {e.get('one-liner','')}"
        for e in entities
    )
    user_msg = (
        f"Strategy: {strategy_title} ({strategy_slug})\n\n"
        f"Entity inventory ({len(entities)} pages):\n{entity_lines}\n\n"
        "Produce the synthesis JSON now."
    )
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            system=_STRATEGY_SYNTHESIS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text
        return json.loads(_strip_code_fence(raw))
    except Exception as e:
        print(f"[synthesize_wiki] build_strategy_synthesis failed for {strategy_slug}: {e}")
        return _empty_synthesis()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_synthesize_wiki.py -v
```
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py
git commit -m "feat(synthesize_wiki): build_strategy_synthesis() — LLM call for L1 synthesis dict"
```

---

## Task 5: `write_strategy_synthesis()` — inject synthesis: block, preserve prose

Takes a strategy page path + a synthesis dict and writes the dict into the page's YAML frontmatter under a `synthesis:` key, leaving the human-written prose body untouched.

**Files:**
- Modify: `pipeline/synthesize_wiki.py`
- Modify: `tests/test_synthesize_wiki.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesize_wiki.py`:

```python
STRATEGY_FIXTURE = """---
title: "Strategy 1 — Renewable Grid"
type: strategy
slug: strategies/strategy-1-renewable-grid
---

This strategy focuses on grid-scale renewable energy and rooftop solar.
The Solarize program is the flagship initiative. ([[sources/cap/cap-2020|cap-2020]])
"""


def test_write_strategy_synthesis_injects_synthesis_block(tmp_path):
    from pipeline.synthesize_wiki import write_strategy_synthesis
    page = tmp_path / "strategy-1-renewable-grid.md"
    page.write_text(STRATEGY_FIXTURE, encoding="utf-8")

    synthesis = {
        "core-initiatives": ["initiatives/solarize-ann-arbor"],
        "core-actors": ["actors/glrea"],
        "year-over-year-arc": "Residential solar grew 31% Y1→Y2.",
        "open-questions": ["5MW Y3 target on track?"],
        "cross-strategy-links": [],
    }
    write_strategy_synthesis(str(page), synthesis, run_date="2026-06-26")
    text = page.read_text(encoding="utf-8")

    # Synthesis block lives in frontmatter
    assert "synthesis:" in text
    assert "core-initiatives:" in text
    assert "initiatives/solarize-ann-arbor" in text
    assert "last-rebuilt: '2026-06-26'" in text or 'last-rebuilt: "2026-06-26"' in text

    # Prose body is preserved
    assert "This strategy focuses on grid-scale renewable energy" in text
    assert "Solarize program is the flagship initiative" in text


def test_write_strategy_synthesis_overwrites_existing_block(tmp_path):
    from pipeline.synthesize_wiki import write_strategy_synthesis
    page = tmp_path / "s1.md"
    page.write_text(STRATEGY_FIXTURE, encoding="utf-8")
    write_strategy_synthesis(str(page),
        {"core-initiatives": ["initiatives/old"],
         "core-actors": [], "year-over-year-arc": "old",
         "open-questions": [], "cross-strategy-links": []},
        run_date="2026-06-01")
    write_strategy_synthesis(str(page),
        {"core-initiatives": ["initiatives/new"],
         "core-actors": [], "year-over-year-arc": "new",
         "open-questions": [], "cross-strategy-links": []},
        run_date="2026-06-26")
    text = page.read_text(encoding="utf-8")
    assert "initiatives/new" in text
    assert "initiatives/old" not in text
    # Prose body still present and intact
    assert "Solarize program is the flagship initiative" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_synthesize_wiki.py::test_write_strategy_synthesis_injects_synthesis_block -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Add to `pipeline/synthesize_wiki.py`:

```python
def write_strategy_synthesis(
    page_path: str,
    synthesis: dict,
    run_date: str,
) -> None:
    """Inject `synthesis:` block into the strategy page frontmatter. Preserve prose body."""
    page = Path(page_path)
    text = page.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError(f"No YAML frontmatter found in {page_path}")
    fm_text, body = m.group(1), m.group(2)
    fm = yaml.safe_load(fm_text) or {}

    # Stamp the rebuild date onto the synthesis block itself
    block = dict(synthesis)
    block["last-rebuilt"] = run_date
    fm["synthesis"] = block

    new_fm = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    page.write_text(f"---\n{new_fm}\n---\n{body}", encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_synthesize_wiki.py -v
```
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py
git commit -m "feat(synthesize_wiki): write_strategy_synthesis() — inject block, preserve prose"
```

---

## Task 6: `build_digest_narrative()` — LLM call producing cross-strategy prose

Takes the dict of {strategy_slug: synthesis_dict} for all 7 strategies and produces the narrative section of digest.md.

**Files:**
- Modify: `pipeline/synthesize_wiki.py`
- Modify: `tests/test_synthesize_wiki.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesize_wiki.py`:

```python
SAMPLE_STRATEGIES_DATA = {
    "strategies/strategy-1-renewable-grid": {
        "title": "Strategy 1 — Renewable Grid",
        "synthesis": {
            "core-initiatives": ["initiatives/solarize-ann-arbor"],
            "core-actors": ["actors/glrea"],
            "year-over-year-arc": "Residential solar grew 31% Y1→Y2.",
            "open-questions": ["DTE intervention outcomes pending"],
            "cross-strategy-links": ["initiatives/bryant-neighborhood-decarbonization"],
        },
    },
    "strategies/strategy-2-electrification": {
        "title": "Strategy 2 — Electrification",
        "synthesis": {
            "core-initiatives": ["initiatives/electrification-campaign"],
            "core-actors": ["actors/rmi"],
            "year-over-year-arc": "Contractor cohort launched Y2.",
            "open-questions": ["Heat pump adoption uptake?"],
            "cross-strategy-links": [],
        },
    },
}


def test_build_digest_narrative_calls_anthropic():
    from pipeline.synthesize_wiki import build_digest_narrative
    narrative_text = (
        "## Cross-strategy synthesis\n\n"
        "Strategy 1 has built a 1.7MW residential rooftop base anchored by "
        "[[initiatives/solarize-ann-arbor]]...\n"
    )
    with patch("pipeline.synthesize_wiki.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = _mock_response(narrative_text)
        result = build_digest_narrative(strategies_data=SAMPLE_STRATEGIES_DATA)
    assert "Strategy 1" in result
    assert "[[initiatives/solarize-ann-arbor]]" in result


def test_build_digest_narrative_returns_placeholder_on_failure():
    from pipeline.synthesize_wiki import build_digest_narrative
    with patch("pipeline.synthesize_wiki.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = Exception("api error")
        result = build_digest_narrative(strategies_data=SAMPLE_STRATEGIES_DATA)
    # Falls back to a placeholder rather than crashing the synthesis run
    assert "Cross-strategy synthesis" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_synthesize_wiki.py::test_build_digest_narrative_calls_anthropic -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Add to `pipeline/synthesize_wiki.py`:

```python
_DIGEST_NARRATIVE_SYSTEM = """You write the narrative cross-strategy section of \
Ann Arbor's A2Zero wiki digest. This will be read by future LLM ingest passes as \
prior context, AND by humans skimming the current state of the wiki.

Given a structured summary of each of the 7 A2Zero strategies (the synthesis dicts), \
produce markdown prose. Required structure:

## Cross-strategy synthesis

<One short paragraph per strategy — what it has accomplished, the year-over-year \
arc, key actors. Reference entities as Obsidian wikilinks: [[initiatives/foo]] or \
[[actors/bar]]. Keep each paragraph to 3–5 sentences.>

<Closing paragraph titled "### Connections" describing where strategies intersect \
— which initiatives or actors span multiple strategies, where work in one strategy \
constrains or enables another. 4–6 sentences.>

Return ONLY the markdown — no preamble, no code fences.
"""


def build_digest_narrative(strategies_data: dict) -> str:
    """LLM call: produce the cross-strategy narrative section of digest.md."""
    lines = []
    for slug, info in strategies_data.items():
        s = info["synthesis"]
        lines.append(f"\n### {info['title']} ({slug})")
        lines.append(f"core-initiatives: {', '.join(s.get('core-initiatives', []))}")
        lines.append(f"core-actors: {', '.join(s.get('core-actors', []))}")
        lines.append(f"arc: {s.get('year-over-year-arc', '—')}")
        lines.append(f"open: {'; '.join(s.get('open-questions', []))}")
        lines.append(f"cross-strategy-links: {', '.join(s.get('cross-strategy-links', []))}")

    user_msg = "Strategy summaries:\n" + "\n".join(lines) + "\n\nWrite the narrative now."

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=_DIGEST_NARRATIVE_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[synthesize_wiki] build_digest_narrative failed: {e}")
        return (
            "## Cross-strategy synthesis\n\n"
            "_Narrative generation failed; rerun `synthesize_wiki` to retry._\n"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_synthesize_wiki.py -v
```
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py
git commit -m "feat(synthesize_wiki): build_digest_narrative() — LLM call for L2 cross-strategy prose"
```

---

## Task 7: `assemble_digest()` + `write_digest()` — full digest.md

Pure function that combines the narrative, the structured entity map, and the recent delta into one markdown string, then writes it to `wiki/digest.md`.

**Files:**
- Modify: `pipeline/synthesize_wiki.py`
- Modify: `tests/test_synthesize_wiki.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesize_wiki.py`:

```python
def test_assemble_digest_combines_all_sections():
    from pipeline.synthesize_wiki import assemble_digest
    text = assemble_digest(
        narrative="## Cross-strategy synthesis\n\nStrategy 1 ...\n",
        strategies_data=SAMPLE_STRATEGIES_DATA,
        delta={"date": "2026-06-26", "source_uuid": "a2zero-year2"},
        run_date="2026-06-26",
        sources_count=3,
        entity_count=399,
    )
    # Frontmatter
    assert text.startswith("---\n")
    assert "generated-by: synthesize_wiki" in text
    assert "last-rebuilt: '2026-06-26'" in text or 'last-rebuilt: "2026-06-26"' in text
    # Narrative section
    assert "Cross-strategy synthesis" in text
    # Entity map section
    assert "## Strategy entity map" in text
    assert "[[initiatives/solarize-ann-arbor]]" in text
    # Recent delta section
    assert "## Recent delta" in text
    assert "a2zero-year2" in text


def test_write_digest_writes_to_vault_root(tmp_path):
    from pipeline.synthesize_wiki import write_digest
    (tmp_path / "wiki").mkdir()
    out = write_digest(wiki_root=str(tmp_path / "wiki"), content="# Hello digest")
    assert (tmp_path / "wiki" / "digest.md").read_text(encoding="utf-8") == "# Hello digest"
    assert out.endswith("wiki/digest.md")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_synthesize_wiki.py::test_assemble_digest_combines_all_sections -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Add to `pipeline/synthesize_wiki.py`:

```python
def assemble_digest(
    narrative: str,
    strategies_data: dict,
    delta: dict,
    run_date: str,
    sources_count: int,
    entity_count: int,
) -> str:
    """Combine narrative + entity map + recent delta into the digest.md body."""
    parts = [
        "---",
        "generated-by: synthesize_wiki",
        f"last-rebuilt: '{run_date}'",
        f"sources-covered: {sources_count}",
        f"entity-count: {entity_count}",
        "---",
        "",
        "# Wiki Digest",
        f"*State of A2Zero knowledge as of {run_date} "
        f"(after {sources_count} ingested sources).*",
        "",
        narrative.strip(),
        "",
        "## Strategy entity map",
        "",
    ]
    for slug, info in strategies_data.items():
        s = info["synthesis"]
        parts.append(f"### [[{slug}|{info['title']}]]")
        if s.get("core-initiatives"):
            inits = ", ".join(f"[[{x}]]" for x in s["core-initiatives"])
            parts.append(f"- **core initiatives:** {inits}")
        if s.get("core-actors"):
            actors = ", ".join(f"[[{x}]]" for x in s["core-actors"])
            parts.append(f"- **core actors:** {actors}")
        parts.append(f"- **arc:** {s.get('year-over-year-arc', '—')}")
        if s.get("open-questions"):
            parts.append(f"- **open:** {'; '.join(s['open-questions'])}")
        if s.get("cross-strategy-links"):
            xs = ", ".join(f"[[{x}]]" for x in s["cross-strategy-links"])
            parts.append(f"- **cross-strategy links:** {xs}")
        parts.append("")

    parts.append("## Recent delta")
    if delta:
        parts.append(f"**Last ingest:** [[sources/.../{delta['source_uuid']}|"
                     f"{delta['source_uuid']}]] ({delta['date']}).")
    else:
        parts.append("_No ingest log entries found._")
    parts.append("")

    return "\n".join(parts)


def write_digest(wiki_root: str, content: str) -> str:
    """Write digest.md to vault root. Returns the absolute path."""
    out = Path(wiki_root) / "digest.md"
    out.write_text(content, encoding="utf-8")
    return str(out)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_synthesize_wiki.py -v
```
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py
git commit -m "feat(synthesize_wiki): assemble_digest() + write_digest() — write wiki/digest.md"
```

---

## Task 8: Wire orchestration in `synthesize_wiki()`

Replace the `NotImplementedError` skeleton with the full Phase C orchestration: gather entities per strategy → build synthesis → write strategy pages → assemble digest → write digest.

**Files:**
- Modify: `pipeline/synthesize_wiki.py`
- Modify: `tests/test_synthesize_wiki.py`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_synthesize_wiki.py`:

```python
def _setup_full_fixture(tmp_path):
    """Stage a minimal but complete wiki fixture for end-to-end orchestration."""
    import shutil
    root = tmp_path / "wiki"
    shutil.copytree("tests/fixtures/synthesize_wiki/wiki", root)
    (root / "strategies").mkdir(parents=True, exist_ok=True)
    (root / "strategies" / "strategy-1-renewable-grid.md").write_text(
        STRATEGY_FIXTURE, encoding="utf-8")
    (root / "log.md").write_text(LOG_FIXTURE, encoding="utf-8")
    return root


def test_synthesize_wiki_orchestrates_end_to_end(tmp_path):
    from pipeline.synthesize_wiki import synthesize_wiki

    root = _setup_full_fixture(tmp_path)
    strategy_llm_output = json.dumps({
        "core-initiatives": ["initiatives/solarize-ann-arbor"],
        "core-actors": ["actors/glrea"],
        "year-over-year-arc": "Residential solar grew 31% Y1→Y2.",
        "open-questions": [],
        "cross-strategy-links": [],
    })
    narrative_output = "## Cross-strategy synthesis\n\nStrategy 1 has solarized 430+ homes.\n"

    with patch("pipeline.synthesize_wiki.anthropic.Anthropic") as MockClient:
        # Strategy synthesis call returns the JSON; digest narrative call returns prose.
        # Match call order: 1 strategy (since we limit to strategy-1) then 1 narrative.
        responses = [_mock_response(strategy_llm_output), _mock_response(narrative_output)]
        MockClient.return_value.messages.create.side_effect = responses

        result = synthesize_wiki(
            wiki_root=str(root),
            strategies=["strategies/strategy-1-renewable-grid"],
        )

    assert result["strategies_rebuilt"] == ["strategies/strategy-1-renewable-grid"]
    assert (root / "digest.md").exists()
    digest_text = (root / "digest.md").read_text(encoding="utf-8")
    assert "Strategy 1 has solarized 430+ homes" in digest_text
    strategy_text = (root / "strategies" / "strategy-1-renewable-grid.md").read_text(encoding="utf-8")
    assert "synthesis:" in strategy_text
    assert "Solarize program is the flagship initiative" in strategy_text  # prose preserved
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_synthesize_wiki.py::test_synthesize_wiki_orchestrates_end_to_end -v
```
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement orchestration**

Replace the `synthesize_wiki()` body in `pipeline/synthesize_wiki.py`:

```python
ALL_STRATEGIES = [
    "strategies/strategy-1-renewable-grid",
    "strategies/strategy-2-electrification",
    "strategies/strategy-3-building-efficiency",
    "strategies/strategy-4-vmt-reduction",
    "strategies/strategy-5-materials-waste",
    "strategies/strategy-6-resilience",
    "strategies/strategy-7-engagement",
]


def _read_strategy_title(wiki_root: str, strategy_slug: str) -> str:
    page = Path(wiki_root) / (strategy_slug + ".md")
    if not page.exists():
        return strategy_slug
    fm = _parse_frontmatter(page.read_text(encoding="utf-8"))
    return fm.get("title", strategy_slug)


def _count_entities(wiki_root: str) -> int:
    root = Path(wiki_root)
    return sum(len(list((root / d).glob("*.md"))) for d in _ENTITY_DIRS if (root / d).exists())


def _count_sources(wiki_root: str) -> int:
    sources_dir = Path(wiki_root) / "sources"
    if not sources_dir.exists():
        return 0
    return sum(1 for p in sources_dir.rglob("*.md"))


def synthesize_wiki(
    wiki_root: str,
    strategies: list[str] | None = None,
    digest_only: bool = False,
    aliases_path: str = "registry/entity_aliases.json",
) -> dict:
    from datetime import date
    run_date = date.today().isoformat()
    targets = strategies or ALL_STRATEGIES

    strategies_data: dict = {}
    rebuilt: list[str] = []

    for strategy_slug in targets:
        title = _read_strategy_title(wiki_root, strategy_slug)
        entities = gather_strategy_entities(wiki_root, strategy_slug)

        if digest_only:
            # Read existing synthesis from strategy frontmatter rather than rebuilding
            page = Path(wiki_root) / (strategy_slug + ".md")
            if page.exists():
                fm = _parse_frontmatter(page.read_text(encoding="utf-8"))
                synthesis = fm.get("synthesis", _empty_synthesis())
            else:
                synthesis = _empty_synthesis()
        else:
            synthesis = build_strategy_synthesis(
                strategy_slug=strategy_slug,
                strategy_title=title,
                entities=entities,
            )
            page = Path(wiki_root) / (strategy_slug + ".md")
            if page.exists():
                write_strategy_synthesis(str(page), synthesis, run_date=run_date)
                rebuilt.append(strategy_slug)
            else:
                print(f"[synthesize_wiki] strategy page missing: {page}")

        strategies_data[strategy_slug] = {"title": title, "synthesis": synthesis}

    narrative = build_digest_narrative(strategies_data=strategies_data)
    delta = extract_recent_delta(str(Path(wiki_root) / "log.md"))

    digest_text = assemble_digest(
        narrative=narrative,
        strategies_data=strategies_data,
        delta=delta,
        run_date=run_date,
        sources_count=_count_sources(wiki_root),
        entity_count=_count_entities(wiki_root),
    )
    digest_path = write_digest(wiki_root=wiki_root, content=digest_text)

    return {
        "strategies_rebuilt": rebuilt,
        "digest_path": digest_path,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_synthesize_wiki.py -v
```
Expected: PASS (15 tests).

- [ ] **Step 5: Verify the full pipeline test suite stays green**

```bash
python -m pytest tests/ -q
```
Expected: 152 passed, 1 skipped (137 prior + 15 new).

- [ ] **Step 6: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py
git commit -m "feat(synthesize_wiki): orchestrate Phase C — L1 rebuild + L2 digest assembly"
```

---

## Task 9: Smoke test against real wiki (manual, with API)

Once tests pass, run the command for real against the current wiki to validate prompt quality, performance, and digest readability. This is a human review step, not a unit test.

- [ ] **Step 1: Dry-run on one strategy to validate the prompt**

```bash
python -m pipeline.synthesize_wiki --wiki-root wiki --strategy strategies/strategy-1-renewable-grid
```
Expected: command completes, `wiki/strategies/strategy-1-renewable-grid.md` gains a `synthesis:` block, `wiki/digest.md` is created with content for Strategy 1 (other strategies will have empty synthesis since they were skipped).

- [ ] **Step 2: Read the generated synthesis block and digest**

Open `wiki/strategies/strategy-1-renewable-grid.md` and `wiki/digest.md` in Obsidian. Confirm:
- `synthesis:` block lists plausible core initiatives and actors
- year-over-year arc reads as factual, not invented
- digest.md is human-readable and would serve as useful Comprehend context
- No fabricated slugs (every wikilink resolves to a real page)

If any of those fail, refine the prompts in `pipeline/synthesize_wiki.py` (the `_STRATEGY_SYNTHESIS_SYSTEM` and `_DIGEST_NARRATIVE_SYSTEM` constants) and re-run.

- [ ] **Step 3: Full rebuild across all 7 strategies**

```bash
python -m pipeline.synthesize_wiki --wiki-root wiki
```
Expected: 7 strategy pages updated, full digest.md written. Total runtime budget: ~90s (8 LLM calls — 7 strategies + 1 narrative).

- [ ] **Step 4: Spot-check the digest**

Verify the digest is under 8k tokens (it should be ~4–6k for current wiki size).

```bash
wc -w wiki/digest.md
# Word count × 1.3 ≈ token count; budget is < 8000 tokens
```

If over budget, tighten the prompt to cap entity list sizes (e.g. top-6 instead of top-8).

- [ ] **Step 5: Commit the generated wiki artifacts**

```bash
git add wiki/strategies/*.md wiki/digest.md
git commit -m "data: first generated synthesis blocks + wiki/digest.md (synthesize_wiki run)"
```

---

## Task 10: Update CLAUDE.md command reference + CHANGELOG

- [ ] **Step 1: Add command to CLAUDE.md**

In `CLAUDE.md`, after the `enrich_strategy_links` block (around line 105), add:

```markdown
On-demand synthesis (run after lint + apply, per Phase C of the architecture):
\`\`\`
python -m pipeline.synthesize_wiki --wiki-root wiki                        # rebuild all 7 strategies + digest
python -m pipeline.synthesize_wiki --wiki-root wiki --strategy strategies/strategy-1-renewable-grid   # single strategy
python -m pipeline.synthesize_wiki --wiki-root wiki --digest-only         # rebuild digest from existing synthesis: blocks
\`\`\`
```

- [ ] **Step 2: Add CHANGELOG entry**

Prepend a new top entry to `CHANGELOG.md`:

```markdown
## 2026-06-26 — Phase C: synthesize_wiki command

**What changed:**
- Added `pipeline/synthesize_wiki.py` — Phase C of the ingest cycle. Reads the
  clean post-lint entity layer, rebuilds machine-maintained `synthesis:` blocks
  in each of the 7 strategy pages (L1), and writes `wiki/digest.md` (L2): a
  ~4–6k-token briefing combining cross-strategy narrative, structured entity
  map, and recent ingest delta.
- 15 new unit tests + integration test against fixture wiki tree.
- First generated synthesis blocks committed for all 7 strategies; first
  `wiki/digest.md` committed.

**Why:** Establishes the L1 and L2 layers defined in
`docs/architecture/knowledge-synthesis-architecture.md`. Closes the first of
four implementation steps in the knowledge synthesis upgrade. Next: wire
`digest.md` injection into the holistic synthesizer's Comprehend pass.
```

- [ ] **Step 3: Commit and push branch**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: document synthesize_wiki command in CLAUDE.md + CHANGELOG"
git push -u origin feat/knowledge-synthesis
```

- [ ] **Step 4: Open PR for review**

```bash
gh pr create --title "feat: Phase C synthesis — synthesize_wiki command (L1 + L2 digest)" --body "$(cat <<'EOF'
## Summary
- Implements the `synthesize_wiki` command (Phase C of the ingest cycle).
- Reads clean post-lint entity layer → rebuilds strategy synthesis: blocks (L1) → writes wiki/digest.md (L2).
- First step of the four-step knowledge synthesis architecture (see docs/architecture/knowledge-synthesis-architecture.md).

## Test plan
- [ ] All 152 tests passing (137 prior + 15 new)
- [ ] Manual smoke test on Strategy 1 produced a plausible synthesis block
- [ ] Full 7-strategy rebuild completed in <2 minutes
- [ ] wiki/digest.md is under 8k tokens
- [ ] Human review of digest.md confirms readability and factual accuracy

## Follow-up plans
- Plan 2: digest.md injection into holistic synthesizer's Comprehend pass
- Plan 3: split holistic synthesizer into Comprehend + Plan API calls
- Plan 4: formalize synthesis: schema in SCHEMA.md with validation
EOF
)"
```

---

## Self-Review Checklist

After completing all tasks above, before requesting code review:

**Spec coverage** — every requirement in `docs/architecture/knowledge-synthesis-architecture.md` Phase C is implemented:
- [x] Step 1 of the architecture (strategy synthesis sections written)
- [x] Step 2 of the architecture (cross-strategy narrative)
- [x] Step 3 of the architecture (entity map + recent delta)
- [x] Phase C runs as a separate command (not wired into run_ingest.py)
- [x] Output is `wiki/digest.md` at vault root
- [x] Prose body of strategy pages preserved

**Risks not addressed in this plan (acknowledge, defer to follow-up):**
- The integration test mocks the LLM. Real prompt quality only becomes visible at Task 9 (manual smoke test). Prompts will likely need 1–2 iteration rounds.
- The `cross-strategy-links` field is populated independently by each strategy's LLM call — they may disagree (Strategy 1 says Bryant is cross-cutting; Strategy 2 doesn't). A reconciliation pass could be added later if this becomes noisy.
- digest.md token budget is monitored manually at Task 9. A programmatic check could be added (warn if >8k tokens).

---

## Roadmap — Remaining Three Steps (separate plans, not this one)

These are the follow-on implementation efforts after this plan ships. Each will be specced in its own plan document when we get there.

### Plan 2: Digest injection into Comprehend pass
- Modify `pipeline/holistic_synthesizer.py` to read `wiki/digest.md` and prepend it to the source content as a "PRIOR WIKI KNOWLEDGE" context block.
- Add fallback for when digest.md doesn't yet exist (first ingest after fresh wiki).
- Estimated effort: 2–3 tasks.

### Plan 3: Split holistic synthesizer into Comprehend + Plan
- Refactor the single Pass 1 LLM call into two calls: Comprehend (produces structured integration plan JSON) → Plan (produces strategy bodies + stub list, informed by the plan).
- Thread the integration plan through to Pass 2 LDP so entity retrieval is targeted to plan's `retrieve-for-context` field.
- Estimated effort: 6–8 tasks. The largest of the four steps.

### Plan 4: Formalize synthesis: schema
- Document the synthesis: schema in `SCHEMA.md` alongside existing page-type schemas.
- Add a validator in `pipeline/models.py` that strategy pages with synthesis blocks must conform to.
- Estimated effort: 2 tasks.
