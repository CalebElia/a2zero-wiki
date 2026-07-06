# Deterministic Recall Floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee that every existing wiki entity named in a new source is deterministically surfaced to the ingest pipeline (recall floor) and that any entity that still slips through is loudly flagged for human review (staleness lint) — closing the silent-staleness gap that left `bryant-neighborhood-decarbonization` untouched by the Year 4/5 ingests.

**Architecture:** Comprehension stays LLM work; recall becomes mechanical. A new `pipeline/recall_scan.py` builds a name index (page titles + registry aliases + computed verb-prefix variants) and string-scans the incoming source. Hits missing from the Comprehend integration plan are appended to the plan (`scan-flagged` + `retrieve-for-context`) *before* it flows to Pass 1B and Pass 2 — both extraction paths inherit the fix through the existing plan plumbing with no prompt-structure changes. A new `--staleness` lint mode re-runs the same scan post-ingest and files a `STALE_ENTITY` finding for every matched entity whose page gained no citation to the new source. Also closes Task 121 (Progress Synthesis link-preservation) via a Writer prompt rule, since it shares the same root cause.

**Tech Stack:** Python 3.13, pytest, no new dependencies, no LLM calls in any new code path.

**Verified failure this fixes:** Year 5 digest named 76/497 entities (15.3%); the Comprehend plan covered 36 slugs; `bryant-neighborhood-decarbonization` (mentioned 8× in the Year 5 source) appeared in neither and its page was silently never updated. See `docs/architecture/knowledge-synthesis-architecture.md` and the 2026-07-06 session audit.

---

## Design decisions (locked before implementation)

1. **Scan hits go to `plan["scan-flagged"]` + `plan["retrieve-for-context"]`, NOT `plan["extends"]`.** Keeps LLM-judgment vs. mechanical provenance distinct in the audit trail (`integration-plans/<uuid>.json`), and preserves `load_retrieved_bodies()`'s existing priority order (extends-first, then mention frequency) so LLM-flagged entities never lose context budget to scan-added ones.

1a. **Awareness is never capped; only bodies are — and body drops are loud, recorded, and budgeted for.** Two tiers ride the plan: (i) *awareness* — the `scan-flagged` entries themselves (~80 chars each), injected uncapped into every chunk prompt via the plan JSON, which alone prevents the Bryant failure class (invisibility → misattribution): even body-less, Pass 2 targets the correct existing slug and `write_or_append_page` appends the new facts with a source marker; (ii) *bodies* — governed by `RETRIEVE_TOKEN_BUDGET`, **raised 30k → 60k tokens** (Year 5 measured 14k used for 15 LLM-flagged entities; a ~50-entity scan at ~2k chars avg adds ~25k tokens → ~39k combined, comfortably inside 60k). Uncapping entirely is rejected — it recreates the naive full-wiki-injection fix the architecture doc rejected for cost and context-degradation reasons, multiplied across every chunk prompt. Any residual drop (pathological sources matching 100+ entities) is (a) printed at ingest time, (b) recorded in the plan as `context-dropped: [slugs]` for the audit trail, and (c) cross-checked first by the staleness lint. Getting it right up front; the lint verifies only the knowingly-deprioritized tail.
1b. **Retrieved bodies are injected per-chunk scoped, not doc-wide.** The LDP chunk loop re-runs the scanner against each chunk's text and injects only the bodies of entities that chunk mentions (intersected with the loaded `retrieved_bodies`). Rationale: doc-wide injection multiplies every body across all ~12 chunk prompts (up to ~720k input tokens/ingest at the 60k budget, mostly irrelevant per chunk — the context-rot risk); per-entity sequential calls invert the cost (each call re-pays system prompt + chunk text, ~660k tokens for 120 calls, with divergent phrasings of co-occurring facts and no cross-reference consistency); agentic mid-extraction fetching returns retrieval initiative to LLM judgment — the exact failure class this plan eliminates. Per-chunk deterministic scoping keeps single-shot calls, batched co-occurring-fact integration, and the reproducible audit trail, at ~60–150k total body tokens with maximal relevance density. The `[INTEGRATION PLAN]` block (small, including `scan-flagged` awareness entries) stays doc-wide in every chunk prompt. The small-doc path is unaffected (one chunk = whole doc).

