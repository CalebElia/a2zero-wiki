# Dedup / Alias Enforcement + lint_wiki Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate entity pages across multi-document ingests and provide an on-demand lint command for post-ingest wiki maintenance.

**Architecture:** Three layers. (1) A shared `alias_registry.py` module wraps `registry/entity_aliases.json` with load/save/resolve/fuzzy-candidate helpers. (2) Pass 1.5 — integrated into the existing stub-creation loop (holistic_synthesizer.py) and the chunk write loop (wiki_writer.py) — resolves every proposed slug through the registry before writing: known aliases redirect to canonical + trigger an LLM merge call; novel near-duplicates are flagged in the review queue. (3) `pipeline/lint_wiki.py` is a new on-demand command with three modes: `--structural` (broken links, title mismatches, orphans), `--semantic` (fuzzy + LLM near-duplicate detection → review queue proposals), and `--apply` (executes approved proposals: merge content, update alias file, rewrite inbound links, log to `registry/merge-log.jsonl`).

**Tech Stack:** Python stdlib `difflib.SequenceMatcher` for Stage 1 fuzzy scoring; `anthropic` SDK (already in requirements.txt) for Stage 2 LLM reasoning and LLM merge calls; `pyyaml` for frontmatter manipulation; `pytest` for tests.

---

## Background for the implementer

This codebase ingests policy documents into an Obsidian wiki. The three-pass pipeline:
- **Pass 0**: copies `prepared/<type>/<uuid>.md` → `wiki/sources/<type>/<uuid>.md`
- **Pass 1** (`holistic_synthesizer.py`): reads the full document, writes one overview page, fills strategy bodies, and creates stub pages for every entity mentioned
- **Pass 2** (`wiki_writer.py` via `ldp.py`): processes the document section-by-section, writing actor/initiative/location/political-event pages
- **Pass 3** (`wiki_index.py`): rebuilds `index.md`, seals `log.md`

The problem: when multiple documents are ingested, the same real-world entity may be named differently in each document. "OSI" in document A is the same as "Office of Sustainability and Innovations" in document B. Without alias enforcement, each ingest creates a new page, and the wiki accumulates duplicates. The alias store (`registry/entity_aliases.json`) already exists with 13 entries but is never consulted during writes.

Key files to read before touching anything:
- `registry/entity_aliases.json` — current alias schema (see Task 1 for the extended schema)
- `pipeline/holistic_synthesizer.py:508-535` — stub creation loop (where Pass 1.5 inserts)
- `pipeline/wiki_writer.py:401-425` — chunk write loop (where Pass 1.5 inserts)
- `pipeline/run_ingest.py:101-143` — `_build_entity_context()` helper

---

## File Map

| File | Status | Role |
|------|--------|------|
| `pipeline/alias_registry.py` | **Create** | Load/save/resolve/fuzzy for entity_aliases.json |
| `pipeline/merge_pages.py` | **Create** | LLM merge call: two page bodies → one unified body |
| `pipeline/lint_wiki.py` | **Create** | `--structural`, `--semantic`, `--apply` modes |
| `registry/entity_aliases.json` | **Modify** | Add `relationship`, `as-of`, `notes` optional fields |
| `registry/merge-log.jsonl` | **Create** | Append-only audit trail for every approved merge |
| `pipeline/holistic_synthesizer.py` | **Modify** | Pass 1.5 in stub creation loop (~line 509) |
| `pipeline/wiki_writer.py` | **Modify** | Pass 1.5 in chunk write loop (~line 401) |
| `tests/test_alias_registry.py` | **Create** | Unit tests for alias_registry.py |
| `tests/test_merge_pages.py` | **Create** | Unit tests for merge_pages.py |
| `tests/test_lint_wiki.py` | **Create** | Unit tests for lint_wiki.py |

---

## Task 1: Extend entity_aliases.json schema + create alias_registry.py

**Files:**
- Modify: `registry/entity_aliases.json`
- Create: `pipeline/alias_registry.py`
- Create: `tests/test_alias_registry.py`

### Context

The current schema has entries like:
```json
"osi": {
  "canonical": "actors/osi",
  "type": "actor",
  "aliases": ["OSI", "Office of Sustainability and Innovations", ...]
}
```

We need three new optional fields:
- `"relationship"`: `"name-variant"` | `"predecessor"` | `"absorbed-by"` (default: `"name-variant"` when omitted)
- `"as-of"`: ISO date string, for temporal transitions only
- `"notes"`: free text, explains the relationship

The `resolve_slug(slug, aliases)` function checks if `slug` appears as the key OR appears inside any entry's `"canonical"` path (strip the type prefix, e.g. `"actors/osi"` → key `"osi"`).

The `resolve_title(title, aliases)` function checks if `title` appears (case-insensitive) in any entry's `"aliases"` list.

