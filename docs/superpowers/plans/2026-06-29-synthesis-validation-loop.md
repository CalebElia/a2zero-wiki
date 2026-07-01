# Synthesis Validation Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Write → Validate → Revise loop to `synthesize_wiki` so that ghost entity references can never reach `wiki/strategies/*.md` synthesis frontmatter or `wiki/digest.md`, while keeping the Writer prompt unconstrained for analytical quality.

**Architecture:** A new deterministic Validator module checks every slug emitted by the synthesis and narrative LLM calls against the filesystem. When ghosts are found, a scoped Reviser LLM call corrects them (substitute from inventory, drop from structured fields, or demote to plain text in prose). Validators run at two points: before the strategy synthesis frontmatter is persisted, and before `digest.md` is written.

**Tech Stack:** Python 3.13, existing `pipeline/llm.py` `chat()` wrapper, pytest, PyYAML.

**Spec:** [docs/architecture/synthesis-validation-loop.md](../../../docs/architecture/synthesis-validation-loop.md)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pipeline/synthesis_validation.py` | Create | Validator + Reviser functions, ghost log helper |
| `tests/test_synthesis_validation.py` | Create | Unit tests for validators + mocked Reviser tests |
| `pipeline/synthesize_wiki.py` | Modify | Wire validation into orchestration; revert inventory-binding prompt; remove inline `_resolve_synthesis_slugs`, `_SUPPRESS_SLUGS` |
| `tests/test_synthesize_wiki.py` | Modify | Update orchestration test to mock the new validate/revise sequence |
| `wiki/meta/synthesis-ghosts.log` | Create empty | Append-only log of dropped ghost slugs |
| `CHANGELOG.md` | Modify | Append entry for this session |
| `CLAUDE.md` | Modify | Document the new validation step in Phase C synthesis description |

---

### Task 1: Module skeleton + dataclasses

**Files:**
- Create: `pipeline/synthesis_validation.py`
- Test: `tests/test_synthesis_validation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synthesis_validation.py
from pipeline.synthesis_validation import BrokenRef, ValidationReport


def test_broken_ref_dataclass():
    b = BrokenRef(slug="actors/foo", location="core-actors", display="Foo", context="")
    assert b.slug == "actors/foo"
    assert b.location == "core-actors"


def test_validation_report_is_clean_when_empty():
    report = ValidationReport(broken=[])
    assert report.is_clean is True


def test_validation_report_is_dirty_when_broken_present():
    report = ValidationReport(broken=[
        BrokenRef(slug="actors/foo", location="core-actors", display="Foo", context="")
    ])
    assert report.is_clean is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthesis_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.synthesis_validation'`

- [ ] **Step 3: Write minimal implementation**

```python
# pipeline/synthesis_validation.py
"""Validator + Reviser for synthesize_wiki outputs.

Catches ghost entity references (wikilinks to non-existent pages) before they
get persisted to strategy synthesis frontmatter or digest.md.

See docs/architecture/synthesis-validation-loop.md for design rationale.
"""
from dataclasses import dataclass, field


@dataclass
class BrokenRef:
    """A single broken entity reference found by the Validator."""
    slug: str       # e.g. "actors/foo" — the unresolvable slug
    location: str   # "core-actors" | "core-initiatives" | "cross-strategy-links" | "narrative"
    display: str    # display name as it appeared in source
    context: str    # surrounding 80 chars (narrative only; empty for structured)


@dataclass
class ValidationReport:
    """Report from a single validation pass."""
    broken: list[BrokenRef] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return len(self.broken) == 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synthesis_validation.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesis_validation.py tests/test_synthesis_validation.py
git commit -m "feat(synthesis): add BrokenRef + ValidationReport dataclasses"
```

---

### Task 2: `validate_synthesis()` — structural validator with alias/suppress/type-sort

**Files:**
- Modify: `pipeline/synthesis_validation.py`
- Test: `tests/test_synthesis_validation.py`

This function moves the alias resolution, suppress list, and type-sort logic out of `synthesize_wiki.py` and into the Validator. After applying those mechanical corrections, it checks every remaining slug against the filesystem.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesis_validation.py`:

```python
import json
from pathlib import Path
from pipeline.synthesis_validation import validate_synthesis


def _make_wiki(tmp_path, actors=None, initiatives=None, locations=None):
    """Helper: create a minimal wiki with stub files for given slugs."""
    root = tmp_path / "wiki"
    for type_dir, slugs in [
        ("actors", actors or []),
        ("initiatives", initiatives or []),
        ("locations", locations or []),
    ]:
        d = root / type_dir
        d.mkdir(parents=True, exist_ok=True)
        for slug in slugs:
            (d / f"{slug}.md").write_text("---\ntype: actor\n---\n", encoding="utf-8")
    return root