1c. **The `[INTEGRATION PLAN]` block stays doc-wide by design — do not per-chunk scope it.** Scope by function: bodies are *integration* material (heavy, chunk-local — scoped); plan entries are *orientation* material (light, ~3k tokens total, document-global — broadcast). Doc-wide plan entries let each chunk resolve boundary-bleeding references ("this funding", "the program above"), suppress duplicate page creation for entities routed elsewhere in the plan, and — decisively — keep awareness unconditional: if the per-chunk scanner misses a paraphrased mention, that chunk loses the body but keeps the awareness entry, so facts still target the right slug. Scoping the plan too would make both layers conditional on string matching, re-creating per-chunk invisibility.

1d. **Prompt assembly ordering is a cache constraint, not a style choice.** Chunk prompts MUST assemble stable-prefix-first: `system → [INTEGRATION PLAN] → KNOWN ENTITIES context` (byte-identical across all chunk calls) *then* `[RETRIEVED ENTITY PAGES] (per-chunk) → [SECTION CONTENT]`. Azure OpenAI applies automatic prefix caching to identical leading prefixes (>1024 tokens), and Anthropic's explicit caching works the same way — the repeated doc-wide block is amortized to a fraction of nominal cost across the ~12 chunk calls, but only if nothing chunk-specific precedes it. The Task 3 Step 3c sketch already orders this way; treat it as load-bearing.

2. **Name index is computed, not stored.** Verb-prefix variants ("Support Aging in Place Efficiently" → "Aging in Place Efficiently") are generated at index-build time. `registry/entity_aliases.json` stays a curated canonical-resolution registry; we do not pollute it with mechanical variants.
3. **Word-boundary, case-insensitive matching; minimum name length 4.** Names shorter than 4 chars are skipped even with boundaries (avoids acronym noise); registry aliases like "SEU" still reach the scanner via longer variants ("the SEU", "Ann Arbor SEU"). Matching runs against whitespace-normalized source text.
4. **Staleness lint is a separate `--staleness` CLI mode, not part of `--structural`.** It is ingest-cycle-scoped (needs a source UUID); structural is state-scoped. Default source = last line of `meta/ingest-stats.jsonl`.
5. **Findings are informational, human-triaged.** A `STALE_ENTITY` finding means "the source names this entity but its page gained no citation" — sometimes correct behavior (source repeats an old fact). No auto-fix.

---

## File structure

- Create: `pipeline/recall_scan.py` — name index, scanner, plan augmentation (single responsibility: deterministic recall)
- Create: `tests/test_recall_scan.py`
- Modify: `pipeline/orchestrator.py` — one insertion point after `validate_plan_slugs`, before `write_integration_plan`
- Modify: `pipeline/pass1a_comprehend.py` — `log_ingest_stats` gains `scan_flagged_count`
- Modify: `pipeline/pass1b_synthesize.py` — Writer prompt link-preservation rule (Task 121)
- Modify: `pipeline/phase_b_lint.py` — `staleness_lint()`, `write_staleness_findings()`, `--staleness` CLI
- Modify: `tests/test_lint_wiki.py`, `tests/test_pass1b_synthesize.py`
- Modify: `CLAUDE.md`, `CHANGELOG.md`; Create: `docs/architecture/deterministic-recall-floor.md`

---

### Task 1: `pipeline/recall_scan.py` — name index + scanner

**Files:**
- Create: `pipeline/recall_scan.py`
- Test: `tests/test_recall_scan.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recall_scan.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_recall_scan.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.recall_scan'`

- [ ] **Step 3: Implement `pipeline/recall_scan.py`**