The `fuzzy_candidates(title, all_titles, threshold=0.65)` function uses `difflib.SequenceMatcher` to return titles scoring above threshold. Used by `lint_wiki --semantic` Stage 1.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_alias_registry.py
import json
import pytest
from pathlib import Path
from pipeline.alias_registry import (
    load_aliases,
    save_aliases,
    resolve_slug,
    resolve_title,
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
    p.write_text(json.dumps(SAMPLE_ALIASES))
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


def test_resolve_title_case_insensitive():
    assert resolve_slug_for_title("office of sustainability and innovations", SAMPLE_ALIASES) == "actors/osi"


def test_resolve_title_unknown_returns_none():
    assert resolve_slug_for_title("completely unknown entity", SAMPLE_ALIASES) is None


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
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
python -m pytest tests/test_alias_registry.py -v
```
Expected: ImportError or NameError (module doesn't exist yet)

- [ ] **Step 3: Create pipeline/alias_registry.py**

```python
# pipeline/alias_registry.py
import json
import difflib
from pathlib import Path

DEFAULT_ALIASES_PATH = "registry/entity_aliases.json"


def load_aliases(path: str = DEFAULT_ALIASES_PATH) -> dict:
    """Load entity_aliases.json. Returns {} if file missing."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_aliases(aliases: dict, path: str = DEFAULT_ALIASES_PATH) -> None:
    """Write aliases back to disk with stable formatting."""
    Path(path).write_text(
        json.dumps(aliases, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def resolve_slug(slug: str, aliases: dict) -> str | None:
    """Return canonical vault path if slug is a known alias key, else None.

    slug should be the bare key (e.g. 'osi'), not the full path ('actors/osi').
    """
    entry = aliases.get(slug)
    if entry:
        return entry["canonical"]
    return None


def resolve_slug_for_title(title: str, aliases: dict) -> str | None:
    """Return canonical vault path if title matches any alias label (case-insensitive)."""
    title_lower = title.strip().lower()
    for entry in aliases.values():
        for label in entry.get("aliases", []):
            if label.lower() == title_lower:
                return entry["canonical"]
    return None


def fuzzy_candidates(query: str, candidates: list[str], threshold: float = 0.65) -> list[str]:
    """Return candidates whose normalized edit similarity to query exceeds threshold.

    Uses difflib.SequenceMatcher (stdlib). Stage 1 of the two-stage dedup detection.
    Results are NOT deduplicated — caller should handle uniqueness.
    """
    query_lower = query.lower()
    results = []
    for candidate in candidates:
        score = difflib.SequenceMatcher(None, query_lower, candidate.lower()).ratio()
        if score >= threshold:
            results.append(candidate)
    return results


def add_alias(
    slug: str,
    canonical: str,
    entity_type: str,
    alias_labels: list[str],
    relationship: str = "name-variant",
    aliases_path: str = DEFAULT_ALIASES_PATH,
    as_of: str | None = None,
    notes: str | None = None,
) -> None:
    """Add or update an alias entry and persist to disk."""
    aliases = load_aliases(aliases_path)
    entry: dict = {
        "canonical": canonical,
        "type": entity_type,
        "aliases": alias_labels,
        "relationship": relationship,
    }
    if as_of:
        entry["as-of"] = as_of
    if notes:
        entry["notes"] = notes
    aliases[slug] = entry
    save_aliases(aliases, aliases_path)
```

- [ ] **Step 4: Fix test file — add missing import**

In `tests/test_alias_registry.py`, the test `test_resolve_title_case_insensitive` calls `resolve_slug_for_title` but the import block only imports `resolve_title`. Fix the import:

```python
from pipeline.alias_registry import (
    load_aliases,
    save_aliases,
    resolve_slug,
    resolve_slug_for_title,
    fuzzy_candidates,
    add_alias,
)
```

Also remove `resolve_title` from the import (it doesn't exist — `resolve_slug_for_title` is the correct name).

- [ ] **Step 5: Run tests — confirm they pass**

```bash
python -m pytest tests/test_alias_registry.py -v
```
Expected: 9 passed

- [ ] **Step 6: Extend entity_aliases.json schema**

Add `"relationship": "name-variant"` to every existing entry that currently lacks it. Also add the new SEU entry with `"relationship": "predecessor"` since we know that lineage already. Edit `registry/entity_aliases.json`:

For each of the 13 existing entries (e.g. `"osi"`, `"city-of-ann-arbor"`, etc.), add one field after `"aliases"`:
```json
"relationship": "name-variant"
```

Add one new entry for the SEU temporal succession at the bottom of the JSON object (before the closing `}`):
```json
,
"sustainable-energy-utility-seu": {
  "canonical": "actors/office-of-sustainability-and-innovations",
  "type": "actor",
  "aliases": [
    "Sustainable Energy Utility",
    "SEU",
    "community energy utility",
    "Ann Arbor SEU",
    "A2Zero SEU",
    "the SEU",
    "community-owned supplemental utility",
    "supplemental utility",
    "SEU ballot measure"
  ],
  "relationship": "predecessor",
  "as-of": "2022",
  "notes": "SEU was the proposed community energy utility; restructured/renamed into OSI scope per Year 2 annual report"
}
```

Note: the existing `"sustainable-energy-utility"` entry points to `"topics/sustainable-energy-utility"` — that's a topic page for the concept. The new entry `"sustainable-energy-utility-seu"` points to the actor. Both can coexist.

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest tests/ -q
```
Expected: 101 passed, 1 skipped (no regressions)

- [ ] **Step 8: Commit**

```bash
git add pipeline/alias_registry.py tests/test_alias_registry.py registry/entity_aliases.json
git commit -m "feat: add alias_registry.py — load/resolve/fuzzy helpers; extend entity_aliases.json schema with relationship field"
```

---

## Task 2: Create pipeline/merge_pages.py

**Files:**
- Create: `pipeline/merge_pages.py`
- Create: `tests/test_merge_pages.py`

### Context

`merge_pages()` is called when Pass 1.5 confirms a proposed entity is a known alias for an existing canonical page. It takes the existing canonical page body and the newly proposed body, and produces a unified page body via a single LLM call.

The prompt reuses the READ-UNDERSTAND-INTEGRATE principle from `wiki_writer.py`'s `WIKI_PAGES_SYSTEM` and the structural rules from `holistic_synthesizer.py`. It is a simpler, cheaper call than the Writer→Evaluator→Editor loop — inputs are two small wiki pages, not a 280KB source document.

The function also handles the `"predecessor"` relationship case: when the alias has `"relationship": "predecessor"`, it does NOT merge content — instead it returns the existing canonical body unchanged and appends `superseded-by` frontmatter fields to the predecessor page.

`merge_pages()` is not responsible for writing to disk. It only returns the merged body string. The caller (Pass 1.5 code in holistic_synthesizer.py or wiki_writer.py) handles the write.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_merge_pages.py
import pytest
from unittest.mock import MagicMock, patch


def _make_response(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.stop_reason = "end_turn"
    return msg


EXISTING_BODY = """The Office of Sustainability and Innovations (OSI) leads A2Zero. ([[sources/cap/cap-2020|cap-2020]])"""

NEW_BODY = """OSI coordinates partner organizations and public engagement events. ([[sources/cap/cap-2020|cap-2020]])"""

MERGED_BODY = """The Office of Sustainability and Innovations (OSI) leads A2Zero and coordinates partner organizations and public engagement events. ([[sources/cap/cap-2020|cap-2020]])"""


def test_merge_pages_calls_anthropic(tmp_path):
    from pipeline.merge_pages import merge_pages
    with patch("pipeline.merge_pages.anthropic.Anthropic") as MockClient:
        mock_client = MockClient.return_value
        mock_client.messages.create.return_value = _make_response(MERGED_BODY)
        result = merge_pages(
            canonical_slug="actors/osi",
            existing_body=EXISTING_BODY,
            new_body=NEW_BODY,
            source_uuid="cap-2020",
        )
    assert mock_client.messages.create.called
    assert result == MERGED_BODY


def test_merge_pages_returns_existing_on_api_failure(tmp_path):
    from pipeline.merge_pages import merge_pages
    with patch("pipeline.merge_pages.anthropic.Anthropic") as MockClient:
        mock_client = MockClient.return_value
        mock_client.messages.create.side_effect = Exception("API error")
        result = merge_pages(
            canonical_slug="actors/osi",
            existing_body=EXISTING_BODY,
            new_body=NEW_BODY,
            source_uuid="cap-2020",
        )
    # On failure, returns existing body unchanged — never loses content
    assert result == EXISTING_BODY


def test_merge_pages_returns_existing_on_truncation():
    from pipeline.merge_pages import merge_pages
    with patch("pipeline.merge_pages.anthropic.Anthropic") as MockClient:
        mock_client = MockClient.return_value
        truncated = MagicMock()
        truncated.content = [MagicMock(text="partial")]
        truncated.stop_reason = "max_tokens"
        mock_client.messages.create.return_value = truncated
        result = merge_pages(
            canonical_slug="actors/osi",
            existing_body=EXISTING_BODY,
            new_body=NEW_BODY,
            source_uuid="cap-2020",
        )
    assert result == EXISTING_BODY
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
python -m pytest tests/test_merge_pages.py -v
```
Expected: ImportError (module doesn't exist)

- [ ] **Step 3: Create pipeline/merge_pages.py**

```python
# pipeline/merge_pages.py
import anthropic

MERGE_SYSTEM = """You are integrating two wiki page bodies into one unified page body.

Rules:
- Preserve ALL factual claims from BOTH versions with their inline wikilink citations
- Do NOT duplicate paragraphs that already make the same point
- Produce a single coherent body a reader would find complete — not two sections stapled together
- Maintain the same wikilink citation format: ([[sources/path|uuid]])
- Output ONLY the merged body text — no frontmatter, no headings above the body, no preamble
"""


def merge_pages(
    canonical_slug: str,
    existing_body: str,
    new_body: str,
    source_uuid: str,
    model: str = "claude-sonnet-4-6",
) -> str:
    """Merge new_body into existing_body for the canonical page.

    Returns the merged body string. On any failure, returns existing_body unchanged
    so content is never silently lost.
    """
    prompt = (
        f"Canonical page: {canonical_slug}\n\n"
        f"[EXISTING BODY]\n{existing_body.strip()}\n[END EXISTING]\n\n"
        f"[NEW CONTENT from {source_uuid}]\n{new_body.strip()}\n[END NEW]\n\n"
        "Produce the unified body."
    )
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            temperature=0,
            system=MERGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "max_tokens":
            print(f"[merge_pages] WARNING: response truncated for {canonical_slug} — keeping existing body")
            return existing_body
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[merge_pages] WARNING: merge failed for {canonical_slug}: {e} — keeping existing body")
        return existing_body
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
python -m pytest tests/test_merge_pages.py -v
```
Expected: 3 passed

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -q
```
Expected: 104 passed, 1 skipped

- [ ] **Step 6: Commit**

```bash
git add pipeline/merge_pages.py tests/test_merge_pages.py
git commit -m "feat: add merge_pages.py — LLM merge call for alias-confirmed duplicate pages; safe fallback to existing body on failure"
```

---

## Task 3: Pass 1.5 in holistic_synthesizer.py (stub creation)

**Files:**
- Modify: `pipeline/holistic_synthesizer.py` (lines ~463–535)
- Modify: `tests/test_holistic_synthesizer.py`

### Context

The stub creation loop lives in `_write_synthesis()` starting at line ~508. For each `sp` in `result["stub_pages"]`, it currently:
1. Checks `stub_path.exists()` — if yes, skips
2. If no, creates the stub

Pass 1.5 inserts between steps 1 and 2:
- Load aliases once before the loop
- For each proposed stub slug: call `resolve_slug(bare_slug, aliases)`
  - If canonical returned AND canonical != proposed slug: redirect stub to canonical path
  - If canonical page has real content: call `merge_pages()` and replace body
  - If canonical page is a stub: write stub to canonical path (not the alias path)
  - If no alias match: proceed normally

The "bare slug" is the part after the type prefix. For `"initiatives/community-solar-program"`, the bare key to look up is `"community-solar-program"`. Also check the title against `resolve_slug_for_title()`.

`_write_synthesis()` currently takes `source_uuid`, `source_rel_path`, `wiki_root`, `run_date`. No signature change needed — aliases path is derived from `wiki_root`.

- [ ] **Step 1: Add alias lookup to stub loop in _write_synthesis()**

Find the stub loop in `pipeline/holistic_synthesizer.py` starting at line ~508. Replace the block:

```python
stubs_written = 0
for sp in result.get("stub_pages", []):
    stub_slug = sp.get("slug", "")
    if not stub_slug:
        continue
    stub_path = Path(wiki_root) / (stub_slug + ".md")
    if stub_path.exists():
        continue
    stub_path.parent.mkdir(parents=True, exist_ok=True)
    stub_fm = {
        "type": sp.get("type", "initiative"),
        "title": sp.get("title", ""),
        "source-first-seen": f"[[{source_rel_path}]]",
        "last-updated": run_date,
    }
    if sp.get("parent-strategy"):
        stub_fm["parent-strategy"] = sp["parent-strategy"]
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
```

With this new version:

```python
from pipeline.alias_registry import load_aliases, resolve_slug, resolve_slug_for_title
from pipeline.merge_pages import merge_pages as _merge_pages

aliases = load_aliases(str(Path(wiki_root).parent / "registry" / "entity_aliases.json"))

stubs_written = 0
for sp in result.get("stub_pages", []):
    stub_slug = sp.get("slug", "")
    if not stub_slug:
        continue

    # Pass 1.5: resolve through alias registry before writing
    bare_key = stub_slug.split("/")[-1]  # "initiatives/foo" → "foo"
    canonical_path = resolve_slug(bare_key, aliases) or resolve_slug_for_title(sp.get("title", ""), aliases)
    if canonical_path:
        # Redirect to canonical slug (e.g. "actors/osi" instead of "actors/office-of-sustainability")
        effective_slug = canonical_path
        print(f"[holistic:pass1.5] {stub_slug!r} → canonical {canonical_path!r}")
    else:
        effective_slug = stub_slug

    stub_path = Path(wiki_root) / (effective_slug + ".md")
    if stub_path.exists():
        existing = stub_path.read_text(encoding="utf-8")
        existing_body = re.sub(r"^---\n.*?\n---\n", "", existing, flags=re.DOTALL).strip()
        if re.sub(r"<!--.*?-->", "", existing_body, flags=re.DOTALL).strip():
            # Canonical page has real content — merge new stub context in
            one_liner = sp.get("one-liner", "")
            if one_liner:
                merged = _merge_pages(
                    canonical_slug=effective_slug,
                    existing_body=existing_body,
                    new_body=one_liner,
                    source_uuid=source_uuid,
                )
                _replace_wiki_page_body(str(stub_path), merged)
                print(f"[holistic:pass1.5] Merged one-liner into existing {effective_slug}")
        continue  # canonical stub or page already exists — skip creation

    stub_path.parent.mkdir(parents=True, exist_ok=True)
    stub_fm = {
        "type": sp.get("type", "initiative"),
        "title": sp.get("title", ""),
        "source-first-seen": f"[[{source_rel_path}]]",
        "last-updated": run_date,
    }
    if sp.get("parent-strategy"):
        stub_fm["parent-strategy"] = sp["parent-strategy"]
    if sp.get("type") in ("initiative", "strategy"):
        stub_fm["projections"] = []
        stub_fm["outcomes"] = []
    stub_page = build_wiki_page(
        page_type=sp.get("type", "initiative"),
        slug=effective_slug,
        frontmatter=stub_fm,
        body=f"<!-- stub from Pass 1 holistic read ({source_uuid}) — {sp.get('one-liner', '')} -->",
    )
    write_wiki_page(stub_page, wiki_root=wiki_root, exist_ok=False)
    stubs_written += 1
if stubs_written:
    print(f"[holistic] {stubs_written} stub pages created for Pass 2")
```

Note: add the two new imports at the top of `_write_synthesis()` function body, or at the top of the file alongside existing imports.

- [ ] **Step 2: Run existing holistic synthesizer tests**

```bash
python -m pytest tests/test_holistic_synthesizer.py -v
```
Expected: 11 passed (no regressions — the new code paths require a real alias file and real wiki pages to trigger, which the existing mocks don't set up)

- [ ] **Step 3: Add a targeted test for Pass 1.5 alias redirect**

Add this test to `tests/test_holistic_synthesizer.py`:

```python
def test_stub_creation_redirects_known_alias(tmp_path):
    """Pass 1.5: a stub whose slug is a known alias should write to the canonical path."""
    import json
    from unittest.mock import patch, MagicMock
    from pipeline.holistic_synthesizer import _write_synthesis

    # Set up wiki structure
    (tmp_path / "strategies").mkdir()
    (tmp_path / "actors").mkdir()
    (tmp_path / "overviews").mkdir()

    # Write the 7 required strategy stubs (synthesizer reads these)
    for i in range(1, 8):
        slug = f"strategy-{i}"
        (tmp_path / "strategies" / f"{slug}.md").write_text(
            f"---\ntitle: Strategy {i}\n---\n<!-- stub -->\n"
        )

    # Set up alias registry: "office-of-sustainability" → canonical "actors/osi"
    registry_dir = tmp_path.parent / "registry"
    registry_dir.mkdir(exist_ok=True)
    aliases = {
        "office-of-sustainability": {
            "canonical": "actors/osi",
            "type": "actor",
            "aliases": ["Office of Sustainability"],
            "relationship": "name-variant",
        }
    }
    aliases_path = registry_dir / "entity_aliases.json"
    aliases_path.write_text(json.dumps(aliases))

    # Synthesis result proposing the alias slug
    result = {
        "overview": {
            "slug": "overviews/test-source",
            "frontmatter": {
                "type": "overview",
                "title": "Test Source",
                "source-ref": "[[sources/cap/cap-2020]]",
                "source-first-seen": "[[sources/cap/cap-2020]]",
            },
            "body": "Overview body.",
        },
        "strategy_bodies": [],
        "stub_pages": [
            {
                "slug": "actors/office-of-sustainability",
                "type": "actor",
                "title": "Office of Sustainability",
                "one-liner": "Leads A2Zero.",
            }
        ],
        "topic_candidates": [],
        "log_summary": "Test run.",
    }

    with patch("pipeline.holistic_synthesizer.alias_registry_path", str(aliases_path)):
        _write_synthesis(
            result=result,
            wiki_root=str(tmp_path),
            source_uuid="cap-2020",
            source_rel_path="sources/cap/cap-2020",
            run_date="2026-06-25",
        )

    # The stub should be written at the canonical path, NOT the alias path
    assert (tmp_path / "actors" / "osi.md").exists()
    assert not (tmp_path / "actors" / "office-of-sustainability.md").exists()
```

To make the test patchable, extract the aliases path to a module-level constant at the top of `holistic_synthesizer.py`:

```python
# Near the top of holistic_synthesizer.py, after imports:
alias_registry_path = "registry/entity_aliases.json"
```

And in `_write_synthesis`, use:
```python
aliases = load_aliases(alias_registry_path)
```

- [ ] **Step 4: Run new test**

```bash
python -m pytest tests/test_holistic_synthesizer.py::test_stub_creation_redirects_known_alias -v
```
Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -q
```
Expected: 105 passed, 1 skipped

- [ ] **Step 6: Commit**

```bash
git add pipeline/holistic_synthesizer.py tests/test_holistic_synthesizer.py
git commit -m "feat: Pass 1.5 in holistic_synthesizer — alias registry lookup in stub creation; redirects known aliases to canonical"
```

---

## Task 4: Pass 1.5 in wiki_writer.py (chunk write loop)

**Files:**
- Modify: `pipeline/wiki_writer.py` (lines ~366–426)
- Modify: `tests/test_wiki_extractor.py` (or create new test)

### Context

`extract_wiki_pages_from_chunk()` is Pass 2's write path. After the LLM proposes a list of page specs, each spec goes through validation and then a write. This is where Pass 1.5 inserts for chunk-level writes.

The aliases dict should be loaded once outside `extract_wiki_pages_from_chunk()` and passed in as a parameter — loading it inside would re-read the file for every chunk (potentially hundreds of times per ingest). Add `aliases: dict | None = None` as a parameter with a default of `None`, which triggers a load inside if not provided.

The registry path must be derivable from `wiki_root` — use `Path(wiki_root).parent / "registry" / "entity_aliases.json"`.

- [ ] **Step 1: Update extract_wiki_pages_from_chunk signature and write loop**

In `pipeline/wiki_writer.py`, update the function signature and write loop:

```python
# Add to imports at top of file:
from pipeline.alias_registry import load_aliases, resolve_slug, resolve_slug_for_title
from pipeline.merge_pages import merge_pages as _merge_pages
import re as _re  # already imported, just ensuring availability


def extract_wiki_pages_from_chunk(
    chunk_text: str,
    source_uuid: str,
    source_rel_path: str,
    context_header: str,
    source_type: str,
    wiki_root: str,
    run_date: str,
    aliases: dict | None = None,  # NEW — pass from caller to avoid re-reading per chunk
) -> list[dict]:
```

In the write loop (starting at line ~401, replacing the `for spec in specs:` block):

```python
    if aliases is None:
        aliases = load_aliases(str(Path(wiki_root).parent / "registry" / "entity_aliases.json"))

    written = []
    for spec in specs:
        errors = validate_page_spec(spec, wiki_root=wiki_root)
        if errors:
            print(
                f"[wiki_writer] WARNING: invalid page spec skipped: {errors} "
                f"— {spec.get('slug', '?')}"
            )
            continue
        try:
            proposed_slug = spec["slug"]

            # Pass 1.5: resolve through alias registry
            bare_key = proposed_slug.split("/")[-1]
            canonical_path = (
                resolve_slug(bare_key, aliases)
                or resolve_slug_for_title(spec.get("frontmatter", {}).get("title", ""), aliases)
            )
            if canonical_path:
                effective_slug = canonical_path
                print(f"[wiki_writer:pass1.5] {proposed_slug!r} → canonical {canonical_path!r}")
                spec = {**spec, "slug": effective_slug}
            else:
                effective_slug = proposed_slug

            page_path = Path(wiki_root) / (effective_slug + ".md")
            if page_path.exists():
                existing = page_path.read_text(encoding="utf-8")
                existing_body = re.sub(r"^---\n.*?\n---\n", "", existing, flags=re.DOTALL).strip()
                if re.sub(r"<!--.*?-->", "", existing_body, flags=re.DOTALL).strip():
                    # Page has real content — merge new body in via LLM
                    merged = _merge_pages(
                        canonical_slug=effective_slug,
                        existing_body=existing_body,
                        new_body=spec["body"],
                        source_uuid=source_uuid,
                    )
                    _replace_wiki_page_body(str(page_path), merged)
                    written.append(spec)
                    continue
            # Normal write path (new page or stub-only existing page):
            write_or_append_page(spec, wiki_root=wiki_root, source_uuid=source_uuid)
            written.append(spec)
        except Exception as e:
            print(f"[wiki_writer] WARNING: failed to write page {spec.get('slug', '?')}: {e}")

    return written
```

- [ ] **Step 2: Update callers in ldp.py to pass aliases**

The aliases dict should be loaded once in `run_ldp_ingest()` in `pipeline/ldp.py` and passed to `extract_wiki_pages_from_chunk()` on each chunk call. Find `run_ldp_ingest` in `pipeline/ldp.py` and:

1. Add import at top: `from pipeline.alias_registry import load_aliases`
2. Load aliases once before the chunk loop:
```python
from pathlib import Path as _Path
aliases = load_aliases(str(_Path(wiki_root).parent / "registry" / "entity_aliases.json"))
```
3. Pass `aliases=aliases` to `extract_wiki_pages_from_chunk(...)` in the chunk loop.

Read `pipeline/ldp.py` to find the exact call site before making the edit.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -q
```
Expected: 105 passed, 1 skipped (new parameter is backward-compatible with default `None`)

- [ ] **Step 4: Commit**

```bash
git add pipeline/wiki_writer.py pipeline/ldp.py
git commit -m "feat: Pass 1.5 in wiki_writer — alias registry lookup in chunk write loop; LLM merge for known aliases"
```

---

## Task 5: lint_wiki.py — structural mode

**Files:**
- Create: `pipeline/lint_wiki.py`
- Create: `tests/test_lint_wiki.py`

### Context

`python -m pipeline.lint_wiki --wiki-root wiki --structural` scans all `.md` files in the vault and checks three things:

1. **Broken wikilinks**: parse every `[[...]]` pattern from page bodies and frontmatter. Strip the display alias (anything after `|`). Check if `wiki_root/<path>.md` exists. Flag missing.
2. **Title/slug mismatch**: the `title:` in frontmatter should be a human-readable form of the slug filename. Convert slug to title (replace `-` with space, title-case) and compare loosely. Flag when they diverge significantly.
3. **Orphaned pages**: build a set of all pages linked from any other page. Flag pages with no inbound links and no special exemption (strategy pages, index.md, log.md, hot.md are exempt).

Output appended to `review-queue.md` under a `## Structural Lint — YYYY-MM-DD` section. Each finding is one line with a severity tag: `[BROKEN_LINK]`, `[TITLE_MISMATCH]`, `[ORPHAN]`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_lint_wiki.py
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
    # Index page linking to osi
    (wiki / "index.md").write_text(
        "# Index\n- [[actors/osi|OSI]]\n- [[actors/broken|Broken]]\n"
    )
    return wiki


def test_structural_finds_broken_link(tmp_path):
    from pipeline.lint_wiki import structural_lint
    wiki = _make_wiki(tmp_path)
    findings = structural_lint(str(wiki))
    broken = [f for f in findings if f["type"] == "BROKEN_LINK"]
    assert any("actors/nonexistent" in f["detail"] for f in broken)


def test_structural_finds_orphan(tmp_path):
    from pipeline.lint_wiki import structural_lint
    wiki = _make_wiki(tmp_path)
    findings = structural_lint(str(wiki))
    orphans = [f for f in findings if f["type"] == "ORPHAN"]
    assert any("orphan-program" in f["page"] for f in orphans)


def test_structural_no_false_positive_for_osi(tmp_path):
    from pipeline.lint_wiki import structural_lint
    wiki = _make_wiki(tmp_path)
    findings = structural_lint(str(wiki))
    orphans = [f for f in findings if f["type"] == "ORPHAN"]
    assert not any("osi" in f["page"] for f in orphans)


def test_structural_skips_exempt_pages(tmp_path):
    from pipeline.lint_wiki import structural_lint
    wiki = _make_wiki(tmp_path)
    # index.md is exempt from orphan check
    findings = structural_lint(str(wiki))
    orphans = [f for f in findings if f["type"] == "ORPHAN"]
    assert not any(f["page"].endswith("index.md") for f in orphans)
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
python -m pytest tests/test_lint_wiki.py -v
```
Expected: ImportError

- [ ] **Step 3: Implement structural_lint() in pipeline/lint_wiki.py**

```python
# pipeline/lint_wiki.py
"""
On-demand post-ingest wiki linter.

Usage:
  python -m pipeline.lint_wiki --wiki-root wiki --structural
  python -m pipeline.lint_wiki --wiki-root wiki --semantic
  python -m pipeline.lint_wiki --wiki-root wiki --apply
"""
import re
import json
import argparse
from datetime import date
from pathlib import Path

# Pages exempt from the orphan check (hub pages, auto-generated, sources)
ORPHAN_EXEMPT_PATTERNS = frozenset({"index.md", "log.md", "hot.md"})
ORPHAN_EXEMPT_DIRS = frozenset({"strategies", "sources", "overviews", "topics", "meta"})

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")


def _all_md_files(wiki_root: str) -> list[Path]:
    return list(Path(wiki_root).rglob("*.md"))


def _parse_wikilinks(text: str) -> list[str]:
    """Return all wikilink targets (path portion only, no display alias)."""
    return WIKILINK_RE.findall(text)


def structural_lint(wiki_root: str) -> list[dict]:
    """Return list of finding dicts with keys: type, page, detail."""
    root = Path(wiki_root)
    all_files = _all_md_files(wiki_root)
    all_slugs = {str(f.relative_to(root)) for f in all_files}

    findings = []
    inbound_links: dict[str, set[str]] = {str(f.relative_to(root)): set() for f in all_files}

    for md_file in all_files:
        rel = str(md_file.relative_to(root))
        text = md_file.read_text(encoding="utf-8", errors="replace")
        links = _parse_wikilinks(text)
        for link in links:
            # Normalize: add .md if missing
            target = link.strip()
            if not target.endswith(".md"):
                target_path = target + ".md"
            else:
                target_path = target
            if target_path not in all_slugs:
                findings.append({
                    "type": "BROKEN_LINK",
                    "page": rel,
                    "detail": f"[[{link}]] → {target_path} not found",
                })
            else:
                inbound_links.setdefault(target_path, set()).add(rel)

    # Orphan check
    for md_file in all_files:
        rel = str(md_file.relative_to(root))
        fname = md_file.name
        parent_dir = md_file.parent.name
        if fname in ORPHAN_EXEMPT_PATTERNS:
            continue
        if parent_dir in ORPHAN_EXEMPT_DIRS:
            continue
        if not inbound_links.get(rel):
            findings.append({
                "type": "ORPHAN",
                "page": rel,
                "detail": "No other page links to this page",
            })

    return findings


def append_lint_report(wiki_root: str, findings: list[dict], mode: str) -> None:
    """Append a lint report section to review-queue.md."""
    if not findings:
        print(f"[lint_wiki:{mode}] No issues found.")
        return
    rq_path = Path(wiki_root).parent / "review-queue.md"
    today = date.today().isoformat()
    lines = [f"\n## {mode.title()} Lint — {today}\n"]
    for f in findings:
        lines.append(f"- [{f['type']}] `{f['page']}` — {f['detail']}")
    lines.append("")
    with rq_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"[lint_wiki:{mode}] {len(findings)} findings written to review-queue.md")
```

- [ ] **Step 4: Run structural tests**

```bash
python -m pytest tests/test_lint_wiki.py -v
```
Expected: 4 passed

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -q
```
Expected: 109 passed, 1 skipped

- [ ] **Step 6: Commit**

```bash
git add pipeline/lint_wiki.py tests/test_lint_wiki.py
git commit -m "feat: lint_wiki structural mode — broken wikilinks, orphan detection; appends to review-queue.md"
```

---

## Task 6: lint_wiki.py — semantic mode (fuzzy + LLM near-duplicate detection)

**Files:**
- Modify: `pipeline/lint_wiki.py`
- Modify: `tests/test_lint_wiki.py`

### Context

`--semantic` mode runs in two stages:
1. **Stage 1 (fuzzy, cheap):** for each entity type directory (actors, initiatives, locations, political-events), compare all page titles pairwise using `fuzzy_candidates()` from `alias_registry.py`. Threshold: 0.65. Pairs above threshold become candidates.
2. **Stage 2 (LLM, per candidate pair):** send both page titles + first 300 chars of body to the model. Ask for a structured JSON verdict: `{relationship: "same|successor|distinct", confidence: 0.0-1.0, reasoning: "..."}`. Only pairs with `confidence >= 0.75` and `relationship != "distinct"` generate proposals.

Proposals are written to `review-queue.md` as structured entries under `## Semantic Lint — YYYY-MM-DD`:

```
### [MERGE_PROPOSED] actors/osi + actors/office-of-sustainability-and-innovations
- Confidence: 0.91
- Reasoning: Both refer to the same Ann Arbor city sustainability office.
- Action: [ ] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER
- Notes: _Add any notes before approving_
```

- [ ] **Step 1: Add semantic_lint() to pipeline/lint_wiki.py**

Add after `structural_lint()`:

```python
SEMANTIC_VERDICT_SYSTEM = """You are comparing two wiki page entries to determine if they refer to the same real-world entity.

Return ONLY valid JSON with this exact structure:
{"relationship": "same|successor|distinct", "confidence": 0.0, "reasoning": "one sentence"}

Definitions:
- "same": both entries describe the same entity with different names (merge appropriate)
- "successor": entry A is a historical predecessor of entity B (keep both, add temporal link)
- "distinct": different real-world entities that happen to have similar names (do nothing)
"""


def _get_page_title_and_excerpt(md_path: Path) -> tuple[str, str]:
    """Return (title, first 300 chars of body) from a wiki page."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    # Extract title from frontmatter
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    title = md_path.stem.replace("-", " ").title()  # fallback
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip("'\"")
                break
    # Extract body excerpt
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL).strip()
    excerpt = body[:300]
    return title, excerpt