def test_validate_synthesis_passes_when_all_slugs_exist(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"], initiatives=["bar"])
    synthesis = {
        "core-initiatives": ["initiatives/bar"],
        "core-actors": ["actors/foo"],
        "cross-strategy-links": [],
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases={})
    assert report.is_clean
    assert corrected["core-actors"] == ["actors/foo"]


def test_validate_synthesis_flags_missing_slug(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "actors/ghost"],
        "cross-strategy-links": [],
    }
    _, report = validate_synthesis(synthesis, str(root), aliases={})
    assert not report.is_clean
    assert any(b.slug == "actors/ghost" for b in report.broken)
    assert all(b.location == "core-actors" for b in report.broken)


def test_validate_synthesis_resolves_aliases_before_checking(tmp_path):
    root = _make_wiki(tmp_path, actors=["office-of-sustainability-and-innovations"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/a2zero-office"],
        "cross-strategy-links": [],
    }
    aliases = {
        "a2zero-office": {
            "canonical": "actors/office-of-sustainability-and-innovations",
            "type": "actor",
            "aliases": [],
            "relationship": "name-variant",
        }
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases=aliases)
    assert report.is_clean
    assert corrected["core-actors"] == ["actors/office-of-sustainability-and-innovations"]


def test_validate_synthesis_moves_initiatives_out_of_core_actors(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"], initiatives=["bar"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "initiatives/bar"],
        "cross-strategy-links": [],
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases={})
    assert report.is_clean
    assert corrected["core-actors"] == ["actors/foo"]
    assert corrected["core-initiatives"] == ["initiatives/bar"]


def test_validate_synthesis_drops_locations_from_core_actors(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"], locations=["place"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "locations/place"],
        "cross-strategy-links": [],
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases={})
    assert report.is_clean
    assert corrected["core-actors"] == ["actors/foo"]


def test_validate_synthesis_suppress_list_drops_known_bad(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "actors/systems-planning-unit"],
        "cross-strategy-links": [],
    }
    corrected, report = validate_synthesis(synthesis, str(root), aliases={})
    assert report.is_clean
    assert "actors/systems-planning-unit" not in corrected["core-actors"]