```python
"""Deterministic recall floor for the ingest pipeline.

Comprehension is LLM work; recall is mechanical. This module string-scans an
incoming source against every known entity name (page titles + registry
aliases + computed verb-prefix variants) so the integration plan is guaranteed
to surface every existing entity the source names — independent of the
digest's lossy top-N compression and the Comprehend pass's judgment.

See docs/architecture/deterministic-recall-floor.md.
"""
import json
import re
from pathlib import Path

ENTITY_DIRS = [
    "actors", "initiatives", "locations", "technology",
    "funding-events", "meetings", "political-events",
]

# CAP-2020 action items carry a leading verb that later annual reports drop.
_VERB_PREFIXES = (
    "Support ", "Expand ", "Launch ", "Promote ", "Enhance ",
    "Implement ", "Develop ", "Increase ", "Advance ", "Establish ",
    "Transition ", "Improve ", "Foster ", "Invest In ", "Preserve ",
)

_MIN_NAME_LEN = 4

_TITLE_RE = re.compile(r"^title:\s*['\"]?(.+?)['\"]?\s*$", re.MULTILINE)


def build_entity_name_index(wiki_root: str, aliases_path: str | None = None) -> dict[str, str]:
    """Return {lowercased name: canonical slug} for every entity page.

    Sources, in override order (later wins on collision — aliases are curated,
    titles are generated, so registry aliases take precedence):
      1. computed verb-prefix variants of page titles
      2. page titles
      3. registry aliases (mapped to their canonical slug)
    """
    root = Path(wiki_root)
    if aliases_path is None:
        aliases_path = str(root.parent / "registry" / "entity_aliases.json")

    index: dict[str, str] = {}

    def _add(name: str, slug: str) -> None:
        name = name.strip()
        if len(name) >= _MIN_NAME_LEN:
            index[name.lower()] = slug

    for type_dir in ENTITY_DIRS:
        dir_path = root / type_dir
        if not dir_path.exists():
            continue
        for page in sorted(dir_path.glob("*.md")):
            slug = f"{type_dir}/{page.stem}"
            try:
                text = page.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
            title = None
            if m:
                tm = _TITLE_RE.search(m.group(1))
                if tm:
                    title = tm.group(1)
            if not title:
                title = page.stem.replace("-", " ").title()
            for prefix in _VERB_PREFIXES:
                if title.startswith(prefix):
                    _add(title[len(prefix):], slug)
            _add(title, slug)

    try:
        aliases = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        aliases = {}
    for entry in aliases.values():
        canonical = entry.get("canonical", "")
        if not canonical or not (root / f"{canonical}.md").exists():
            continue
        for alias in entry.get("aliases", []):
            _add(alias, canonical)

    return index


def scan_source_for_known_entities(source_text: str, index: dict[str, str]) -> dict[str, dict]:
    """Return {slug: {"matched-names": [...], "mentions": int}} for every
    indexed name that appears (word-boundary, case-insensitive) in the source."""
    text = re.sub(r"\s+", " ", source_text)
    hits: dict[str, dict] = {}
    for name, slug in index.items():
        pattern = r"\b" + re.escape(name) + r"\b"
        count = len(re.findall(pattern, text, re.IGNORECASE))
        if count:
            entry = hits.setdefault(slug, {"matched-names": [], "mentions": 0})
            entry["matched-names"].append(name)
            entry["mentions"] += count
    return hits
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_recall_scan.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/recall_scan.py tests/test_recall_scan.py
git commit -m "feat: recall_scan module — deterministic entity name index + source scanner"
```

---

### Task 2: `augment_integration_plan()` — merge scan hits into the plan

**Files:**
- Modify: `pipeline/recall_scan.py` (append function)
- Test: `tests/test_recall_scan.py` (append tests)

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_recall_scan.py

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_recall_scan.py -q`
Expected: FAIL with `ImportError: cannot import name 'augment_integration_plan'`

- [ ] **Step 3: Implement**

```python
# append to pipeline/recall_scan.py