def semantic_lint(wiki_root: str, confidence_threshold: float = 0.75) -> list[dict]:
    """Stage 1 fuzzy + Stage 2 LLM near-duplicate detection.

    Returns list of proposal dicts with keys:
      type (MERGE_PROPOSED|TEMPORAL_SUCCESSION_PROPOSED), page_a, page_b,
      confidence, reasoning
    """
    import anthropic
    from pipeline.alias_registry import fuzzy_candidates

    root = Path(wiki_root)
    proposals = []
    client = anthropic.Anthropic()

    for type_dir in ["actors", "initiatives", "locations", "political-events"]:
        dir_path = root / type_dir
        if not dir_path.exists():
            continue
        pages = list(dir_path.glob("*.md"))
        if len(pages) < 2:
            continue

        # Build title→path map
        title_map: dict[str, Path] = {}
        for page in pages:
            title, _ = _get_page_title_and_excerpt(page)
            title_map[title] = page

        titles = list(title_map.keys())
        seen_pairs: set[frozenset] = set()

        for i, title_a in enumerate(titles):
            candidates = fuzzy_candidates(title_a, titles[i + 1:], threshold=0.65)
            for title_b in candidates:
                pair = frozenset({title_a, title_b})
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                # Stage 2: LLM verdict
                path_a = title_map[title_a]
                path_b = title_map[title_b]
                _, excerpt_a = _get_page_title_and_excerpt(path_a)
                _, excerpt_b = _get_page_title_and_excerpt(path_b)

                prompt = (
                    f"Entry A: {title_a}\n{excerpt_a}\n\n"
                    f"Entry B: {title_b}\n{excerpt_b}"
                )
                try:
                    response = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=256,
                        temperature=0,
                        system=SEMANTIC_VERDICT_SYSTEM,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    verdict = json.loads(response.content[0].text)
                except Exception as e:
                    print(f"[lint_wiki:semantic] WARNING: verdict failed for {title_a!r} vs {title_b!r}: {e}")
                    continue

                rel = verdict.get("relationship", "distinct")
                conf = float(verdict.get("confidence", 0))
                if rel == "distinct" or conf < confidence_threshold:
                    continue

                proposal_type = "MERGE_PROPOSED" if rel == "same" else "TEMPORAL_SUCCESSION_PROPOSED"
                proposals.append({
                    "type": proposal_type,
                    "page_a": str(path_a.relative_to(root)),
                    "page_b": str(path_b.relative_to(root)),
                    "confidence": conf,
                    "reasoning": verdict.get("reasoning", ""),
                })

    return proposals


