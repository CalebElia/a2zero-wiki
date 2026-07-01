# Comprehend → Plan → Write Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `wiki/digest.md` into the ingest pipeline by splitting the holistic synthesizer into a Comprehend pass (reads digest + source, produces a structured integration plan) and a Plan-guided Write pass (the existing Writer→Evaluator→Editor loop, now informed by the plan). Update LDP to consume the plan + retrieved entity page bodies.

**Architecture:** A new module `pipeline/comprehend.py` produces and persists integration plans to `wiki/integration-plans/<source-uuid>.json`. The plan flows downstream into both the holistic Writer pass and the LDP chunk extraction loop. Plans are validated via the existing `synthesis_validation` machinery to strip ghost slugs. Retrieved entity bodies are token-budget-capped (30k) and shared as a cached prefix across all chunks of a single ingest. Per-ingest telemetry lands in `wiki/meta/ingest-stats.jsonl`.

**Tech Stack:** Python 3.13, existing `pipeline/llm.py` `chat()`/`stream_chat()` wrappers, pytest, PyYAML, existing `pipeline/synthesis_validation.py` for ghost-slug stripping.

**Spec:** [docs/architecture/comprehend-plan-write.md](../../architecture/comprehend-plan-write.md)

**Branch:** `feat/digest-injection` (already checked out; do NOT switch).

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pipeline/comprehend.py` | Create | Comprehend LLM call + plan I/O + validation + token-budget capping |
| `tests/test_comprehend.py` | Create | Unit tests for plan generation, I/O roundtrip, validation, capping |
| `pipeline/holistic_synthesizer.py` | Modify | Replace `integration_block` (lines 341-352) with plan + digest injection; add small prompt addition for plan awareness |
| `pipeline/run_ingest.py` | Modify | Call `build_integration_plan` before `synthesize_source`; thread plan into downstream calls; append telemetry |
| `pipeline/ldp.py` | Modify | Load plan + retrieved entity bodies; thread into chunk extraction as cached prefix |
| `pipeline/wiki_writer.py` | Modify | `extract_wiki_pages_from_chunk` accepts plan-context kwargs; prepend to chunk prompt |
| `tests/test_holistic_synthesizer.py` | Modify | Update mocks for new plan-aware input context |
| `tests/test_ldp.py` | Modify | Update mocks for new plan-aware chunk extraction |
| `tests/test_run_ingest.py` | Modify | Add Comprehend orchestration tests (call sequence, hard-fail, fallback) |
| `wiki/integration-plans/.gitkeep` | Create | Bootstrap the directory |
| `wiki/integration-plans/README.md` | Create | One-paragraph explainer for humans browsing the vault |
| `wiki/meta/ingest-stats.jsonl` | Create empty | Per-ingest telemetry log |
| `CLAUDE.md` | Modify | Document Comprehend pass + plan artifacts |
| `CHANGELOG.md` | Modify | Append entry for this session |

---

### Task 1: Module skeleton + plan I/O

**Files:**
- Create: `pipeline/comprehend.py`
- Create: `tests/test_comprehend.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_comprehend.py
import json
from pathlib import Path
from pipeline.comprehend import empty_plan, write_integration_plan, load_integration_plan


def test_empty_plan_has_all_required_fields():
    plan = empty_plan()
    assert plan["strategies-touched"] == []
    assert plan["extends"] == []
    assert plan["new-entities"] == []
    assert plan["retrieve-for-context"] == []
    assert plan["theme-connections"] == []


def test_write_and_load_integration_plan_roundtrip(tmp_path):
    plans_dir = tmp_path / "integration-plans"
    plan = {
        "source-uuid": "test-source",
        "generated-at": "2026-06-29T18:00:00Z",
        "digest-rebuilt": "2026-06-29",
        "strategies-touched": ["strategies/strategy-1-renewable-grid"],
        "extends": [{"slug": "initiatives/solarize", "new-data": "Year 3 totals"}],
        "new-entities": [],
        "retrieve-for-context": ["initiatives/solarize"],
        "theme-connections": ["Grid capacity tied to electrification"],
    }
    out_path = write_integration_plan(plan, str(plans_dir))
    assert Path(out_path).exists()
    loaded = load_integration_plan(str(plans_dir), "test-source")
    assert loaded == plan


def test_load_integration_plan_returns_empty_when_missing(tmp_path):
    plans_dir = tmp_path / "integration-plans"
    plans_dir.mkdir()
    loaded = load_integration_plan(str(plans_dir), "nonexistent-source")
    # Falls back to empty plan rather than raising
    assert loaded["extends"] == []
    assert loaded["strategies-touched"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_comprehend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.comprehend'`

- [ ] **Step 3: Write minimal implementation**

```python
# pipeline/comprehend.py
"""Pass 1A — Comprehend → Integration Plan.

Reads wiki/digest.md plus the new source, produces a structured integration
plan that guides downstream passes (Writer→Evaluator→Editor + LDP).

See docs/architecture/comprehend-plan-write.md for design rationale.
"""
import json
from pathlib import Path


def empty_plan() -> dict:
    """Return the empty-plan skeleton used as fallback."""
    return {
        "source-uuid": "",
        "generated-at": "",
        "digest-rebuilt": "",
        "strategies-touched": [],
        "extends": [],
        "new-entities": [],
        "retrieve-for-context": [],
        "theme-connections": [],
    }


def write_integration_plan(plan: dict, plans_dir: str) -> str:
    """Write plan JSON to <plans_dir>/<source-uuid>.json. Returns absolute path."""
    out_dir = Path(plans_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{plan['source-uuid']}.json"
    out_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return str(out_path)


def load_integration_plan(plans_dir: str, source_uuid: str) -> dict:
    """Load plan from disk. Returns empty_plan() if file missing (graceful fallback)."""
    path = Path(plans_dir) / f"{source_uuid}.json"
    if not path.exists():
        return empty_plan()
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_comprehend.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/comprehend.py tests/test_comprehend.py
git commit -m "feat(comprehend): module skeleton + empty_plan + plan I/O roundtrip"
```

---

### Task 2: `build_integration_plan()` LLM call

**Files:**
- Modify: `pipeline/comprehend.py`
- Modify: `tests/test_comprehend.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_comprehend.py`:

```python
from unittest.mock import patch
from pipeline.comprehend import build_integration_plan


def test_build_integration_plan_returns_empty_when_no_digest():
    """First-ingest path: no digest yet → empty plan, no LLM call."""
    with patch("pipeline.comprehend.chat") as mock_chat:
        plan = build_integration_plan(
            source_content="some source text",
            source_uuid="first-source",
            digest_content=None,
            run_date="2026-06-29",
        )
    assert mock_chat.call_count == 0  # No LLM call when digest is absent
    assert plan["source-uuid"] == "first-source"
    assert plan["extends"] == []
    assert plan["strategies-touched"] == []


def test_build_integration_plan_calls_llm_and_parses_json():
    llm_output = json.dumps({
        "strategies-touched": ["strategies/strategy-1-renewable-grid"],
        "extends": [{"slug": "initiatives/solarize-ann-arbor", "new-data": "Y3 totals"}],
        "new-entities": [],
        "retrieve-for-context": ["initiatives/solarize-ann-arbor"],
        "theme-connections": [],
    })
    with patch("pipeline.comprehend.chat") as mock_chat:
        mock_chat.return_value = llm_output
        plan = build_integration_plan(
            source_content="source text",
            source_uuid="test-source",
            digest_content="# Wiki Digest\n\n## Cross-strategy synthesis\n...",
            run_date="2026-06-29",
        )
    assert mock_chat.call_count == 1
    assert plan["source-uuid"] == "test-source"
    assert plan["digest-rebuilt"]  # stamped from digest content if present, else empty
    assert plan["strategies-touched"] == ["strategies/strategy-1-renewable-grid"]
    assert plan["extends"][0]["slug"] == "initiatives/solarize-ann-arbor"


def test_build_integration_plan_handles_fenced_json():
    llm_output = "```json\n" + json.dumps({
        "strategies-touched": [],
        "extends": [],
        "new-entities": [],
        "retrieve-for-context": [],
        "theme-connections": [],
    }) + "\n```"
    with patch("pipeline.comprehend.chat") as mock_chat:
        mock_chat.return_value = llm_output
        plan = build_integration_plan(
            source_content="x",
            source_uuid="t",
            digest_content="d",
            run_date="2026-06-29",
        )
    assert plan["extends"] == []