def test_validate_synthesis_deduplicates(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"])
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "actors/foo"],
        "cross-strategy-links": [],
    }
    corrected, _ = validate_synthesis(synthesis, str(root), aliases={})
    assert corrected["core-actors"] == ["actors/foo"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_synthesis_validation.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_synthesis'`

- [ ] **Step 3: Implement**

Append to `pipeline/synthesis_validation.py`:

```python
from pathlib import Path


SUPPRESS_SLUGS: frozenset[str] = frozenset({
    "actors/systems-planning-unit",
    "actors/city-of-ann-arbor-systems-planning",
    "actors/ann-arbor-recycling-and-solid-waste",
    "actors/neighborhood-organizations",
})


def _exists(slug: str, wiki_root: str) -> bool:
    return (Path(wiki_root) / f"{slug}.md").exists()


def _resolve_alias(slug: str, aliases: dict) -> str:
    """Substitute alias -> canonical, if known."""
    key = slug.split("/")[-1]
    return aliases.get(key, {}).get("canonical") or slug


def validate_synthesis(
    synthesis: dict,
    wiki_root: str,
    aliases: dict,
) -> tuple[dict, ValidationReport]:
    """Apply alias resolution + type-sort + suppress list, then check
    every remaining slug against the filesystem.

    Returns (partially-corrected synthesis, report of what's still broken).
    """
    corrected = dict(synthesis)

    def _clean(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for slug in items or []:
            resolved = _resolve_alias(slug, aliases)
            if resolved in SUPPRESS_SLUGS or resolved in seen:
                continue
            seen.add(resolved)
            out.append(resolved)
        return out

    for field in ("core-initiatives", "core-actors", "cross-strategy-links"):
        corrected[field] = _clean(corrected.get(field) or [])

    # Type-sort: initiatives misplaced in core-actors → move to core-initiatives;
    # locations in core-actors → drop.
    misplaced_inits = [s for s in corrected["core-actors"] if s.startswith("initiatives/")]
    bad_actors = {s for s in corrected["core-actors"]
                  if s.startswith("initiatives/") or s.startswith("locations/")}
    if bad_actors:
        corrected["core-actors"] = [s for s in corrected["core-actors"] if s not in bad_actors]
        existing = set(corrected["core-initiatives"])
        corrected["core-initiatives"] = corrected["core-initiatives"] + [
            s for s in misplaced_inits if s not in existing
        ]

    # Filesystem check on what's left
    broken: list[BrokenRef] = []
    for field in ("core-initiatives", "core-actors", "cross-strategy-links"):
        for slug in corrected[field]:
            if not _exists(slug, wiki_root):
                broken.append(BrokenRef(
                    slug=slug, location=field, display=slug.split("/")[-1], context=""
                ))

    return corrected, ValidationReport(broken=broken)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesis_validation.py -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesis_validation.py tests/test_synthesis_validation.py
git commit -m "feat(synthesis): add validate_synthesis() with alias/suppress/type-sort"
```

---

### Task 3: `validate_narrative()` — wikilink regex validator for prose

**Files:**
- Modify: `pipeline/synthesis_validation.py`
- Test: `tests/test_synthesis_validation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesis_validation.py`:

```python
from pipeline.synthesis_validation import validate_narrative


def test_validate_narrative_passes_clean_prose(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"], initiatives=["bar"])
    narrative = "The [[actors/foo|Foo Org]] led [[initiatives/bar|Bar Program]] this year."
    report = validate_narrative(narrative, str(root), aliases={})
    assert report.is_clean


def test_validate_narrative_flags_broken_wikilinks(tmp_path):
    root = _make_wiki(tmp_path, actors=["foo"])
    narrative = "The [[actors/foo|Foo Org]] partnered with [[actors/ghost|Ghost Inc]]."
    report = validate_narrative(narrative, str(root), aliases={})
    assert not report.is_clean
    assert len(report.broken) == 1
    assert report.broken[0].slug == "actors/ghost"
    assert report.broken[0].display == "Ghost Inc"
    assert report.broken[0].location == "narrative"
    assert "Ghost Inc" in report.broken[0].context


def test_validate_narrative_resolves_aliases(tmp_path):
    root = _make_wiki(tmp_path, actors=["office-of-sustainability-and-innovations"])
    narrative = "[[actors/a2zero-office|A2Zero Office]] coordinated the program."
    aliases = {
        "a2zero-office": {
            "canonical": "actors/office-of-sustainability-and-innovations",
            "type": "actor", "aliases": [], "relationship": "name-variant",
        }
    }
    report = validate_narrative(narrative, str(root), aliases=aliases)
    assert report.is_clean


def test_validate_narrative_handles_bare_wikilinks(tmp_path):
    """[[slug]] without pipe-display should still validate."""
    root = _make_wiki(tmp_path, actors=["foo"])
    narrative = "Background on [[actors/foo]] and [[actors/missing]]."
    report = validate_narrative(narrative, str(root), aliases={})
    assert not report.is_clean
    assert report.broken[0].slug == "actors/missing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_synthesis_validation.py::test_validate_narrative_passes_clean_prose -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `pipeline/synthesis_validation.py`:

```python
import re


# Matches [[path/slug|Display]] or [[path/slug]] — captures slug and optional display
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def validate_narrative(
    narrative: str,
    wiki_root: str,
    aliases: dict,
) -> ValidationReport:
    """Parse wikilinks in narrative prose; report broken ones.

    Does not modify the narrative — narratives are revised in-place by the Reviser.
    """
    broken: list[BrokenRef] = []
    seen: set[str] = set()

    for match in _WIKILINK_RE.finditer(narrative):
        slug = match.group(1).strip()
        display = (match.group(2) or slug.split("/")[-1]).strip()

        # Skip non-entity wikilinks (e.g. sources/, strategies/)
        type_prefix = slug.split("/")[0]
        if type_prefix not in {"actors", "initiatives", "locations", "technology",
                               "funding-events", "meetings", "political-events"}:
            continue

        resolved = _resolve_alias(slug, aliases)
        if resolved in seen or resolved in SUPPRESS_SLUGS:
            continue
        seen.add(resolved)

        if not _exists(resolved, wiki_root):
            # Pull ±40 chars around the wikilink as context
            start = max(0, match.start() - 40)
            end = min(len(narrative), match.end() + 40)
            broken.append(BrokenRef(
                slug=resolved, location="narrative", display=display,
                context=narrative[start:end],
            ))

    return ValidationReport(broken=broken)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesis_validation.py -v`
Expected: PASS (all 14 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesis_validation.py tests/test_synthesis_validation.py
git commit -m "feat(synthesis): add validate_narrative() with wikilink regex parsing"
```

---

### Task 4: Ghost log helper

**Files:**
- Modify: `pipeline/synthesis_validation.py`
- Test: `tests/test_synthesis_validation.py`
- Create: `wiki/meta/synthesis-ghosts.log` (empty placeholder)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesis_validation.py`:

```python
from pipeline.synthesis_validation import log_dropped_ghosts


def test_log_dropped_ghosts_appends_entries(tmp_path):
    log_path = tmp_path / "synthesis-ghosts.log"
    log_dropped_ghosts(
        log_path=str(log_path),
        run_date="2026-06-29",
        context_label="strategy-5-materials-waste",
        ghosts=[
            BrokenRef(slug="actors/foo", location="core-actors", display="Foo", context=""),
            BrokenRef(slug="actors/bar", location="narrative", display="Bar", context="..."),
        ],
    )
    content = log_path.read_text(encoding="utf-8")
    assert "2026-06-29" in content
    assert "strategy-5-materials-waste" in content
    assert "actors/foo" in content
    assert "actors/bar" in content


def test_log_dropped_ghosts_is_noop_on_empty_list(tmp_path):
    log_path = tmp_path / "synthesis-ghosts.log"
    log_dropped_ghosts(
        log_path=str(log_path), run_date="2026-06-29",
        context_label="strategy-1", ghosts=[],
    )
    assert not log_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_synthesis_validation.py::test_log_dropped_ghosts_appends_entries -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `pipeline/synthesis_validation.py`:

```python
def log_dropped_ghosts(
    log_path: str,
    run_date: str,
    context_label: str,
    ghosts: list[BrokenRef],
) -> None:
    """Append dropped-ghost entries to the synthesis-ghosts log for human review.

    Recurring entries in this log signal entities worth either creating as pages
    or adding to SUPPRESS_SLUGS permanently.
    """
    if not ghosts:
        return
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"\n## [{run_date} | {context_label}]"]
    for g in ghosts:
        lines.append(f"- {g.slug} (location={g.location}, display={g.display!r})")
        if g.context:
            lines.append(f"  context: …{g.context.strip()}…")
    with p.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
```

- [ ] **Step 4: Create the empty log file in the wiki**

```bash
mkdir -p wiki/meta
touch wiki/meta/synthesis-ghosts.log
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesis_validation.py -v`
Expected: PASS (all 16 tests)

- [ ] **Step 6: Commit**

```bash
git add pipeline/synthesis_validation.py tests/test_synthesis_validation.py wiki/meta/synthesis-ghosts.log
git commit -m "feat(synthesis): add log_dropped_ghosts() + empty log placeholder"
```

---

### Task 5: `revise_synthesis()` — LLM call for structured corrections

**Files:**
- Modify: `pipeline/synthesis_validation.py`
- Test: `tests/test_synthesis_validation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesis_validation.py`:

```python
import json
from unittest.mock import patch
from pipeline.synthesis_validation import revise_synthesis


def test_revise_synthesis_calls_llm_and_returns_corrected_dict():
    synthesis = {
        "core-initiatives": [],
        "core-actors": ["actors/foo", "actors/ghost"],
        "cross-strategy-links": [],
    }
    report = ValidationReport(broken=[
        BrokenRef(slug="actors/ghost", location="core-actors", display="Ghost", context="")
    ])
    inventory = [
        {"slug": "actors/foo", "title": "Foo Org", "type": "actor", "one-liner": ""},
    ]
    corrected_json = json.dumps({
        "core-initiatives": [],
        "core-actors": ["actors/foo"],
        "cross-strategy-links": [],
    })
    with patch("pipeline.synthesis_validation.chat") as mock_chat:
        mock_chat.return_value = corrected_json
        result = revise_synthesis(synthesis, report, inventory)
    assert "actors/ghost" not in result["core-actors"]
    assert result["core-actors"] == ["actors/foo"]


def test_revise_synthesis_returns_original_on_llm_failure():
    synthesis = {"core-initiatives": [], "core-actors": ["actors/foo"], "cross-strategy-links": []}
    report = ValidationReport(broken=[
        BrokenRef(slug="actors/foo", location="core-actors", display="Foo", context="")
    ])
    with patch("pipeline.synthesis_validation.chat") as mock_chat:
        mock_chat.side_effect = Exception("api error")
        result = revise_synthesis(synthesis, report, inventory=[])
    # Falls back to original synthesis (with the ghost still in it) rather than crashing
    assert result == synthesis
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_synthesis_validation.py::test_revise_synthesis_calls_llm_and_returns_corrected_dict -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `pipeline/synthesis_validation.py`:

```python
import json
from pipeline.llm import chat


_REVISE_SYNTHESIS_SYSTEM = """You are correcting wikilinks in a structured synthesis \
JSON document.

You will receive:
1. The original synthesis (JSON)
2. A list of broken references — slugs that don't exist as wiki pages
3. The inventory of entities that DO exist for this strategy

For each broken reference, choose ONE action:
- SUBSTITUTE with a slug from the inventory, ONLY if there is a clear match \
(same entity, different name)
- DROP the slug entirely from its list

Do not invent new slugs. Do not add new content. Do not modify the year-over-year-arc \
or open-questions fields. Only touch the slug lists (core-initiatives, core-actors, \
cross-strategy-links).

Return ONLY the corrected JSON object — no preamble, no code fences.
"""


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:-1]) if len(lines) > 2 else t
    return t.strip()