def append_semantic_proposals(wiki_root: str, proposals: list[dict]) -> None:
    """Append semantic lint proposals to review-queue.md."""
    if not proposals:
        print("[lint_wiki:semantic] No near-duplicate proposals.")
        return
    rq_path = Path(wiki_root).parent / "review-queue.md"
    today = date.today().isoformat()
    lines = [f"\n## Semantic Lint — {today}\n"]
    for p in proposals:
        lines.append(f"### [{p['type']}] {p['page_a']} + {p['page_b']}")
        lines.append(f"- Confidence: {p['confidence']:.2f}")
        lines.append(f"- Reasoning: {p['reasoning']}")
        lines.append("- Action: [ ] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER")
        lines.append("- Notes: _Add any notes before approving_\n")
    with rq_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"[lint_wiki:semantic] {len(proposals)} proposals written to review-queue.md")
```

- [ ] **Step 2: Add semantic test**

Add to `tests/test_lint_wiki.py`:

```python
def test_semantic_lint_calls_llm_for_candidates(tmp_path):
    """Stage 2 LLM verdict is called when Stage 1 fuzzy match finds candidates."""
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
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(verdict))]
    mock_response.stop_reason = "end_turn"

    import json
    with patch("pipeline.lint_wiki.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        from pipeline.lint_wiki import semantic_lint
        proposals = semantic_lint(str(wiki))

    assert len(proposals) == 1
    assert proposals[0]["type"] == "MERGE_PROPOSED"
    assert proposals[0]["confidence"] == 0.92
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_lint_wiki.py -v
```
Expected: 5 passed

- [ ] **Step 4: Run full suite**

```bash
python -m pytest tests/ -q
```
Expected: 110 passed, 1 skipped

- [ ] **Step 5: Commit**

```bash
git add pipeline/lint_wiki.py tests/test_lint_wiki.py
git commit -m "feat: lint_wiki semantic mode — fuzzy Stage 1 + LLM Stage 2 near-duplicate detection; proposals to review-queue.md"
```

---

## Task 7: lint_wiki.py — apply mode + merge-log

**Files:**
- Modify: `pipeline/lint_wiki.py`
- Modify: `tests/test_lint_wiki.py`

### Context

`--apply` mode reads the review queue, finds approved proposals (those with `[x] APPROVE_MERGE` or `[x] APPROVE_TEMPORAL_SUCCESSION` checked), and executes each one:

**For APPROVE_MERGE:**
1. Read both pages' full content
2. Call `merge_pages()` → unified body
3. Write unified body to `page_a` (canonical)
4. Delete `page_b`
5. Scan all wiki .md files for `[[page_b_slug]]` wikilinks and rewrite to `[[page_a_slug]]`
6. Call `add_alias()` to persist the alias
7. Append to `registry/merge-log.jsonl`

**For APPROVE_TEMPORAL_SUCCESSION:**
1. Add `superseded-by` and `superseded-date` frontmatter to `page_b` (the predecessor)
2. Call `add_alias()` with `relationship="predecessor"`
3. Append to `registry/merge-log.jsonl`

The `merge-log.jsonl` entry format:
```json
{"date": "2026-06-25", "action": "MERGE", "from": "actors/office-of-sustainability", "into": "actors/osi", "source-doc": "cap-2020", "approved-by": "manual"}
```

The apply mode parses review-queue.md with a simple regex looking for `[x]` (lowercase x) in checked checkboxes in the Action line following a `### [MERGE_PROPOSED]` or `### [TEMPORAL_SUCCESSION_PROPOSED]` header.

- [ ] **Step 1: Add apply_proposals() to pipeline/lint_wiki.py**

```python
APPROVED_MERGE_RE = re.compile(r"\[x\] APPROVE_MERGE", re.IGNORECASE)
APPROVED_SUCCESSION_RE = re.compile(r"\[x\] APPROVE_TEMPORAL_SUCCESSION", re.IGNORECASE)
PROPOSAL_HEADER_RE = re.compile(
    r"### \[(MERGE_PROPOSED|TEMPORAL_SUCCESSION_PROPOSED)\] (.+?) \+ (.+)"
)


def _parse_approved_proposals(review_queue_path: str) -> list[dict]:
    """Parse review-queue.md for checked (approved) proposals."""
    text = Path(review_queue_path).read_text(encoding="utf-8", errors="replace")
    proposals = []
    current = None
    for line in text.splitlines():
        m = PROPOSAL_HEADER_RE.match(line.strip())
        if m:
            current = {"type": m.group(1), "page_a": m.group(2).strip(), "page_b": m.group(3).strip()}
        elif current and APPROVED_MERGE_RE.search(line):
            proposals.append({**current, "approved_action": "MERGE"})
            current = None
        elif current and APPROVED_SUCCESSION_RE.search(line):
            proposals.append({**current, "approved_action": "TEMPORAL_SUCCESSION"})
            current = None
    return proposals


def _rewrite_inbound_links(wiki_root: str, old_slug: str, new_slug: str) -> int:
    """Rewrite all [[old_slug]] wikilinks to [[new_slug]] across the vault. Returns count."""
    old_bare = old_slug.removesuffix(".md")
    new_bare = new_slug.removesuffix(".md")
    pattern = re.compile(r"\[\[" + re.escape(old_bare) + r"(\|[^\]]+)?\]\]")
    count = 0
    for md_file in Path(wiki_root).rglob("*.md"):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        def _replace(m):
            alias_part = m.group(1) or ""
            return f"[[{new_bare}{alias_part}]]"
        new_text, n = pattern.subn(_replace, text)
        if n > 0:
            md_file.write_text(new_text, encoding="utf-8")
            count += n
    return count


def _append_merge_log(merge_log_path: str, entry: dict) -> None:
    """Append one JSON entry to registry/merge-log.jsonl."""
    import json
    with open(merge_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def apply_proposals(wiki_root: str, aliases_path: str, merge_log_path: str) -> None:
    """Execute approved proposals from review-queue.md."""
    from pipeline.merge_pages import merge_pages as _merge_pages
    from pipeline.alias_registry import load_aliases, add_alias
    import re as _re

    rq_path = str(Path(wiki_root).parent / "review-queue.md")
    if not Path(rq_path).exists():
        print("[lint_wiki:apply] No review-queue.md found.")
        return

    proposals = _parse_approved_proposals(rq_path)
    if not proposals:
        print("[lint_wiki:apply] No approved proposals found.")
        return

    today = date.today().isoformat()
    root = Path(wiki_root)

    for p in proposals:
        page_a_rel = p["page_a"]  # canonical / merge target
        page_b_rel = p["page_b"]  # alias / predecessor
        path_a = root / page_a_rel
        path_b = root / page_b_rel

        if p["approved_action"] == "MERGE":
            if not path_a.exists() or not path_b.exists():
                print(f"[lint_wiki:apply] WARNING: page not found for merge: {page_a_rel} + {page_b_rel}")
                continue

            # Merge content
            body_a = re.sub(r"^---\n.*?\n---\n", "", path_a.read_text(encoding="utf-8"), flags=re.DOTALL).strip()
            body_b = re.sub(r"^---\n.*?\n---\n", "", path_b.read_text(encoding="utf-8"), flags=re.DOTALL).strip()
            merged = _merge_pages(
                canonical_slug=page_a_rel.removesuffix(".md"),
                existing_body=body_a,
                new_body=body_b,
                source_uuid="lint-merge",
            )
            _replace_wiki_page_body(str(path_a), merged)

            # Delete non-canonical
            path_b.unlink()

            # Rewrite inbound links
            n = _rewrite_inbound_links(wiki_root, page_b_rel, page_a_rel)
            print(f"[lint_wiki:apply] MERGE: {page_b_rel} → {page_a_rel} ({n} links rewritten)")

            # Register alias
            slug_b = page_b_rel.removesuffix(".md").split("/")[-1]
            canonical_full = page_a_rel.removesuffix(".md")
            entity_type = page_a_rel.split("/")[0].rstrip("s")  # "actors" → "actor"
            add_alias(
                slug=slug_b,
                canonical=canonical_full,
                entity_type=entity_type,
                alias_labels=[path_b.stem.replace("-", " ").title()],
                relationship="name-variant",
                aliases_path=aliases_path,
            )

            # Log
            _append_merge_log(merge_log_path, {
                "date": today,
                "action": "MERGE",
                "from": page_b_rel,
                "into": page_a_rel,
                "approved-by": "manual",
            })

        elif p["approved_action"] == "TEMPORAL_SUCCESSION":
            if not path_b.exists():
                print(f"[lint_wiki:apply] WARNING: predecessor page not found: {page_b_rel}")
                continue

            # Add superseded-by frontmatter to predecessor (page_b)
            content = path_b.read_text(encoding="utf-8")
            m = re.match(r"^(---\n)(.*?)(\n---\n)(.*)", content, re.DOTALL)
            if m:
                fm_text = m.group(2)
                fm_text += f"\nsuperseded-by: '[[{page_a_rel.removesuffix(\".md\")}]]'"
                fm_text += f"\nsuperseded-date: '{today}'"
                path_b.write_text(m.group(1) + fm_text + m.group(3) + m.group(4), encoding="utf-8")

            slug_b = page_b_rel.removesuffix(".md").split("/")[-1]
            entity_type = page_a_rel.split("/")[0].rstrip("s")
            add_alias(
                slug=slug_b,
                canonical=page_a_rel.removesuffix(".md"),
                entity_type=entity_type,
                alias_labels=[path_b.stem.replace("-", " ").title()],
                relationship="predecessor",
                aliases_path=aliases_path,
                as_of=today,
            )
            _append_merge_log(merge_log_path, {
                "date": today,
                "action": "TEMPORAL_SUCCESSION",
                "predecessor": page_b_rel,
                "successor": page_a_rel,
                "approved-by": "manual",
            })
            print(f"[lint_wiki:apply] TEMPORAL_SUCCESSION: {page_b_rel} → {page_a_rel}")
```

- [ ] **Step 2: Add the __main__ entry point to pipeline/lint_wiki.py**

Add at the bottom of `pipeline/lint_wiki.py`:

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A2Zero wiki linter")
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument("--structural", action="store_true")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--aliases-path", default="registry/entity_aliases.json")
    parser.add_argument("--merge-log", default="registry/merge-log.jsonl")
    args = parser.parse_args()

    if args.structural:
        findings = structural_lint(args.wiki_root)
        append_lint_report(args.wiki_root, findings, "structural")

    if args.semantic:
        proposals = semantic_lint(args.wiki_root)
        append_semantic_proposals(args.wiki_root, proposals)

    if args.apply:
        apply_proposals(args.wiki_root, args.aliases_path, args.merge_log)

    if not any([args.structural, args.semantic, args.apply]):
        print("Specify at least one mode: --structural, --semantic, --apply")
```

- [ ] **Step 3: Add apply tests**

Add to `tests/test_lint_wiki.py`:

```python
def test_parse_approved_proposals_finds_checked_merge(tmp_path):
    from pipeline.lint_wiki import _parse_approved_proposals
    rq = tmp_path / "review-queue.md"
    rq.write_text(
        "## Semantic Lint — 2026-06-25\n\n"
        "### [MERGE_PROPOSED] actors/osi.md + actors/office-of-sustainability.md\n"
        "- Confidence: 0.91\n"
        "- Reasoning: Same office.\n"
        "- Action: [x] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER\n"
    )
    proposals = _parse_approved_proposals(str(rq))
    assert len(proposals) == 1
    assert proposals[0]["approved_action"] == "MERGE"
    assert "actors/osi.md" in proposals[0]["page_a"]


def test_rewrite_inbound_links(tmp_path):
    from pipeline.lint_wiki import _rewrite_inbound_links
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "actors").mkdir()
    (wiki / "actors" / "page.md").write_text(
        "See [[actors/old-slug]] and [[actors/old-slug|Old Name]].\n"
    )
    n = _rewrite_inbound_links(str(wiki), "actors/old-slug.md", "actors/new-slug.md")
    assert n == 2
    content = (wiki / "actors" / "page.md").read_text()
    assert "actors/new-slug" in content
    assert "actors/old-slug" not in content
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_lint_wiki.py -v
```
Expected: 7 passed

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -q
```
Expected: 112 passed, 1 skipped