def test_build_integration_plan_hard_fails_on_llm_error_when_digest_present():
    """Per spec: digest exists + LLM fails → hard fail (do not silently degrade)."""
    with patch("pipeline.comprehend.chat") as mock_chat:
        mock_chat.side_effect = Exception("API error")
        try:
            build_integration_plan(
                source_content="source",
                source_uuid="test",
                digest_content="# Digest",
                run_date="2026-06-29",
            )
        except Exception as e:
            assert "comprehend" in str(e).lower() or "API error" in str(e)
            return
        raise AssertionError("Expected hard fail, got silent return")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_comprehend.py::test_build_integration_plan_calls_llm_and_parses_json -v`
Expected: FAIL with `ImportError: cannot import name 'build_integration_plan'`

- [ ] **Step 3: Implement**

Append to `pipeline/comprehend.py`:

```python
import re
from datetime import datetime, timezone
from pipeline.llm import chat


_COMPREHEND_SYSTEM = """You are the Comprehend pass for the A2Zero knowledge wiki ingest pipeline.

You will receive:
1. The current wiki digest (compressed prior over what the wiki knows)
2. A new source document to be ingested

Your job: produce a structured integration plan that downstream extraction passes will use.

Return ONLY a JSON object with EXACTLY these keys:

- strategies-touched: list of strategy slugs (e.g. "strategies/strategy-1-renewable-grid") \
  that this source meaningfully affects
- extends: list of {slug, new-data} objects for EXISTING entities the source adds new \
  information to. The slug must reference a real entity from the digest. The new-data is \
  a one-sentence hint describing what the source contributes.
- new-entities: list of {slug, type, title, rationale} objects for entities NOT yet in \
  the wiki that the source introduces and that warrant a dedicated page. Type must be one \
  of: actor, initiative, location, technology, funding-event, meeting, political-event.
- retrieve-for-context: list of existing entity slugs whose page bodies should be loaded \
  as reference context during chunk-by-chunk extraction. Include entities in `extends` \
  and any other existing entities the source heavily references. Aim for 5-15 entities.
- theme-connections: list of 2-5 short strings describing cross-strategy patterns this \
  source surfaces (e.g. "Source ties grid capacity to building electrification timeline").

Use slug references from the digest's entity map. Do not invent slugs for existing entities. \
For `new-entities`, use kebab-case slugs that follow project conventions.

Return ONLY the JSON object. No preamble, no code fences, no commentary.
"""


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:-1]) if len(lines) > 2 else t
    return t.strip()


def _extract_digest_rebuilt(digest_content: str) -> str:
    """Pull the last-rebuilt date from digest frontmatter, or empty string."""
    m = re.search(r"^last-rebuilt:\s*['\"]?(\d{4}-\d{2}-\d{2})", digest_content, re.MULTILINE)
    return m.group(1) if m else ""


def build_integration_plan(
    source_content: str,
    source_uuid: str,
    digest_content: str | None,
    run_date: str,
) -> dict:
    """Comprehend LLM call: read digest + source, produce structured integration plan.

    Two failure modes per spec:
    - No digest (digest_content is None): silent fallback, no LLM call, returns empty plan
      stamped with source-uuid. This is the first-ingest path.
    - Digest present but LLM call fails: HARD FAIL — raises the exception. The caller
      (run_ingest.py) halts the ingest before any downstream tokens are spent.
    """
    plan = empty_plan()
    plan["source-uuid"] = source_uuid
    plan["generated-at"] = datetime.now(timezone.utc).isoformat()

    if digest_content is None:
        # First-ingest fallback: no digest exists yet
        return plan

    plan["digest-rebuilt"] = _extract_digest_rebuilt(digest_content)

    user_msg = (
        f"[WIKI DIGEST]\n{digest_content}\n[END DIGEST]\n\n"
        f"[NEW SOURCE — uuid={source_uuid}, ingest_date={run_date}]\n"
        f"{source_content}\n[END SOURCE]\n\n"
        "Produce the integration plan JSON now."
    )

    raw = chat(
        system=_COMPREHEND_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=4096,
        model_hint="synthesis",
        temperature=0.0,
    )
    parsed = json.loads(_strip_code_fence(raw))

    # Merge into plan skeleton (preserves source-uuid, generated-at, digest-rebuilt)
    for k in ("strategies-touched", "extends", "new-entities",
              "retrieve-for-context", "theme-connections"):
        if k in parsed:
            plan[k] = parsed[k]
    return plan
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_comprehend.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/comprehend.py tests/test_comprehend.py
git commit -m "feat(comprehend): build_integration_plan() LLM call with first-ingest fallback and hard-fail semantics"
```

---

### Task 3: Plan validation (reuse synthesis_validation)

**Files:**
- Modify: `pipeline/comprehend.py`
- Modify: `tests/test_comprehend.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_comprehend.py`:

```python
from pipeline.comprehend import validate_plan_slugs


def test_validate_plan_slugs_strips_ghost_entries(tmp_path):
    """Plan with slugs pointing to nonexistent pages → ghosts removed."""
    # Set up a tiny wiki with one real entity
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "initiatives" / "solarize.md").write_text("---\ntype: initiative\n---\n", encoding="utf-8")

    plan = {
        "source-uuid": "test",
        "generated-at": "2026-06-29",
        "digest-rebuilt": "2026-06-29",
        "strategies-touched": [],
        "extends": [
            {"slug": "initiatives/solarize", "new-data": "real"},
            {"slug": "initiatives/ghost-entity", "new-data": "fake"},
        ],
        "new-entities": [],
        "retrieve-for-context": ["initiatives/solarize", "initiatives/another-ghost"],
        "theme-connections": [],
    }
    cleaned = validate_plan_slugs(plan, wiki_root=str(wiki), aliases={})
    # extends: ghost dropped
    extend_slugs = [e["slug"] for e in cleaned["extends"]]
    assert extend_slugs == ["initiatives/solarize"]
    # retrieve-for-context: ghost dropped
    assert cleaned["retrieve-for-context"] == ["initiatives/solarize"]
    # new-entities: untouched (these are proposed pages that don't exist YET)
    assert cleaned["new-entities"] == []