def augment_integration_plan(plan: dict, scan_hits: dict[str, dict]) -> dict:
    """Fold deterministic scan hits into a Comprehend integration plan.

    Adds a `scan-flagged` list (provenance: mechanical, not LLM judgment) and
    appends missing slugs to `retrieve-for-context` ordered by mention count.
    Slugs the LLM already covered (extends / new-entities / retrieve list) are
    left alone — the scan is a recall floor, not an override.

    Awareness vs. bodies: scan-flagged entries ride the plan JSON into every
    chunk prompt UNCAPPED, so no matched entity is ever invisible to Pass 2.
    Only full page bodies are subject to RETRIEVE_TOKEN_BUDGET (raised to 60k
    tokens in Task 3); LLM-flagged entities keep first claim on that budget,
    scan-added bodies drop first, and drops are recorded loudly in
    `context-dropped` (Task 3) rather than silently.
    """
    known = {e.get("slug", "") for e in plan.get("extends") or []}
    known |= {e.get("slug", "") for e in plan.get("new-entities") or []}
    known |= set(plan.get("retrieve-for-context") or [])

    missing = {slug: hit for slug, hit in scan_hits.items() if slug not in known}
    ordered = sorted(missing, key=lambda s: (-missing[s]["mentions"], s))

    plan = dict(plan)
    plan["scan-flagged"] = [
        {"slug": slug,
         "matched-names": missing[slug]["matched-names"],
         "mentions": missing[slug]["mentions"]}
        for slug in ordered
    ]
    plan["retrieve-for-context"] = list(plan.get("retrieve-for-context") or []) + ordered
    return plan
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_recall_scan.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/recall_scan.py tests/test_recall_scan.py
git commit -m "feat: augment_integration_plan — fold scan hits into Comprehend plan as recall floor"
```

---

### Task 3: Wire the scan into `orchestrator.py` + telemetry

The single insertion point covers both Pass 2 paths (LDP and small-doc) *and* Pass 1B, because all three consume `integration_plan`/`retrieved_bodies` built here.

**Files:**
- Modify: `pipeline/orchestrator.py` (after `validate_plan_slugs`, ~line 183)
- Modify: `pipeline/pass1a_comprehend.py` (`log_ingest_stats` signature)
- Test: `tests/test_run_ingest.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_run_ingest.py — mirror the existing mocked-ingest fixture
# style in this file (patch chat/stream_chat, build tmp wiki). Core assertion:

def test_integration_plan_gains_scan_flagged_entities(tmp_path, monkeypatch):
    """An existing entity named in the source but absent from the Comprehend
    plan must appear in the written plan's scan-flagged list and
    retrieve-for-context — the Bryant regression."""
    # ... fixture: tmp wiki with initiatives/bryant-neighborhood-decarbonization.md
    #     (title: Bryant Neighborhood Decarbonization), a digest.md, registry dir;
    #     mocked Comprehend returns a plan WITHOUT bryant; mocked Pass 1B/2 no-op.
    # ... run run_source_ingest(...)
    plan = json.loads((tmp_path / "integration-plans" / "test-src.json").read_text())
    flagged = [e["slug"] for e in plan["scan-flagged"]]
    assert "initiatives/bryant-neighborhood-decarbonization" in flagged
    assert "initiatives/bryant-neighborhood-decarbonization" in plan["retrieve-for-context"]
```

(Implementer: follow the existing `test_run_ingest.py` mock pattern exactly — this file already has fixtures that stub the LLM calls and run `run_source_ingest` end-to-end.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_run_ingest.py -q -k scan_flagged`
Expected: FAIL (`KeyError: 'scan-flagged'`)

- [ ] **Step 3: Implement the orchestrator insertion**

In `run_source_ingest()`, immediately after `integration_plan = validate_plan_slugs(...)` and before `write_integration_plan(...)`:

```python
        # Deterministic recall floor: string-scan the source against every
        # known entity name so the plan is guaranteed to surface existing
        # entities the source mentions — independent of digest compression
        # and Comprehend judgment. See docs/architecture/deterministic-recall-floor.md.
        from pipeline.recall_scan import (
            build_entity_name_index,
            scan_source_for_known_entities,
            augment_integration_plan,
        )
        name_index = build_entity_name_index(wiki_root)
        scan_hits = scan_source_for_known_entities(source_content, name_index)
        integration_plan = augment_integration_plan(integration_plan, scan_hits)
        n_flagged = len(integration_plan.get("scan-flagged", []))
        if n_flagged:
            print(f"[ingest] {uuid}: recall scan flagged {n_flagged} existing "
                  f"entit{'y' if n_flagged == 1 else 'ies'} the Comprehend plan missed")
```

Then extend the `log_ingest_stats(...)` call with `scan_flagged_count=n_flagged`, and in `pass1a_comprehend.py` add the parameter (`scan_flagged_count: int = 0`) and include it in the JSONL record.

- [ ] **Step 3b: Raise the body budget and make drops loud + recorded**

In `pipeline/pass1a_comprehend.py`, raise the cap (sized from Year 5 telemetry: 14k tokens used by 15 LLM-flagged entities; ~50 scan-added entities at ~2k chars avg ≈ +25k tokens → ~39k combined fits with headroom):

```python
RETRIEVE_TOKEN_BUDGET = 60000  # raised from 30000 for the deterministic recall floor —
# scan-flagged bodies share this budget below LLM-flagged entities; drops are
# recorded in the plan's context-dropped field, never silent.
```

In `run_source_ingest()`, **reorder so `load_retrieved_bodies()` runs before `write_integration_plan()`**, then annotate drops into the plan so the audit-trail file records them:

```python
        retrieved_bodies = load_retrieved_bodies(integration_plan, wiki_root)
        # Loud accounting: any retrieve-for-context slug whose page exists but
        # whose body didn't fit the budget. Never silent — recorded in the plan
        # and checked first by the staleness lint.
        dropped = [
            s for s in integration_plan.get("retrieve-for-context", [])
            if s not in retrieved_bodies and (Path(wiki_root) / f"{s}.md").exists()
        ]
        integration_plan["context-dropped"] = dropped
        if dropped:
            print(f"[ingest] {uuid}: WARNING — {len(dropped)} entity bodies exceeded "
                  f"RETRIEVE_TOKEN_BUDGET and were not injected: {dropped}")
        plan_path = write_integration_plan(integration_plan, str(plans_dir))
```

Add to the Step 1 test: after the mocked ingest, `assert plan["context-dropped"] == []` (nothing drops in a small fixture), and add one test where a tiny monkeypatched `RETRIEVE_TOKEN_BUDGET` (e.g. `monkeypatch.setattr(pass1a_comprehend, "RETRIEVE_TOKEN_BUDGET", 1)`) forces a drop and asserts the slug lands in `context-dropped`. (Note: check whether `load_retrieved_bodies` reads the module constant at call time — if it binds at import, patch via the module attribute exactly as `tests/test_wiki_pages.py` does for `_VALID_PAGE_TYPES_PATH`.)

- [ ] **Step 3c: Per-chunk scoped body injection in the LDP chunk loop**

In `pipeline/pass2a_chunk_loop.py`, move the `[RETRIEVED ENTITY PAGES]` block assembly from the once-per-ingest context header (currently ~lines 260-271) into the per-chunk iteration, filtered to entities the chunk actually mentions. The `[INTEGRATION PLAN]` block stays doc-wide (it is small and carries the uncapped `scan-flagged` awareness entries). Thread the name index down from the orchestrator (built once) or rebuild it in the loop entry point — it is a cheap filesystem read.