- [ ] **Step 6: Commit**

```bash
git add pipeline/lint_wiki.py tests/test_lint_wiki.py
git commit -m "feat: lint_wiki apply mode — executes approved merges and temporal succession; audit trail to registry/merge-log.jsonl"
```

---

## Task 8: Update CLAUDE.md and CHANGELOG.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add lint_wiki commands to CLAUDE.md**

In `CLAUDE.md`, find the "Post-ingest linting" line under the pipeline section and replace it:

```markdown
Post-ingest linting (on-demand):
  python -m pipeline.lint_wiki --wiki-root wiki --structural   # broken links, orphans
  python -m pipeline.lint_wiki --wiki-root wiki --semantic     # near-duplicate detection
  python -m pipeline.lint_wiki --wiki-root wiki --apply        # execute approved proposals from review-queue.md
```

Also add a new "Alias Registry" section under Key Conventions:

```markdown
**Alias registry:** `registry/entity_aliases.json` — canonical source of truth for entity name variants and temporal relationships. Entries have `canonical`, `type`, `aliases`, `relationship` (`name-variant`|`predecessor`|`absorbed-by`), and optional `as-of`/`notes` fields. Every write in Pass 1 and Pass 2 resolves through this registry (Pass 1.5). Approved lint proposals are automatically written back to this file by `lint_wiki --apply`.

**Merge log:** `registry/merge-log.jsonl` — append-only audit trail of every approved entity merge or temporal succession. Each entry has `date`, `action`, `from`/`into` (or `predecessor`/`successor`), and `approved-by`. Use `git show <hash>:wiki/<path>.md` to recover any deleted page from git history.
```