def revise_synthesis(
    synthesis: dict,
    report: ValidationReport,
    inventory: list[dict],
) -> dict:
    """LLM call: correct broken slugs in a structured synthesis dict.

    Falls back to the original synthesis if the LLM call fails — a synthesis with
    ghosts is more useful than no synthesis.
    """
    if report.is_clean:
        return synthesis

    broken_lines = "\n".join(
        f"- {b.slug} (in {b.location}, displayed as '{b.display}')"
        for b in report.broken
    )
    inventory_lines = "\n".join(
        f"- {e['slug']} — {e['title']}: {e.get('one-liner','')}"
        for e in inventory
    )
    user_msg = (
        f"Original synthesis:\n```json\n{json.dumps(synthesis, indent=2)}\n```\n\n"
        f"Broken references:\n{broken_lines}\n\n"
        f"Available entity inventory:\n{inventory_lines}\n\n"
        "Return the corrected JSON."
    )

    try:
        raw = chat(
            system=_REVISE_SYNTHESIS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
            model_hint="revision",
            temperature=0.0,
        )
        return json.loads(_strip_code_fence(raw))
    except Exception as e:
        print(f"[synthesis_validation] revise_synthesis failed; returning original: {e}")
        return synthesis
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesis_validation.py -v`
Expected: PASS (all 18 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesis_validation.py tests/test_synthesis_validation.py
git commit -m "feat(synthesis): add revise_synthesis() LLM call for structured corrections"
```