```python
# inside the per-chunk loop, before building the chunk prompt:
from pipeline.recall_scan import scan_source_for_known_entities
chunk_hits = scan_source_for_known_entities(chunk_text, name_index)
chunk_bodies = {s: b for s, b in (retrieved_bodies or {}).items() if s in chunk_hits}
if chunk_bodies:
    body_lines = ["\n[RETRIEVED ENTITY PAGES — integrate new findings into these]"]
    for _s, _b in chunk_bodies.items():
        body_lines.append(f"--- {_s} ---\n{_b}")
    body_lines.append("[END RETRIEVED ENTITY PAGES]\n")
    chunk_context = doc_level_context + "\n".join(body_lines)
else:
    chunk_context = doc_level_context
```

Add a test (follow `tests/test_ldp.py`'s existing mocked-chunk-loop fixture style): two chunks, chunk A's text mentions entity X by title and chunk B's does not; capture the prompts passed to the mocked extraction call and assert X's body text appears in chunk A's prompt and NOT in chunk B's, while `[INTEGRATION PLAN]` appears in both.

The orchestrator's small-doc path (single whole-document "chunk") keeps its existing doc-level injection — scoping is a no-op there.

- [ ] **Step 4: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: all pass (306+ passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/orchestrator.py pipeline/pass1a_comprehend.py tests/test_run_ingest.py
git commit -m "feat: wire deterministic recall scan into ingest — plan augmented before Pass 1B/2"
```

---

### Task 4: Writer link-preservation rule (closes Task 121)

**Files:**
- Modify: `pipeline/pass1b_synthesize.py` (`HOLISTIC_WRITER_SYSTEM`, the "REQUIRED — entity wikilinks" block, ~lines 69-74)
- Test: `tests/test_pass1b_synthesize.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_pass1b_synthesize.py

def test_writer_prompt_requires_preserving_existing_wikilinks():
    """Task 121: the wikilink rule must cover entities already linked in
    EXISTING PROGRESS SYNTHESIS and entities in the integration plan — not
    only this run's stub_pages. Otherwise mature entities silently lose
    their links on every rewrite and backlink lint re-finds them yearly."""
    from pipeline.pass1b_synthesize import HOLISTIC_WRITER_SYSTEM
    assert "PRESERVE every [[...]] wikilink" in HOLISTIC_WRITER_SYSTEM
    assert "scan-flagged" in HOLISTIC_WRITER_SYSTEM
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pass1b_synthesize.py -q -k preserving`
Expected: FAIL (AssertionError)

- [ ] **Step 3: Extend the prompt rule**

In `HOLISTIC_WRITER_SYSTEM`, extend the existing "REQUIRED — entity wikilinks" block with:

```
- PRESERVE every [[...]] wikilink already present in [EXISTING PROGRESS SYNTHESIS]:
  when you restate or paraphrase a fact that carried a wikilink, the entity keeps
  its wikilink in your output. Dropping an existing link is a validation failure.
- Entities listed in the integration plan (extends, retrieve-for-context, or
  scan-flagged) already have wiki pages — link their first mention using the
  plan's slug. The stub_pages rule below covers only NEW entities you create.
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pass1b_synthesize.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline/pass1b_synthesize.py tests/test_pass1b_synthesize.py
git commit -m "feat: Writer must preserve existing wikilinks and link plan-listed entities (Task 121)"
```

---

### Task 5: `--staleness` lint mode with `STALE_ENTITY` findings

**Files:**
- Modify: `pipeline/phase_b_lint.py`
- Test: `tests/test_lint_wiki.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_lint_wiki.py

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_lint_wiki.py -q -k staleness`
Expected: FAIL (`ImportError: cannot import name 'staleness_lint'`)

- [ ] **Step 3: Implement in `phase_b_lint.py`**

```python
def staleness_lint(wiki_root: str, source_uuid: str | None = None) -> list[dict]:
    """Flag entity pages the given source names (title/alias, word-boundary)
    that gained no citation to that source — the silent-staleness failure.

    Informational findings for human triage: a mention can legitimately go
    uncited when the source merely repeats an already-recorded fact.
    """
    from pipeline.recall_scan import build_entity_name_index, scan_source_for_known_entities

    root = Path(wiki_root)
    if source_uuid is None:
        stats_path = root.parent / "meta" / "ingest-stats.jsonl"
        if not stats_path.exists():
            print("[lint_wiki:staleness] no source-uuid given and no ingest-stats.jsonl — nothing to check")
            return []
        last = stats_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        source_uuid = json.loads(last)["source-uuid"]

    matches = sorted((root / "sources").rglob(f"{source_uuid}.md"))
    if not matches:
        print(f"[lint_wiki:staleness] source {source_uuid!r} not found under wiki/sources/")
        return []
    source_text = matches[0].read_text(encoding="utf-8")

    index = build_entity_name_index(wiki_root)
    hits = scan_source_for_known_entities(source_text, index)

    findings = []
    for slug in sorted(hits):
        page_path = root / f"{slug}.md"
        if not page_path.exists():
            continue
        body = page_path.read_text(encoding="utf-8")
        if f"/{source_uuid}" in body or f"{source_uuid}]]" in body:
            continue  # page cites this source somewhere — not stale
        names = ", ".join(hits[slug]["matched-names"][:3])
        findings.append({
            "type": "STALE_ENTITY",
            "page": f"{slug}.md",
            "detail": (
                f"source {source_uuid} mentions this entity "
                f"({hits[slug]['mentions']}× as: {names}) but the page has no "
                f"{source_uuid} citation — possible missed update"
            ),
        })
    return findings


def write_staleness_findings(wiki_root: str, findings: list[dict], source_uuid: str) -> None:
    """Write staleness findings to review-queue.md, replacing any prior staleness section."""
    rq_path = Path(wiki_root).parent / "review-queue.md"
    today = date.today().isoformat()
    section_re = re.compile(r"\n?## Staleness Lint — [^\n]*\n(?:(?!## ).*\n?)*", re.MULTILINE)

    if findings:
        lines = [f"\n## Staleness Lint — {today} (source: {source_uuid})\n"]
        for f in findings:
            lines.append(f"- [{f['type']}] `{f['page']}` — {f['detail']}")
        lines.append("")
        new_section = "\n".join(lines)
    else:
        new_section = ""

    if rq_path.exists():
        text = section_re.sub("", rq_path.read_text(encoding="utf-8"))
        rq_path.write_text(text.rstrip() + new_section, encoding="utf-8")
    elif new_section:
        rq_path.write_text(new_section.lstrip(), encoding="utf-8")

    print(f"[lint_wiki:staleness] {len(findings)} findings written to review-queue.md"
          if findings else "[lint_wiki:staleness] No stale entities found.")
```

CLI wiring in the argparse block: add `parser.add_argument("--staleness", action="store_true")` and `parser.add_argument("--source-uuid", default=None)`; in main dispatch:

```python
    if args.staleness:
        findings = staleness_lint(args.wiki_root, source_uuid=args.source_uuid)
        uuid_used = args.source_uuid or (findings and "see section header") or "last-ingest"
        write_staleness_findings(args.wiki_root, findings, args.source_uuid or "last-ingest")
```

(Implementer: thread the resolved uuid out of `staleness_lint` cleanly — return `(findings, source_uuid)` or resolve the default before calling; match the file's existing style.)

- [ ] **Step 4: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add pipeline/phase_b_lint.py tests/test_lint_wiki.py
git commit -m "feat: --staleness lint mode — STALE_ENTITY findings for mentioned-but-uncited pages"
```

---

### Task 6: Documentation

**Files:**
- Create: `docs/architecture/deterministic-recall-floor.md` — problem (Bryant trace, 15.3% digest coverage), principle (LLM comprehension / mechanical recall), design decisions table from this plan's header, the embeddings trigger criteria (see plan appendix below)
- Modify: `CLAUDE.md` — add `recall_scan.py` row to Pipeline Modules table; add `--staleness` to the post-ingest lint command list (run after ingest, before/alongside structural); note the `scan-flagged` plan field in the Pass 1A description
- Modify: `CHANGELOG.md` — new dated entry, never edit past entries

- [ ] **Step 1: Write the three docs**
- [ ] **Step 2: Grep sweep** — `grep -rn "scan-flagged\|staleness\|recall_scan" CLAUDE.md docs/architecture/deterministic-recall-floor.md` reads coherently; no stale references
- [ ] **Step 3: Commit**

```bash
git add docs/architecture/deterministic-recall-floor.md CLAUDE.md CHANGELOG.md
git commit -m "docs: deterministic recall floor architecture + CLAUDE.md/CHANGELOG updates"
```

---

### Task 7: Real-data verification (no re-ingest, no LLM calls)

- [ ] **Step 1: Retroactive scan dry-run** — run the scanner against the already-ingested Year 5 source and diff against the recorded plan:

```bash
python -c "
from pipeline.recall_scan import build_entity_name_index, scan_source_for_known_entities
import json
idx = build_entity_name_index('wiki')
src = open('wiki/sources/annual-reports/a2zero-year5.md').read()
hits = scan_source_for_known_entities(src, idx)
plan = json.load(open('integration-plans/a2zero-year5.json'))
known = {e['slug'] for e in plan.get('extends',[])} | {e['slug'] for e in plan.get('new-entities',[])} | set(plan.get('retrieve-for-context',[]))
missed = sorted(set(hits) - known, key=lambda s: -hits[s]['mentions'])
print(f'{len(idx)} names indexed; {len(hits)} entities matched; {len(missed)} would have been scan-flagged:')
for s in missed: print(f\"  {hits[s]['mentions']:>3}x {s}\")
"
```

Expected: `initiatives/bryant-neighborhood-decarbonization` in the output (the regression proof), plus a plausible list (~10-40 entities). If the list exceeds ~80 entries, inspect for index noise (over-generic names) before proceeding.

Also report the budget behavior for this retroactive case: total chars of the would-be-added bodies plus Year 5's recorded 55,530 retrieved chars, vs. the 60k-token (~240k-char) budget. Expected: everything fits with headroom, `context-dropped` would be empty. If it wouldn't fit, that's a signal to revisit the budget number before merging — not after.

- [ ] **Step 2: Staleness lint against Year 5** — `python -m pipeline.phase_b_lint --wiki-root wiki --staleness --source-uuid a2zero-year5`; confirm `STALE_ENTITY` findings land in review-queue.md and include the Bryant page. **These findings are the remediation queue for the follow-up content-repair session — do not auto-fix; human triages per the standard review flow.**
- [ ] **Step 3: Full suite** — `python -m pytest tests/ -q`, all green
- [ ] **Step 4: Final commit, push branch, open PR**

```bash
git push -u origin feat/deterministic-recall
gh pr create --title "feat: deterministic recall floor + staleness lint" --body "..."
```

---

## Explicitly out of scope (deferred, with triggers)

- **Embedding-based retrieval** — deferred until a trigger fires; see `docs/architecture/deterministic-recall-floor.md` appendix. Triggers: (a) `STALE_ENTITY` review reveals recurring *paraphrase-only* mentions the string scan cannot see; (b) new source types with informal language land (council transcripts are the expected first case); (c) wiki exceeds ~1,000 entity pages.
- **Remediation of currently-stale pages** (Bryant Year-4/5 content, circular-economy Year-4 gap, remaining staleness-lint findings) — separate follow-up session using Task 7 Step 2's queue.
- **Duplicate pairs found in audit** (`green-rental-housing`/`green-rental-housing-program`, `sustaining-ann-arbor-together-*`) — route through the normal semantic-lint cycle.