def test_validate_plan_slugs_resolves_aliases(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "actors").mkdir(parents=True)
    (wiki / "actors" / "office-of-sustainability-and-innovations.md").write_text(
        "---\ntype: actor\n---\n", encoding="utf-8"
    )
    aliases = {
        "a2zero-office": {
            "canonical": "actors/office-of-sustainability-and-innovations",
            "type": "actor", "aliases": [], "relationship": "name-variant",
        }
    }
    plan = {
        "source-uuid": "t", "generated-at": "x", "digest-rebuilt": "y",
        "strategies-touched": [], "new-entities": [], "theme-connections": [],
        "extends": [{"slug": "actors/a2zero-office", "new-data": "x"}],
        "retrieve-for-context": ["actors/a2zero-office"],
    }
    cleaned = validate_plan_slugs(plan, wiki_root=str(wiki), aliases=aliases)
    assert cleaned["extends"][0]["slug"] == "actors/office-of-sustainability-and-innovations"
    assert cleaned["retrieve-for-context"] == ["actors/office-of-sustainability-and-innovations"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_comprehend.py::test_validate_plan_slugs_strips_ghost_entries -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `pipeline/comprehend.py`:

```python
from pipeline.synthesis_validation import _exists, _resolve_alias, SUPPRESS_SLUGS


def validate_plan_slugs(plan: dict, wiki_root: str, aliases: dict) -> dict:
    """Strip ghost slugs from `extends` and `retrieve-for-context`.

    Reuses synthesis_validation helpers — applies alias resolution, suppress list,
    then drops anything whose page doesn't exist. `new-entities` is left alone
    (those slugs are intentionally for pages that DON'T exist yet).
    """
    cleaned = dict(plan)

    # extends: list of {slug, new-data} — filter on slug
    cleaned_extends = []
    seen_extends: set[str] = set()
    for item in plan.get("extends") or []:
        slug = item.get("slug", "")
        resolved = _resolve_alias(slug, aliases)
        if not resolved or resolved in SUPPRESS_SLUGS or resolved in seen_extends:
            continue
        if not _exists(resolved, wiki_root):
            continue
        seen_extends.add(resolved)
        cleaned_extends.append({**item, "slug": resolved})
    cleaned["extends"] = cleaned_extends

    # retrieve-for-context: list of slugs — filter directly
    cleaned_retrieve = []
    seen_retrieve: set[str] = set()
    for slug in plan.get("retrieve-for-context") or []:
        resolved = _resolve_alias(slug, aliases)
        if not resolved or resolved in SUPPRESS_SLUGS or resolved in seen_retrieve:
            continue
        if not _exists(resolved, wiki_root):
            continue
        seen_retrieve.add(resolved)
        cleaned_retrieve.append(resolved)
    cleaned["retrieve-for-context"] = cleaned_retrieve

    return cleaned
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_comprehend.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/comprehend.py tests/test_comprehend.py
git commit -m "feat(comprehend): validate_plan_slugs() reuses synthesis_validation to strip ghosts"
```

---

### Task 4: Token-budget cap for `retrieve-for-context`

**Files:**
- Modify: `pipeline/comprehend.py`
- Modify: `tests/test_comprehend.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_comprehend.py`:

```python
from pipeline.comprehend import load_retrieved_bodies, RETRIEVE_TOKEN_BUDGET


def test_load_retrieved_bodies_returns_under_budget(tmp_path):
    """Small wiki, all pages fit → all returned."""
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    for slug_stem in ["a", "b", "c"]:
        (wiki / "initiatives" / f"{slug_stem}.md").write_text(
            f"---\ntype: initiative\n---\nShort body {slug_stem}\n", encoding="utf-8"
        )
    plan = {
        "extends": [],
        "retrieve-for-context": ["initiatives/a", "initiatives/b", "initiatives/c"],
        "theme-connections": [],
    }
    bodies = load_retrieved_bodies(plan, str(wiki))
    assert set(bodies.keys()) == {"initiatives/a", "initiatives/b", "initiatives/c"}
    for slug, body in bodies.items():
        assert "Short body" in body


def test_load_retrieved_bodies_prioritizes_extends_when_over_budget(tmp_path, monkeypatch):
    """When over budget: extends entries kept first, others dropped."""
    # Shrink budget for the test
    monkeypatch.setattr("pipeline.comprehend.RETRIEVE_TOKEN_BUDGET", 200)
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    # Create pages where each body is roughly ~100 tokens (400+ chars)
    big_body = "word " * 200  # ~200 tokens
    for stem in ["in-extends", "not-in-extends-1", "not-in-extends-2"]:
        (wiki / "initiatives" / f"{stem}.md").write_text(
            f"---\ntype: initiative\n---\n{big_body}\n", encoding="utf-8"
        )
    plan = {
        "extends": [{"slug": "initiatives/in-extends", "new-data": "x"}],
        "retrieve-for-context": [
            "initiatives/not-in-extends-1",
            "initiatives/in-extends",
            "initiatives/not-in-extends-2",
        ],
        "theme-connections": [],
    }
    bodies = load_retrieved_bodies(plan, str(wiki))
    # Extends entry is included; one or both of the others gets dropped
    assert "initiatives/in-extends" in bodies
    total_chars = sum(len(b) for b in bodies.values())
    assert total_chars < 200 * 5  # under budget (4 chars/token heuristic)


def test_load_retrieved_bodies_skips_missing_files(tmp_path):
    """Ghost slugs in retrieve-for-context are silently dropped."""
    wiki = tmp_path / "wiki"
    (wiki / "initiatives").mkdir(parents=True)
    (wiki / "initiatives" / "real.md").write_text("---\ntype: initiative\n---\nbody\n", encoding="utf-8")
    plan = {
        "extends": [],
        "retrieve-for-context": ["initiatives/real", "initiatives/ghost"],
        "theme-connections": [],
    }
    bodies = load_retrieved_bodies(plan, str(wiki))
    assert set(bodies.keys()) == {"initiatives/real"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_comprehend.py::test_load_retrieved_bodies_returns_under_budget -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `pipeline/comprehend.py`:

```python
RETRIEVE_TOKEN_BUDGET = 30000  # ~4 chars/token heuristic → ~120k chars
_CHARS_PER_TOKEN = 4


def load_retrieved_bodies(plan: dict, wiki_root: str) -> dict[str, str]:
    """Load entity page bodies for slugs in `retrieve-for-context`, prioritized
    by `extends` then plan-mention frequency, capped at RETRIEVE_TOKEN_BUDGET.

    Returns dict mapping slug → body text. Pages whose load would exceed budget
    are silently dropped (long-tail entities fall back to existing _merge_pages).
    """
    extends_slugs = {e.get("slug", "") for e in plan.get("extends") or []}
    retrieve_slugs = plan.get("retrieve-for-context") or []

    # Mention frequency across plan fields (used as secondary priority)
    text_blob = json.dumps(plan)
    def _mention_count(slug: str) -> int:
        return text_blob.count(slug)

    # Sort: extends-first, then by mention frequency (desc), then by slug for stability
    ordered = sorted(
        retrieve_slugs,
        key=lambda s: (s not in extends_slugs, -_mention_count(s), s),
    )

    bodies: dict[str, str] = {}
    char_budget = RETRIEVE_TOKEN_BUDGET * _CHARS_PER_TOKEN
    used = 0
    for slug in ordered:
        page_path = Path(wiki_root) / f"{slug}.md"
        if not page_path.exists():
            continue
        try:
            raw = page_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Strip frontmatter; keep body only
        body = re.sub(r"^---\n.*?\n---\n", "", raw, flags=re.DOTALL).strip()
        body_len = len(body)
        if used + body_len > char_budget:
            continue  # drop overflow silently
        bodies[slug] = body
        used += body_len
    return bodies
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_comprehend.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/comprehend.py tests/test_comprehend.py
git commit -m "feat(comprehend): load_retrieved_bodies() with 30k token-budget cap and extends-first priority"
```

---

### Task 5: Directory bootstrap + README

**Files:**
- Create: `wiki/integration-plans/.gitkeep`
- Create: `wiki/integration-plans/README.md`
- Create: `wiki/meta/ingest-stats.jsonl` (empty file)

- [ ] **Step 1: Create the directory and files**

```bash
mkdir -p wiki/integration-plans
touch wiki/integration-plans/.gitkeep
touch wiki/meta/ingest-stats.jsonl
```

- [ ] **Step 2: Write the README**

```bash
cat > wiki/integration-plans/README.md <<'EOF'
# Integration Plans

This directory contains structured JSON integration plans produced by the **Comprehend** pass at the start of each source ingest. Each file is named `<source-uuid>.json` and reflects how the Comprehend LLM mapped that source onto the wiki's existing state.

## What's in a plan

Each plan has five fields:

- **strategies-touched** — which A2Zero strategies the source affects
- **extends** — existing entity pages the source contributes new data to
- **new-entities** — entities the source introduces that warrant new pages
- **retrieve-for-context** — existing entity bodies that get pre-loaded into the LDP chunk extraction prompts as integration context
- **theme-connections** — cross-strategy patterns the source surfaces

## Why they're committed

Plans are part of the audit trail. They document *why* the pipeline made specific integration decisions during each ingest, which helps when reviewing entity merges, debugging false splits, or auditing how a controversial claim was integrated.

## Lifecycle

Plans are overwritten on re-ingest of the same source. Use `git log <plan-path>` to see prior versions.

See `docs/architecture/comprehend-plan-write.md` for the full architecture.
EOF
```

- [ ] **Step 3: Commit**

```bash
git add wiki/integration-plans/.gitkeep wiki/integration-plans/README.md wiki/meta/ingest-stats.jsonl
git commit -m "chore: bootstrap wiki/integration-plans/ and wiki/meta/ingest-stats.jsonl"
```

---

### Task 6: Telemetry helper

**Files:**
- Modify: `pipeline/comprehend.py`
- Modify: `tests/test_comprehend.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_comprehend.py`:

```python
from pipeline.comprehend import log_ingest_stats


def test_log_ingest_stats_appends_jsonl(tmp_path):
    log_path = tmp_path / "ingest-stats.jsonl"
    log_ingest_stats(
        log_path=str(log_path),
        source_uuid="a2zero-year3",
        run_date="2026-07-15",
        comprehend_skipped=False,
        plan_size_bytes=2048,
        extends_count=4,
        new_entities_count=2,
        retrieve_count=8,
        retrieved_chars=12000,
    )
    # Append a second entry
    log_ingest_stats(
        log_path=str(log_path),
        source_uuid="a2zero-year4",
        run_date="2026-08-01",
        comprehend_skipped=False,
        plan_size_bytes=1500,
        extends_count=2,
        new_entities_count=0,
        retrieve_count=5,
        retrieved_chars=6000,
    )
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    entry1 = json.loads(lines[0])
    assert entry1["source-uuid"] == "a2zero-year3"
    assert entry1["extends-count"] == 4
    entry2 = json.loads(lines[1])
    assert entry2["source-uuid"] == "a2zero-year4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_comprehend.py::test_log_ingest_stats_appends_jsonl -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `pipeline/comprehend.py`:

```python
def log_ingest_stats(
    log_path: str,
    source_uuid: str,
    run_date: str,
    comprehend_skipped: bool,
    plan_size_bytes: int,
    extends_count: int,
    new_entities_count: int,
    retrieve_count: int,
    retrieved_chars: int,
) -> None:
    """Append one JSON line of per-ingest stats. Cheap monitoring for ingest health."""
    entry = {
        "source-uuid": source_uuid,
        "run-date": run_date,
        "comprehend-skipped": comprehend_skipped,
        "plan-size-bytes": plan_size_bytes,
        "extends-count": extends_count,
        "new-entities-count": new_entities_count,
        "retrieve-count": retrieve_count,
        "retrieved-chars": retrieved_chars,
    }
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_comprehend.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/comprehend.py tests/test_comprehend.py
git commit -m "feat(comprehend): log_ingest_stats() telemetry helper for ingest-stats.jsonl"
```

---

### Task 7: Wire Comprehend + plan into `holistic_synthesizer.py`

**Files:**
- Modify: `pipeline/holistic_synthesizer.py`
- Modify: `tests/test_holistic_synthesizer.py`

This task replaces the existing `integration_block` (lines 341-352) with a new context block that includes the integration plan + digest. The Writer/Evaluator/Editor prompts get a small addition referencing the plan.

- [ ] **Step 1: Update `synthesize_source()` signature and integration block**

Edit `pipeline/holistic_synthesizer.py`:

Change the `synthesize_source()` signature to accept the new optional kwargs:

```python
def synthesize_source(
    source_content: str,
    source_uuid: str,
    source_rel_path: str,
    source_type: str,
    wiki_root: str,
    run_date: str,
    max_retries: int = 2,
    integration_plan: dict | None = None,
    digest_content: str | None = None,
) -> dict | None:
```

Replace the block at lines 332-352 (the `existing_strategy_content` loop and `integration_block` assembly) with:

```python
    # Build the integration block from the digest + integration plan (preferred).
    # Falls back to raw strategy bodies if no digest is available (first-ingest path).
    integration_block = ""
    if digest_content or integration_plan:
        lines = [
            "\n\n[INTEGRATION PLAN — read this first]",
            "The Comprehend pass has produced a structured plan for how this source",
            "should be integrated. Use it to guide which strategies to extend, which",
            "entities to update vs. create, and which existing content to preserve.\n",
            json.dumps(integration_plan or {}, indent=2),
            "[END INTEGRATION PLAN]\n",
        ]
        if digest_content:
            lines.extend([
                "\n[WIKI DIGEST — current state of the wiki]",
                "READ-UNDERSTAND-INTEGRATE: this digest reflects what the wiki already",
                "knows. Build on it rather than re-stating known facts.\n",
                digest_content,
                "[END WIKI DIGEST]",
            ])
        integration_block = "\n".join(lines)
    else:
        # Fallback: legacy behavior — inject raw strategy bodies
        existing_strategy_content: dict[str, str] = {}
        strategies_dir = Path(wiki_root) / "strategies"
        if strategies_dir.exists():
            for strat_file in sorted(strategies_dir.glob("*.md")):
                content = strat_file.read_text(encoding="utf-8")
                body = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL).strip()
                if re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip():
                    existing_strategy_content[f"strategies/{strat_file.stem}"] = body
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
```

- [ ] **Step 2: Add test for plan-aware injection**

Append to `tests/test_holistic_synthesizer.py`:

```python
@patch("pipeline.holistic_synthesizer.stream_chat")
def test_synthesize_source_injects_integration_plan_and_digest(mock_stream_chat, tmp_path):
    """Plan + digest replace the legacy strategy-body integration block."""
    mock_stream_chat.side_effect = [
        {"overview": {"slug": "overviews/test", "frontmatter": {"type": "overview", "title": "T", "source-ref": "[[sources/test/test]]"}, "body": "Overview body"}, "strategy_bodies": [{"slug": f"strategies/strategy-{i}-x", "body": "body"} for i in range(1, 8)], "stub_pages": [], "log_summary": "ok"},
        {"proceed_to_edit": True, "overall_score": 9},
        {"overview": {"slug": "overviews/test", "frontmatter": {"type": "overview", "title": "T", "source-ref": "[[sources/test/test]]"}, "body": "Edited overview"}, "strategy_bodies": [{"slug": f"strategies/strategy-{i}-x", "body": "edited"} for i in range(1, 8)], "stub_pages": [], "log_summary": "edited"},
    ]
    # Stage minimum strategy stubs so validate_synthesis_output passes
    strategies = tmp_path / "strategies"
    strategies.mkdir()
    for i in range(1, 8):
        (strategies / f"strategy-{i}-x.md").write_text("---\ntype: strategy\n---\n", encoding="utf-8")
    (tmp_path / "overviews").mkdir()
    (tmp_path / "sources" / "test").mkdir(parents=True)

    plan = {"source-uuid": "test", "extends": [{"slug": "x", "new-data": "y"}], "strategies-touched": ["strategies/strategy-1-x"], "new-entities": [], "retrieve-for-context": [], "theme-connections": []}
    digest = "# Wiki Digest\n\nDigest content here.\n"

    synthesize_source(
        source_content="---\nuuid: test\n---\nSource body",
        source_uuid="test", source_rel_path="sources/test/test",
        source_type="test", wiki_root=str(tmp_path), run_date="2026-06-29",
        integration_plan=plan, digest_content=digest,
    )

    # The first call (Writer) should have received the plan + digest in its user content
    first_call_user_content = mock_stream_chat.call_args_list[0].kwargs["messages"][0]["content"]
    # Content is a list with one cache_control block whose 'text' contains both
    text = first_call_user_content[0]["text"] if isinstance(first_call_user_content, list) else first_call_user_content
    assert "INTEGRATION PLAN" in text
    assert "WIKI DIGEST" in text
    assert "Digest content here" in text
```

- [ ] **Step 3: Run the new test and all existing tests**

Run: `python -m pytest tests/test_holistic_synthesizer.py -v`
Expected: All existing tests pass (legacy fallback path is unchanged when plan/digest are None); new test passes.

If any existing test fails because the integration_block format changed: those tests pass `integration_plan=None, digest_content=None` implicitly via the default, so they should hit the fallback branch which is byte-equivalent to today's behavior. Investigate any failure carefully.

- [ ] **Step 4: Commit**

```bash
git add pipeline/holistic_synthesizer.py tests/test_holistic_synthesizer.py
git commit -m "feat(holistic): accept integration_plan + digest_content; replace integration_block with plan-aware injection"
```

---

### Task 8: Wire Comprehend orchestration into `run_ingest.py`

**Files:**
- Modify: `pipeline/run_ingest.py`
- Modify: `tests/test_run_ingest.py`

This task loads the digest, calls `build_integration_plan`, validates the plan, persists it, and passes it to `synthesize_source`. Hard-fails when digest exists but Comprehend raises.

- [ ] **Step 1: Update `run_source_ingest()` to orchestrate Comprehend**

In `pipeline/run_ingest.py`, after the source-type extraction block (around line 107) and BEFORE the `if quads_only` block, insert:

```python
    # ── Pass 1A: Comprehend → integration plan ───────────────────────────────
    from pipeline.comprehend import (
        build_integration_plan,
        validate_plan_slugs,
        write_integration_plan,
        load_retrieved_bodies,
        log_ingest_stats,
    )
    from pipeline.alias_registry import load_aliases
    import time as _time

    digest_path = Path(wiki_root) / "digest.md"
    digest_content = digest_path.read_text(encoding="utf-8") if digest_path.exists() else None

    integration_plan = None
    retrieved_bodies: dict[str, str] = {}
    if not quads_only:
        comprehend_start = _time.time()
        # Hard-fail when digest exists; graceful fallback only when no digest at all.
        # build_integration_plan() raises if the LLM call fails with a digest present.
        integration_plan = build_integration_plan(
            source_content=source_content,
            source_uuid=uuid,
            digest_content=digest_content,
            run_date=run_date,
        )
        # Strip ghost slugs (reuses synthesis_validation machinery)
        _aliases = load_aliases("registry/entity_aliases.json")
        integration_plan = validate_plan_slugs(integration_plan, wiki_root, _aliases)
        # Persist plan for audit trail and for LDP to consume
        plans_dir = Path(wiki_root) / "integration-plans"
        plan_path = write_integration_plan(integration_plan, str(plans_dir))
        print(f"[ingest] {uuid}: integration plan written → {plan_path}")
        # Pre-load entity bodies for retrieve-for-context (token-budget capped)
        retrieved_bodies = load_retrieved_bodies(integration_plan, wiki_root)
        # Telemetry: per-ingest stats
        stats_path = Path(wiki_root) / "meta" / "ingest-stats.jsonl"
        log_ingest_stats(
            log_path=str(stats_path),
            source_uuid=uuid,
            run_date=run_date,
            comprehend_skipped=(digest_content is None),
            plan_size_bytes=len(json.dumps(integration_plan)),
            extends_count=len(integration_plan.get("extends", [])),
            new_entities_count=len(integration_plan.get("new-entities", [])),
            retrieve_count=len(integration_plan.get("retrieve-for-context", [])),
            retrieved_chars=sum(len(b) for b in retrieved_bodies.values()),
        )
        print(f"[ingest] {uuid}: comprehend took {_time.time() - comprehend_start:.1f}s "
              f"(extends={len(integration_plan.get('extends', []))}, "
              f"new={len(integration_plan.get('new-entities', []))}, "
              f"retrieve={len(integration_plan.get('retrieve-for-context', []))})")
```

Add `import json` at the top of the file if not already present.

Then update the `synthesize_source` call inside the `else` branch to pass the new kwargs:

```python
        synthesis_result = synthesize_source(
            source_content=source_content,
            source_uuid=uuid,
            source_rel_path=source_rel_path,
            source_type=source_type,
            wiki_root=wiki_root,
            run_date=run_date,
            integration_plan=integration_plan,
            digest_content=digest_content,
        )
```

And update the `run_ldp_ingest` call to pass the plan + retrieved bodies (the actual threading into LDP happens in Task 9; for now just pass them through):

```python
        run_ldp_ingest(
            source_content=source_content,
            uuid=uuid,
            title=title,
            quads_path=quads_path,
            source_rel_path=source_rel_path,
            wiki_root=wiki_root,
            source_type=source_type,
            section_maps_dir=section_maps_dir,
            run_date=run_date,
            wiki_only=wiki_only,
            quads_only=quads_only,
            entity_context=entity_context,
            integration_plan=integration_plan,
            retrieved_bodies=retrieved_bodies,
        )
```

(The `integration_plan` and `retrieved_bodies` kwargs will be added to `run_ldp_ingest` in Task 9. For now, add `**kwargs` capture or skip these kwargs if Task 9 hasn't landed — but since these tasks are sequential, plan to add them now and Task 9 will consume them.)

Actually — to keep this task green standalone, comment out the two new kwargs until Task 9 wires them in:

```python
        run_ldp_ingest(
            source_content=source_content,
            uuid=uuid,
            title=title,
            quads_path=quads_path,
            source_rel_path=source_rel_path,
            wiki_root=wiki_root,
            source_type=source_type,
            section_maps_dir=section_maps_dir,
            run_date=run_date,
            wiki_only=wiki_only,
            quads_only=quads_only,
            entity_context=entity_context,
            # integration_plan and retrieved_bodies passed in Task 9
        )
```

- [ ] **Step 2: Update existing `tests/test_run_ingest.py` and add Comprehend tests**

Read the current `tests/test_run_ingest.py` and add a new test that exercises the Comprehend orchestration. Append:

```python
@patch("pipeline.run_ingest.synthesize_source")
@patch("pipeline.run_ingest.run_ldp_ingest")
@patch("pipeline.run_ingest.rebuild_index")
@patch("pipeline.run_ingest.wiki_append_log")
@patch("pipeline.run_ingest.run_post_ingest")
@patch("pipeline.comprehend.chat")
def test_run_source_ingest_calls_comprehend_when_digest_exists(
    mock_comprehend_chat, mock_post, mock_log, mock_rebuild, mock_ldp, mock_synth, tmp_path
):
    """Digest present → Comprehend fires → plan persisted → synthesize_source receives plan."""
    import json as _json

    # Stage wiki with a digest
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "digest.md").write_text("---\nlast-rebuilt: '2026-06-29'\n---\n# Digest\nBody.\n", encoding="utf-8")
    (wiki / "meta").mkdir()
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "test.md"
    src_path.write_text("---\nuuid: test\nsource_type: annual-report\n---\nSource body.\n", encoding="utf-8")

    # Mock Comprehend to return a valid plan
    mock_comprehend_chat.return_value = _json.dumps({
        "strategies-touched": ["strategies/strategy-1-renewable-grid"],
        "extends": [],
        "new-entities": [],
        "retrieve-for-context": [],
        "theme-connections": [],
    })
    mock_synth.return_value = {"stub_pages": []}
    mock_post.return_value = type("R", (), {"total_quads": 0, "schema_errors": [], "dark_matter_ids": []})()

    from pipeline.run_ingest import run_source_ingest
    run_source_ingest(
        source_path=str(src_path),
        uuid="test",
        title="Test",
        quads_path=str(tmp_path / "quads.jsonl"),
        wiki_root=str(wiki),
        review_queue_path=str(tmp_path / "queue.md"),
        run_date="2026-06-29",
    )

    # Comprehend was called
    assert mock_comprehend_chat.call_count == 1
    # Plan was persisted
    assert (wiki / "integration-plans" / "test.json").exists()
    # Stats line was appended
    assert (wiki / "meta" / "ingest-stats.jsonl").exists()
    # synthesize_source received the plan + digest
    synth_kwargs = mock_synth.call_args.kwargs
    assert synth_kwargs.get("integration_plan") is not None
    assert synth_kwargs.get("digest_content") is not None


@patch("pipeline.run_ingest.synthesize_source")
@patch("pipeline.run_ingest.rebuild_index")
@patch("pipeline.run_ingest.wiki_append_log")
@patch("pipeline.run_ingest.run_post_ingest")
@patch("pipeline.comprehend.chat")
def test_run_source_ingest_hard_fails_when_comprehend_errors_with_digest(
    mock_comprehend_chat, mock_post, mock_log, mock_rebuild, mock_synth, tmp_path
):
    """Digest present + Comprehend raises → ingest halts before any downstream work."""
    import pytest

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "digest.md").write_text("---\nlast-rebuilt: '2026-06-29'\n---\n# Digest\n", encoding="utf-8")
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "test.md"
    src_path.write_text("---\nuuid: test\n---\nBody\n", encoding="utf-8")

    mock_comprehend_chat.side_effect = Exception("API down")

    from pipeline.run_ingest import run_source_ingest
    with pytest.raises(Exception, match="API down"):
        run_source_ingest(
            source_path=str(src_path),
            uuid="test", title="T", quads_path=str(tmp_path / "q.jsonl"),
            wiki_root=str(wiki), review_queue_path=str(tmp_path / "queue.md"),
            run_date="2026-06-29",
        )
    # Downstream calls never fired
    assert mock_synth.call_count == 0
    assert mock_rebuild.call_count == 0


@patch("pipeline.run_ingest.synthesize_source")
@patch("pipeline.run_ingest.run_ldp_ingest")
@patch("pipeline.run_ingest.rebuild_index")
@patch("pipeline.run_ingest.wiki_append_log")
@patch("pipeline.run_ingest.run_post_ingest")
@patch("pipeline.comprehend.chat")
def test_run_source_ingest_skips_comprehend_when_no_digest(
    mock_comprehend_chat, mock_post, mock_log, mock_rebuild, mock_ldp, mock_synth, tmp_path
):
    """First ingest: no digest → graceful fallback, no LLM call, empty plan."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    # NOTE: no digest.md
    (wiki / "sources" / "annual-reports").mkdir(parents=True)
    src_path = wiki / "sources" / "annual-reports" / "test.md"
    src_path.write_text("---\nuuid: test\n---\nBody\n", encoding="utf-8")

    mock_synth.return_value = {"stub_pages": []}
    mock_post.return_value = type("R", (), {"total_quads": 0, "schema_errors": [], "dark_matter_ids": []})()

    from pipeline.run_ingest import run_source_ingest
    run_source_ingest(
        source_path=str(src_path),
        uuid="test", title="T", quads_path=str(tmp_path / "q.jsonl"),
        wiki_root=str(wiki), review_queue_path=str(tmp_path / "queue.md"),
        run_date="2026-06-29",
    )

    # No LLM call (graceful fallback)
    assert mock_comprehend_chat.call_count == 0
    # An empty plan was still written for the audit trail
    assert (wiki / "integration-plans" / "test.json").exists()
    # synthesize_source received digest_content=None
    synth_kwargs = mock_synth.call_args.kwargs
    assert synth_kwargs.get("digest_content") is None
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_run_ingest.py -v`
Expected: PASS (existing + 3 new tests).

If existing tests fail because `synthesize_source` now receives `integration_plan` and `digest_content` kwargs, those tests need their mocks updated to accept the additional kwargs (most use `mock_synth.call_args.kwargs` patterns that already tolerate this).

- [ ] **Step 4: Commit**

```bash
git add pipeline/run_ingest.py tests/test_run_ingest.py
git commit -m "feat(ingest): Pass 1A Comprehend orchestration — load digest, build plan, validate, persist, hard-fail on errors"
```

---

### Task 9: Thread plan + retrieved bodies into LDP and wiki_writer

**Files:**
- Modify: `pipeline/ldp.py`
- Modify: `pipeline/wiki_writer.py`
- Modify: `pipeline/run_ingest.py` (uncomment the kwargs from Task 8)
- Modify: `tests/test_ldp.py`

This task adds `integration_plan` and `retrieved_bodies` kwargs to `run_ldp_ingest()` and `extract_quads_chunked()`, builds a cached plan-context prefix, and passes it through to `extract_wiki_pages_from_chunk()`.

- [ ] **Step 1: Update `pipeline/ldp.py`**

Update `run_ldp_ingest()` and `extract_quads_chunked()` signatures to accept the new kwargs:

```python
def extract_quads_chunked(
    source_content: str,
    section_map: dict,
    source_uuid: str,
    document_title: str,
    source_rel_path: str = "",
    source_type: str = "cap",
    wiki_root: str = "wiki",
    run_date: str | None = None,
    wiki_only: bool = False,
    quads_only: bool = False,
    entity_context: str = "",
    integration_plan: dict | None = None,
    retrieved_bodies: dict[str, str] | None = None,
) -> tuple[list[dict], int]:
```

Build a plan-context string before the chunk loop:

```python
    plan_context = ""
    if integration_plan or retrieved_bodies:
        lines = []
        if integration_plan:
            import json as _json
            lines.append("\n[INTEGRATION PLAN — Comprehend pass output]")
            lines.append(_json.dumps(integration_plan, indent=2))
            lines.append("[END INTEGRATION PLAN]\n")
        if retrieved_bodies:
            lines.append("\n[RETRIEVED ENTITY PAGES — integrate new findings into these]")
            for slug, body in retrieved_bodies.items():
                lines.append(f"\n--- {slug} ---\n{body}")
            lines.append("\n[END RETRIEVED ENTITY PAGES]\n")
        plan_context = "\n".join(lines)
```

Pass `plan_context` to `extract_wiki_pages_from_chunk` by combining it with the existing `entity_context`:

```python
        combined_context = (
            (entity_context or "") + (plan_context or "") + context_header
        )
        pages_written = extract_wiki_pages_from_chunk(
            chunk_text=chunk_text,
            source_uuid=source_uuid,
            source_rel_path=source_rel_path,
            context_header=combined_context,
            source_type=source_type,
            wiki_root=wiki_root,
            run_date=run_date,
            aliases=aliases,
        )
```

Update `run_ldp_ingest()` signature to accept the same kwargs and pass them through to `extract_quads_chunked()`:

```python
def run_ldp_ingest(
    source_content: str,
    uuid: str,
    title: str,
    quads_path: str,
    source_rel_path: str = "",
    wiki_root: str = "wiki",
    source_type: str = "cap",
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
    wiki_only: bool = False,
    quads_only: bool = False,
    entity_context: str = "",
    integration_plan: dict | None = None,
    retrieved_bodies: dict[str, str] | None = None,
):
```

And the inner call:

```python
    quads, pages_written = extract_quads_chunked(
        source_content=source_content,
        section_map=section_map,
        source_uuid=uuid,
        document_title=title,
        source_rel_path=source_rel_path,
        source_type=source_type,
        wiki_root=wiki_root,
        run_date=run_date,
        wiki_only=wiki_only,
        quads_only=quads_only,
        entity_context=entity_context,
        integration_plan=integration_plan,
        retrieved_bodies=retrieved_bodies,
    )
```

- [ ] **Step 2: Uncomment the kwargs in `run_ingest.py`**

In `pipeline/run_ingest.py`, restore the kwargs in the `run_ldp_ingest()` call:

```python
        run_ldp_ingest(
            source_content=source_content,
            ...
            entity_context=entity_context,
            integration_plan=integration_plan,
            retrieved_bodies=retrieved_bodies,
        )
```

Same for the non-LDP branch that calls `extract_wiki_pages_from_chunk` directly — prepend `plan_context` if the plan exists:

```python
        if not quads_only:
            from pipeline.wiki_writer import extract_wiki_pages_from_chunk
            body = re.sub(r"^---\n.*?\n---\n", "", source_content, flags=re.DOTALL).strip()
            _plan_ctx = ""
            if integration_plan or retrieved_bodies:
                _lines = []
                if integration_plan:
                    _lines.append("[INTEGRATION PLAN]\n" + json.dumps(integration_plan, indent=2) + "\n[END INTEGRATION PLAN]")
                if retrieved_bodies:
                    _lines.append("[RETRIEVED ENTITY PAGES]")
                    for _s, _b in retrieved_bodies.items():
                        _lines.append(f"--- {_s} ---\n{_b}")
                    _lines.append("[END RETRIEVED ENTITY PAGES]")
                _plan_ctx = "\n".join(_lines) + "\n"
            extract_wiki_pages_from_chunk(
                chunk_text=body,
                source_uuid=uuid,
                source_rel_path=source_rel_path,
                context_header=_plan_ctx + entity_context,
                source_type=source_type,
                wiki_root=wiki_root,
                run_date=run_date,
            )
```

- [ ] **Step 3: Update `tests/test_ldp.py`**

Find `test_extract_quads_chunked_calls_llm_per_chunk` and add a new test below it:

```python
@patch("pipeline.wiki_writer.extract_wiki_pages_from_chunk")
@patch("pipeline.ldp.chat")
def test_extract_quads_chunked_passes_plan_context_to_writer(mock_chat, mock_wiki_writer_extract, tmp_path):
    """When integration_plan + retrieved_bodies are supplied, they appear in the chunk's context_header."""
    section_map = {
        "uuid": "test", "sections": [
            {"depth": 1, "title": "Strategy 1", "line_start": 1, "line_end": 5, "section_num": "1"}
        ]
    }
    source = "# Strategy 1\nSome chunk content.\n"
    mock_chat.return_value = "[]"
    mock_wiki_writer_extract.return_value = []

    plan = {"strategies-touched": ["strategies/strategy-1-x"], "extends": [{"slug": "initiatives/x", "new-data": "y"}], "new-entities": [], "retrieve-for-context": ["initiatives/x"], "theme-connections": []}
    bodies = {"initiatives/x": "Existing body text for X"}

    from pipeline.ldp import extract_quads_chunked
    extract_quads_chunked(
        source_content=source,
        section_map=section_map,
        source_uuid="test", document_title="T",
        wiki_root=str(tmp_path),
        run_date="2026-06-29",
        integration_plan=plan,
        retrieved_bodies=bodies,
    )
    # The wiki_writer call should have received a context_header containing the plan + body
    assert mock_wiki_writer_extract.called
    context_header = mock_wiki_writer_extract.call_args.kwargs["context_header"]
    assert "INTEGRATION PLAN" in context_header
    assert "Existing body text for X" in context_header
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -q`
Expected: PASS (existing + all new tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/ldp.py pipeline/run_ingest.py tests/test_ldp.py
git commit -m "feat(ldp): thread integration_plan + retrieved_bodies as cached prefix into chunk extraction"
```

---

### Task 10: Update CLAUDE.md + CHANGELOG.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update CLAUDE.md**

Find the "Three-Pass Ingest Pipeline" section and add a paragraph after the existing pass descriptions:

```markdown
**Pass 1A (Comprehend):** Before Pass 1 runs, the new Comprehend pass reads `wiki/digest.md` plus the source and produces a structured integration plan saved to `wiki/integration-plans/<source-uuid>.json`. The plan flows downstream into both the holistic Writer (Pass 1B) and the LDP chunk extraction (Pass 2), informing which entities to extend vs. create and which existing page bodies to pre-load as integration context. Per-ingest telemetry lands in `wiki/meta/ingest-stats.jsonl`. See `docs/architecture/comprehend-plan-write.md`.
```

Find the "Pipeline Modules" table and add a row:

```markdown
| `comprehend.py` | Pass 1A Comprehend: read digest + source → integration plan |
```

- [ ] **Step 2: Update CHANGELOG.md**

Prepend (under today's date) above the most recent entry:

```markdown
## 2026-06-29 — Comprehend → Plan → Write architecture

**What changed:**
- **`pipeline/comprehend.py`** — new module implementing Pass 1A: reads `wiki/digest.md` plus the source, calls an LLM to produce a structured integration plan, validates the plan's slugs via the existing `synthesis_validation` machinery, persists to `wiki/integration-plans/<source-uuid>.json`, and pre-loads entity page bodies for `retrieve-for-context` (capped at 30k tokens, prioritized by `extends` + mention frequency).
- **`pipeline/holistic_synthesizer.py`** — `synthesize_source()` now accepts `integration_plan` and `digest_content` kwargs. Replaces the legacy `integration_block` (raw strategy bodies) with a plan + digest injection block. Legacy fallback preserved for callers that don't pass the new kwargs.
- **`pipeline/ldp.py`** — `extract_quads_chunked()` and `run_ldp_ingest()` accept `integration_plan` + `retrieved_bodies` kwargs and prepend them as a cached prefix to each chunk's context. Plan is a prior, not a constraint — LDP still creates pages for entities outside the plan as before.
- **`pipeline/run_ingest.py`** — orchestrates Comprehend before Pass 1. Hard-fails the ingest when `digest.md` exists but the Comprehend LLM call errors (don't waste downstream tokens). Graceful fallback (no LLM call, empty plan) when no digest exists (first-ingest path).
- **`wiki/integration-plans/`** — new directory for integration plan artifacts, committed for audit trail. Each `<source-uuid>.json` records how that ingest mapped the source onto existing wiki state.
- **`wiki/meta/ingest-stats.jsonl`** — per-ingest telemetry (Comprehend duration, plan size, extends/new-entities/retrieve counts).
- **13 new tests** in `tests/test_comprehend.py` + integration tests added to `tests/test_holistic_synthesizer.py`, `tests/test_ldp.py`, `tests/test_run_ingest.py`.

**Why:** Year 1 and Year 2 ingests both produced visible entity fragmentation because the LLM responsible for the integration decision never saw what the wiki already knew. We compensated downstream with alias resolution and lint cycles, but the *fundamental* problem was upstream: the holistic synthesizer conflated reading with writing, treating each source as if it were the only one. The Comprehend split makes the integration decision an explicit, structured artifact (the plan), and the plan flows downstream to inform both the Writer pass and the LDP chunk extraction. Per-ingest cost stops growing with wiki size — the digest is constant-size regardless of how many entities exist.

**Spec:** `docs/architecture/comprehend-plan-write.md`. **Plan:** `docs/superpowers/plans/2026-06-29-comprehend-plan-write.md`. **Branch:** `feat/digest-injection` (draft PR opened for review).

---
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: document Comprehend → Plan → Write architecture in CLAUDE.md + CHANGELOG"
```

---

### Task 11: Push branch + open draft PR

- [ ] **Step 1: Verify all tests pass**

Run: `python -m pytest tests/ -q`
Expected: PASS — 187 prior + 13 new + integration tests ≈ 200+ passed, 1 skipped.

- [ ] **Step 2: Push branch**

```bash
git push -u origin feat/digest-injection
```

- [ ] **Step 3: Open a DRAFT PR**

```bash
gh pr create --draft --title "feat: Comprehend → Plan → Write architecture" --body "$(cat <<'EOF'
## Summary

Wires `wiki/digest.md` into the ingest pipeline by splitting the holistic synthesizer into a Comprehend pass and a Plan-guided Write pass. LDP chunk extraction now consumes the plan + pre-loaded entity page bodies as a cached prefix.

## Architecture

- **Pass 1A (new): Comprehend** — `pipeline/comprehend.py` reads `wiki/digest.md` + source, produces a structured integration plan with 5 fields (`strategies-touched`, `extends`, `new-entities`, `retrieve-for-context`, `theme-connections`).
- **Pass 1B: Plan-guided Write** — existing Writer→Evaluator→Editor loop, now receives plan + digest in its input context instead of raw strategy bodies.
- **Pass 2: Plan-guided LDP** — chunk extraction prompts include the plan + retrieved entity bodies as a cached prefix (shared across all chunks of one ingest).

## Key design decisions (per spec)

- Comprehend hard-fails when digest exists but LLM errors (don't waste downstream tokens)
- Graceful fallback only when no digest exists at all (first-ingest path)
- `retrieve-for-context` capped at 30k tokens, prioritized by `extends` then mention frequency
- Plan slugs validated through existing `synthesis_validation` machinery
- Per-ingest telemetry to `wiki/meta/ingest-stats.jsonl`
- LDP creates pages for entities outside the plan as today (plan is prior, not constraint)

## Test plan

- [x] All existing tests still pass (187 prior)
- [x] 13 new unit tests for `pipeline/comprehend.py` (plan I/O, LLM call, validation, token-budget cap, telemetry)
- [x] Integration tests added for `holistic_synthesizer`, `ldp`, `run_ingest`
- [ ] Smoke test against Year 3 ingest — DEFERRED (Caleb's call after PR review)
- [ ] Manual review of one integration plan artifact

## Spec & plan

- **Spec:** [docs/architecture/comprehend-plan-write.md](docs/architecture/comprehend-plan-write.md)
- **Implementation plan:** [docs/superpowers/plans/2026-06-29-comprehend-plan-write.md](docs/superpowers/plans/2026-06-29-comprehend-plan-write.md)

## Not included (out of scope per spec)

- `synthesize_wiki --strategies-touched-from <plan>` — follow-on PR
- Embedding-based `retrieve-for-context` supplementation — deferred until wiki >1000 entities
- Plan-driven `review-queue.md` annotations
- Changes to Writer/Evaluator/Editor prompt structure (only input context changes)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Report PR URL back to the user**

Capture the PR URL printed by `gh pr create` and include it in the final summary.

---

## Self-Review Checklist

After all tasks complete:

- [ ] All tests passing (`python -m pytest tests/ -q`)
- [ ] No ghost slugs in any generated integration plan (run the test wiki and verify with `cat wiki/integration-plans/*.json | jq '.extends, .["retrieve-for-context"]'`)
- [ ] `wiki/integration-plans/` exists and is git-tracked
- [ ] `wiki/meta/ingest-stats.jsonl` exists
- [ ] CLAUDE.md describes the Comprehend pass and the integration-plans directory
- [ ] CHANGELOG.md has the new entry
- [ ] Draft PR opened and URL captured
- [ ] Branch `feat/digest-injection` pushed to origin