- [ ] **Step 2: Add CHANGELOG entry**

Prepend to `CHANGELOG.md` (add before the existing first entry):

```markdown
## 2026-06-25 — Dedup/Alias Enforcement + lint_wiki

**What changed:**
- Added `pipeline/alias_registry.py` — load/resolve/fuzzy helpers wrapping `registry/entity_aliases.json`.
- Added `pipeline/merge_pages.py` — LLM merge call combining two page bodies into one; fails safe to existing body.
- Pass 1.5 integrated into holistic_synthesizer.py and wiki_writer.py: every proposed entity slug is resolved through the alias registry before writing; known aliases redirect to canonical and trigger an LLM merge.
- Extended `entity_aliases.json` schema with `relationship`, `as-of`, `notes` fields; added first `predecessor` entry (SEU → OSI).
- Added `pipeline/lint_wiki.py` with three modes: `--structural` (broken links, orphans), `--semantic` (fuzzy + LLM near-duplicate detection), `--apply` (execute approved proposals, rewrite inbound links, update alias file, log to `registry/merge-log.jsonl`).
- Created `registry/merge-log.jsonl` audit trail for all approved merges and temporal successions.

**Why:** Multi-document ingests were producing duplicate pages for the same real-world entity named differently across sources. The alias enforcement layer prevents new duplicates from forming during ingest; the linter surfaces and resolves existing duplicates post-ingest with HITL review.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: update CLAUDE.md with lint_wiki commands and alias conventions; add CHANGELOG entry"
```