---

### Task 6: `revise_narrative()` — LLM call for prose corrections

**Files:**
- Modify: `pipeline/synthesis_validation.py`
- Test: `tests/test_synthesis_validation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthesis_validation.py`:

```python
from pipeline.synthesis_validation import revise_narrative


def test_revise_narrative_calls_llm_and_returns_corrected_prose():
    narrative = "The [[actors/foo|Foo]] partnered with [[actors/ghost|Ghost Inc]]."
    report = ValidationReport(broken=[
        BrokenRef(slug="actors/ghost", location="narrative", display="Ghost Inc",
                  context="partnered with Ghost Inc"),
    ])
    inventory = []
    corrected = "The [[actors/foo|Foo]] partnered with Ghost Inc."
    with patch("pipeline.synthesis_validation.chat") as mock_chat:
        mock_chat.return_value = corrected
        result = revise_narrative(narrative, report, inventory)
    assert "[[actors/ghost" not in result
    assert "Ghost Inc" in result  # demoted to plain text


def test_revise_narrative_returns_original_on_llm_failure():
    narrative = "Text with [[actors/foo|Foo]]."
    report = ValidationReport(broken=[
        BrokenRef(slug="actors/foo", location="narrative", display="Foo", context="")
    ])
    with patch("pipeline.synthesis_validation.chat") as mock_chat:
        mock_chat.side_effect = Exception("api error")
        result = revise_narrative(narrative, report, inventory=[])
    assert result == narrative
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_synthesis_validation.py::test_revise_narrative_calls_llm_and_returns_corrected_prose -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `pipeline/synthesis_validation.py`:

```python
_REVISE_NARRATIVE_SYSTEM = """You are correcting wikilinks in narrative prose for an \
Obsidian wiki.

You will receive:
1. The original narrative (markdown prose with [[slug|Display]] wikilinks)
2. A list of broken references — wikilinks pointing to pages that don't exist
3. The available entity inventory

For each broken wikilink, choose ONE action:
- SUBSTITUTE with a real slug from the inventory, ONLY if there is a clear match
- DEMOTE to plain text: unwrap [[slug|Display Name]] → Display Name (preserves \
readability, removes the false link)

Do NOT invent new slugs. Do NOT modify the analytical content of the prose — only \
fix the broken wikilinks. Keep paragraph structure and word choice intact otherwise.

Return ONLY the corrected markdown — no preamble, no code fences.
"""


def revise_narrative(
    narrative: str,
    report: ValidationReport,
    inventory: list[dict],
) -> str:
    """LLM call: correct broken wikilinks in narrative prose.

    Falls back to the original narrative if the LLM call fails.
    """
    if report.is_clean:
        return narrative

    broken_lines = "\n".join(
        f"- [[{b.slug}|{b.display}]] (no page exists; context: …{b.context.strip()}…)"
        for b in report.broken
    )
    inventory_lines = "\n".join(
        f"- {e['slug']} — {e['title']}" for e in inventory
    )
    user_msg = (
        f"Original narrative:\n\n{narrative}\n\n---\n\n"
        f"Broken wikilinks:\n{broken_lines}\n\n"
        f"Available entity inventory:\n{inventory_lines or '(none)'}\n\n"
        "Return the corrected narrative."
    )

    try:
        return chat(
            system=_REVISE_NARRATIVE_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=4096,
            model_hint="revision",
            temperature=0.0,
        ).strip()
    except Exception as e:
        print(f"[synthesis_validation] revise_narrative failed; returning original: {e}")
        return narrative
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesis_validation.py -v`
Expected: PASS (all 20 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesis_validation.py tests/test_synthesis_validation.py
git commit -m "feat(synthesis): add revise_narrative() LLM call for prose corrections"
```

---

### Task 7: Wire validation into `synthesize_wiki()` orchestration; revert constraining prompt

**Files:**
- Modify: `pipeline/synthesize_wiki.py`
- Modify: `tests/test_synthesize_wiki.py`

This task:
1. Removes `_resolve_synthesis_slugs()`, `_SUPPRESS_SLUGS`, and the inline alias-resolution call from `synthesize_wiki.py` (now lives in the Validator).
2. Reverts the "ONLY use slugs that appear verbatim in the entity inventory" language added to `_STRATEGY_SYNTHESIS_SYSTEM` last iteration. The Writer is now free again.
3. Inserts `validate_synthesis` → `revise_synthesis` calls after `build_strategy_synthesis()`.
4. Inserts `validate_narrative` → `revise_narrative` calls after `build_digest_narrative()`.
5. Logs dropped ghosts to `wiki/meta/synthesis-ghosts.log` after each revision.

- [ ] **Step 1: Update the orchestration test in `tests/test_synthesize_wiki.py`**

Replace `test_synthesize_wiki_orchestrates_end_to_end`:

```python
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

    with patch("pipeline.synthesize_wiki.chat") as mock_chat:
        # Writer calls only — validators are deterministic and the fixture is clean
        # so no Reviser calls fire. Call order: 1 strategy synth + 1 narrative.
        mock_chat.side_effect = [strategy_llm_output, narrative_output]

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

Also update the existing fixture to ensure `wiki/initiatives/solarize-ann-arbor.md` and `wiki/actors/glrea.md` exist in the fixture so validation passes. Check `tests/fixtures/synthesize_wiki/wiki/` — if those pages aren't there, add them:

```bash
ls tests/fixtures/synthesize_wiki/wiki/initiatives/ tests/fixtures/synthesize_wiki/wiki/actors/
```

If missing, create stub files:

```bash
mkdir -p tests/fixtures/synthesize_wiki/wiki/initiatives tests/fixtures/synthesize_wiki/wiki/actors
echo "---\ntype: initiative\n---\n" > tests/fixtures/synthesize_wiki/wiki/initiatives/solarize-ann-arbor.md
echo "---\ntype: actor\n---\n" > tests/fixtures/synthesize_wiki/wiki/actors/glrea.md
```

- [ ] **Step 2: Run the test to verify it fails as expected**

Run: `python -m pytest tests/test_synthesize_wiki.py::test_synthesize_wiki_orchestrates_end_to_end -v`
Expected: Existing test passes since orchestration hasn't changed yet — we'll change it next and verify it still passes.

- [ ] **Step 3: Update `pipeline/synthesize_wiki.py`**

Three edits in this file:

**Edit A — remove `_resolve_synthesis_slugs()` and `_SUPPRESS_SLUGS`:**

Delete the entire `_SUPPRESS_SLUGS = frozenset({...})` block and the `_resolve_synthesis_slugs()` function definition. They're now in `synthesis_validation.py`.

**Edit B — revert the constraining language in `_STRATEGY_SYNTHESIS_SYSTEM`:**

Replace this:

```python
- core-initiatives: list of up to 8 slugs of the most important initiatives (most \
central to the strategy's outcomes). ONLY use slugs that appear verbatim in the \
entity inventory provided — do not invent new slugs.
- core-actors: list of up to 6 slugs of the most important actors. ONLY use slugs \
that appear verbatim in the entity inventory provided — do not invent new slugs. \
Only include actors/ slugs — do not place initiatives or locations here.
```

with the original:

```python
- core-initiatives: list of up to 8 slugs of the most important initiatives (most \
central to the strategy's outcomes)
- core-actors: list of up to 6 slugs of the most important actors
```

And remove this from the cross-strategy-links bullet:

```python
. These \
may reference entities outside the current inventory.
```

**Edit C — wire validators into `synthesize_wiki()`:**

Add imports at the top of the file:

```python
from pipeline.synthesis_validation import (
    validate_synthesis,
    validate_narrative,
    revise_synthesis,
    revise_narrative,
    log_dropped_ghosts,
)
```

Remove the existing `aliases = load_aliases(aliases_path)` + `_resolve_synthesis_slugs(...)` flow inside `synthesize_wiki()`. Replace the per-strategy block:

```python
        else:
            synthesis = build_strategy_synthesis(
                strategy_slug=strategy_slug,
                strategy_title=title,
                entities=entities,
            )
            synthesis = _resolve_synthesis_slugs(synthesis, aliases)
            page = Path(wiki_root) / (strategy_slug + ".md")
            if page.exists():
                write_strategy_synthesis(str(page), synthesis, run_date=run_date)
                rebuilt.append(strategy_slug)
            else:
                print(f"[synthesize_wiki] strategy page missing: {page}")
```

with:

```python
        else:
            synthesis = build_strategy_synthesis(
                strategy_slug=strategy_slug,
                strategy_title=title,
                entities=entities,
            )
            # Validate → Revise loop
            synthesis, report = validate_synthesis(synthesis, wiki_root, aliases)
            if not report.is_clean:
                print(f"[synthesize_wiki] {strategy_slug}: {len(report.broken)} broken refs; revising")
                synthesis = revise_synthesis(synthesis, report, entities)
                # Re-validate to compute final dropped set for the log
                synthesis, post_report = validate_synthesis(synthesis, wiki_root, aliases)
                log_dropped_ghosts(
                    log_path=str(Path(wiki_root) / "meta" / "synthesis-ghosts.log"),
                    run_date=run_date,
                    context_label=strategy_slug,
                    ghosts=post_report.broken,
                )
                # Strip any still-broken slugs so the frontmatter is clean
                for field in ("core-initiatives", "core-actors", "cross-strategy-links"):
                    bad = {b.slug for b in post_report.broken if b.location == field}
                    synthesis[field] = [s for s in synthesis[field] if s not in bad]

            page = Path(wiki_root) / (strategy_slug + ".md")
            if page.exists():
                write_strategy_synthesis(str(page), synthesis, run_date=run_date)
                rebuilt.append(strategy_slug)
            else:
                print(f"[synthesize_wiki] strategy page missing: {page}")
```

Replace the digest narrative block:

```python
    narrative = build_digest_narrative(strategies_data=strategies_data)
```

with:

```python
    narrative = build_digest_narrative(strategies_data=strategies_data)
    # Validate → Revise the narrative
    narrative_report = validate_narrative(narrative, wiki_root, aliases)
    if not narrative_report.is_clean:
        print(f"[synthesize_wiki] digest narrative: {len(narrative_report.broken)} broken wikilinks; revising")
        # Build a combined inventory from every strategy for the narrative reviser
        combined_inventory: list[dict] = []
        for strategy_slug in targets:
            combined_inventory.extend(gather_strategy_entities(wiki_root, strategy_slug))
        narrative = revise_narrative(narrative, narrative_report, combined_inventory)
        post_narrative_report = validate_narrative(narrative, wiki_root, aliases)
        log_dropped_ghosts(
            log_path=str(Path(wiki_root) / "meta" / "synthesis-ghosts.log"),
            run_date=run_date,
            context_label="digest-narrative",
            ghosts=post_narrative_report.broken,
        )
```

Note: keep `aliases = load_aliases(aliases_path)` near the top of `synthesize_wiki()` — it's still needed (it's now passed to `validate_synthesis` and `validate_narrative` instead of used inline).

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -q`
Expected: PASS — 167 + 20 new = 187 passed, 1 skipped.

If `test_synthesize_wiki_orchestrates_end_to_end` fails because the fixture is missing the slug pages, add them (Step 1 above) and re-run.

- [ ] **Step 5: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py tests/fixtures/synthesize_wiki/
git commit -m "feat(synthesis): wire Validate→Revise loop into synthesize_wiki; revert inventory-binding prompt"
```

---

### Task 8: Smoke test against the real wiki

This is a manual verification step — no test code, just a sanity check that the full pipeline behaves correctly on real data.

- [ ] **Step 1: Run synthesize_wiki against the real wiki**

```bash
LLM_PROVIDER=anthropic python -m pipeline.synthesize_wiki --wiki-root wiki
```

Expected output: log lines showing per-strategy broken-ref counts and revisions, e.g.:
```
[synthesize_wiki] strategies/strategy-5-materials-waste: 2 broken refs; revising
[synthesize_wiki] strategies/strategy-6-resilience: 1 broken refs; revising
[synthesize_wiki] digest narrative: 3 broken wikilinks; revising
```

- [ ] **Step 2: Verify the synthesis frontmatter is clean**

```bash
grep -h "^  - actors/\|^  - initiatives/\|^  - locations/" wiki/strategies/strategy-*.md | sed 's/^  - //' | sort -u | while read slug; do
  if [ ! -f "wiki/$slug.md" ]; then echo "GHOST  $slug"; fi
done
```

Expected: no output (zero ghosts in synthesis frontmatter).

- [ ] **Step 3: Verify the digest is clean**

```bash
grep -oE '\[\[(actors|initiatives|locations)/[a-z0-9-]+' wiki/digest.md | sed 's/\[\[//' | sort -u | while read slug; do
  if [ ! -f "wiki/$slug.md" ]; then echo "GHOST  $slug"; fi
done
```

Expected: no output (zero broken wikilinks in digest.md).

- [ ] **Step 4: Review the ghost log**

```bash
cat wiki/meta/synthesis-ghosts.log
```

Expected: entries for each strategy and the digest narrative where ghosts were dropped. Each entry includes the slug, location, and (for narrative) surrounding context. Use this list to decide whether any recurring ghosts should become real pages or be added to `SUPPRESS_SLUGS`.

- [ ] **Step 5: Commit the regenerated wiki data**

```bash
git add wiki/strategies/*.md wiki/digest.md wiki/meta/synthesis-ghosts.log
git commit -m "data: regenerate synthesis + digest under Validate→Revise loop"
```

---

### Task 9: Update CLAUDE.md and CHANGELOG.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update CLAUDE.md Phase C synthesis description**

Find the section that describes `synthesize_wiki` (under "Active Architectural Direction" or wherever Phase C is documented). Add a sentence noting that synthesis runs a Write → Validate → Revise loop and that dropped-ghost entries land in `wiki/meta/synthesis-ghosts.log` for human review.

Specifically, in the Phase C commands block, add an explanatory note after the existing commands:

```markdown
The synthesizer runs each LLM output through a deterministic validator that checks
every entity slug against the filesystem. Broken references trigger a scoped Reviser
LLM call that either substitutes a real entity or drops the bad slug; dropped slugs
are logged to `wiki/meta/synthesis-ghosts.log` for human review. See
`docs/architecture/synthesis-validation-loop.md`.
```

- [ ] **Step 2: Update CHANGELOG.md**

Add a new entry at the top under today's date (2026-06-29):

```markdown
## 2026-06-29 — Synthesis validation loop

- Added Write → Validate → Revise pipeline to `synthesize_wiki` (`pipeline/synthesis_validation.py`)
- Validators check every entity slug against the filesystem before persisting strategy
  synthesis frontmatter or `digest.md`; broken refs trigger a scoped LLM Reviser call
- Dropped ghosts logged to `wiki/meta/synthesis-ghosts.log` for human review
- Reverted the inventory-binding language in `_STRATEGY_SYNTHESIS_SYSTEM` — the Writer
  is again free to reach for plausible entities; correctness is enforced at the
  validation boundary
- 20 new tests in `tests/test_synthesis_validation.py`
- Spec: `docs/architecture/synthesis-validation-loop.md`
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: document synthesis validation loop in CLAUDE.md and CHANGELOG"
```

---

## Self-Review Checklist

After completing all tasks:

- [ ] All 187 tests passing
- [ ] No ghosts in `wiki/strategies/*.md` synthesis frontmatter (Task 8 Step 2 returns empty)
- [ ] No broken wikilinks in `wiki/digest.md` (Task 8 Step 3 returns empty)
- [ ] `wiki/meta/synthesis-ghosts.log` exists and is being appended to
- [ ] `_STRATEGY_SYNTHESIS_SYSTEM` no longer contains "ONLY use slugs that appear verbatim"
- [ ] `_SUPPRESS_SLUGS` and `_resolve_synthesis_slugs()` removed from `synthesize_wiki.py`
- [ ] CLAUDE.md and CHANGELOG.md updated