---

## Task 9: Final verification

- [ ] **Step 1: Run full test suite — must be green**

```bash
python -m pytest tests/ -q
```
Expected: 112 passed, 1 skipped

- [ ] **Step 2: Smoke test structural lint against real wiki**

```bash
python -m pipeline.lint_wiki --wiki-root wiki --structural
```
Expected: runs without error; finding count printed; check `review-queue.md` tail for the new structural section

- [ ] **Step 3: Verify merge-log file was created**

```bash
ls -la registry/merge-log.jsonl
```
Expected: file exists (may be empty until first `--apply` run)

- [ ] **Step 4: Push to GitHub**

```bash
git push origin main
```

---

## Self-Review

**Spec coverage check:**
- [x] Alias enforcement during Pass 1 stub creation → Task 3
- [x] Alias enforcement during Pass 2 chunk writes → Task 4
- [x] LLM merge for known aliases → Task 2 + Tasks 3/4
- [x] Structural lint: broken links, orphans → Task 5
- [x] Semantic lint: fuzzy + LLM near-duplicate → Task 6
- [x] Apply mode: merge content, rewrite links, update alias file → Task 7
- [x] Audit trail (merge-log.jsonl) → Task 7
- [x] Temporal succession support (frontmatter + alias relationship) → Tasks 1 + 7
- [x] Review queue as MD format → Tasks 5/6/7
- [x] CLAUDE.md updated → Task 8
- [x] CHANGELOG updated → Task 8
- [x] All tests pass → Task 9

**Type consistency check:**
- `resolve_slug(slug: str, aliases: dict) -> str | None` — consistent across Tasks 1, 3, 4
- `resolve_slug_for_title(title: str, aliases: dict) -> str | None` — consistent across Tasks 1, 3, 4
- `merge_pages(canonical_slug, existing_body, new_body, source_uuid) -> str` — consistent across Tasks 2, 3, 4, 7
- `add_alias(slug, canonical, entity_type, alias_labels, relationship, aliases_path, as_of, notes)` — consistent across Tasks 1, 7
- `structural_lint(wiki_root: str) -> list[dict]` — dict keys: `type`, `page`, `detail` — consistent Tasks 5, 9
- `semantic_lint(wiki_root: str) -> list[dict]` — dict keys: `type`, `page_a`, `page_b`, `confidence`, `reasoning` — consistent Tasks 6, 9

**No placeholders found.**
