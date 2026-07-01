# Chunking Gate

## A Human-in-the-Loop Review Step Before Pass 2 Extraction

*Spec: 2026-06-30. Pre-implementation. Branch: `feat/chunking-gate` (stacked on `refactor/pipeline-rename`).*

---

## The Problem This Solves

Pass 2 of the ingest pipeline (LDP — Long Document Processor) chops the source into chunks before extraction. Today this happens purely mechanically: `parse_section_map()` in `pipeline/pass2a_chunk_loop.py` runs a regex over markdown headings and produces section boundaries. Sections at heading depth 1 and 2 become extraction chunks; deeper headings get rolled up into their parents.

This works fine for the current source corpus (A2Zero CAP and annual reports) because those documents have clean, semantically meaningful heading structure. A "Strategy 1" section in an annual report is a coherent unit that maps naturally to a chunk.

It will not generalize. The wiki's research agenda includes source types where mechanical chunking will fail in characteristic ways:

- **Council meeting transcripts.** Heading-free or pseudo-headings (timestamps, speaker names). A two-hour transcript becomes one giant chunk that exceeds context window.
- **News articles.** Many short pieces with shallow structure. Either over-chunked (every paragraph) or under-chunked (whole article as one).
- **Research papers.** Heading depth (`## Abstract`, `## Methods`) doesn't map to logical extraction units; you'd want chunks defined by argumentative structure, not section labels.
- **OCR'd PDFs.** Heading detection fails entirely when source formatting was lost.

Bad chunks have an outsized impact on downstream quality. A chunk that splits an entity description in half causes the LLM to extract a partial entity from each half — producing fragmented duplicates that the lint cycle then has to clean up. A chunk that fuses two unrelated topics dilutes the extraction signal. Both failure modes cost real time in human review.

**The solution this spec proposes:** A human-in-the-loop gate between mechanical chunking and Pass 2 extraction. The pipeline produces a *proposed* section map (mechanical, fast, no LLM). The human reviews it, optionally edits it, and explicitly approves it. The orchestrator then loads the approved map instead of generating fresh.

The Year 3 annual report is a clean source where mechanical chunking is correct. That's *why* it's the right shakedown for the gate: we get to validate the new HITL workflow before it's load-bearing, in a regime where errors should be minimal.

---

## The Architecture

A new preflight stage runs *before* the main orchestrator's `source` subcommand. The orchestrator gains two new subcommands:

```
┌──────────────────────────┐
│   prepared/<type>/       │
│   <uuid>.md              │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│ 1. preflight                          │
│    (mechanical, no LLM)               │
│                                       │
│    parse_section_map → proposed.json  │
│    generate_preview → preview.md      │
└──────────┬───────────────────────────┘
           │
           ▼
       (HUMAN GATE)
           │
           │  read preview.md
           │  optionally edit proposed.json
           │
           ▼
┌──────────────────────────────────────┐
│ 2. approve                            │
│    (mechanical, no LLM)               │
│                                       │
│    validate proposed.json             │
│    rename proposed → approved         │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│ 3. source                             │
│    (existing — Pass 0/1A/1B/2/3)      │
│                                       │
│    LDP path loads approved.json       │
│    rather than generating fresh       │
└──────────────────────────────────────┘
```

The gate only fires when the source would route to LDP. Small documents (those that fail the `_should_use_ldp` threshold) bypass it — they're handled as a single chunk anyway, so there's nothing to review.

---

## The Two Artifacts

### `<uuid>_proposed.json` — the editable source of truth

The full machine-readable section map. Today's `parse_section_map()` output extended with two new fields per section: `is_chunk` (whether this section becomes its own LDP chunk) and `notes` (free-text human annotation, optional).

```json
{
  "document_uuid": "a2zero-year3",
  "total_lines": 247,
  "ldp_version": "1.1",
  "approved": false,
  "sections": [
    {
      "id": "table-of-contents",
      "title": "Table of Contents",
      "depth": 1,
      "line_start": 5,
      "line_end": 18,
      "is_chunk": false,
      "notes": "ToC — skip extraction"
    },
    {
      "id": "strategy-1-power-our-electric-grid",
      "title": "Strategy 1: Power our electric grid with 100% renewable energy",
      "depth": 2,
      "line_start": 20,
      "line_end": 48,
      "is_chunk": true,
      "notes": ""
    },
    ...
  ]
}
```

**Edits a human can make:**
- Toggle `is_chunk` — promote a depth-3 section to its own chunk, or roll a depth-2 into its parent
- Edit `title` for clarity (useful when source headings are cryptic)
- Adjust `line_start` / `line_end` to merge two sections or split one
- Delete a section entirely (boilerplate, ToC, blank pages, references)
- Add `notes` for later humans (or future-you) reviewing the integration

**The `approved: false` flag** at the top is the gate's status marker. `approve` flips it to `true` and renames the file from `_proposed.json` to `_approved.json`.

### `<uuid>_preview.md` — generated, read-only, human-friendly

A markdown rendering of the proposed map, organized so a human can eyeball quality without opening the JSON. One section per chunk, with metadata and a content preview.

```markdown
# Chunk Preview: a2zero-year3

**Source:** prepared/annual-reports/a2zero-year3.md
**Total lines:** 247
**Proposed chunks:** 12

---

## Chunk 1 — Strategy 1: Power our electric grid with 100% renewable energy
- **Lines:** 20–48 (~1,820 chars, ~455 tokens)
- **Depth:** 2
- **Notes:** _none_

> Strategy 1 focuses on the City's transition to a 100% renewable electricity supply
> through a combination of utility intervention, community solar deployment, and
> grid capacity expansion. In Year 3, the City advanced several key initiatives...

---

## Chunk 2 — Strategy 2: Switch our appliances and vehicles from fossil fuels
- **Lines:** 50–82 (~2,140 chars, ~535 tokens)
- **Depth:** 2
- **Notes:** _none_

> Building and vehicle electrification accelerated significantly in Year 3...

---
```

The preview shows only sections where `is_chunk: true`. Sections marked `is_chunk: false` get a brief "(skipped)" note at the bottom of the file so the human can see what was excluded.

The preview file is **regenerated** every time `preflight` runs. The human never edits it; it's a read-only view.

---

## CLI Behavior

### `preflight` — generate the proposed map

```bash
python -m pipeline.orchestrator preflight \
  --source prepared/annual-reports/a2zero-year3.md \
  --uuid a2zero-year3 \
  [--section-maps-dir blackboard/section_maps]
```

**Behavior:**
- Reads source, runs `parse_section_map()` (no LLM, deterministic regex)
- Defaults `is_chunk: true` for depth-1 and depth-2 sections, `false` for depth-3+
- Writes `<uuid>_proposed.json` and `<uuid>_preview.md`
- If `<uuid>_approved.json` already exists, refuses to run unless `--force` is passed (prevents accidentally clobbering work)
- Prints next-step instructions: "Review preview.md. When ready: `python -m pipeline.orchestrator approve --uuid a2zero-year3`"

### `approve` — validate and promote

```bash
python -m pipeline.orchestrator approve \
  --uuid a2zero-year3 \
  [--section-maps-dir blackboard/section_maps]
```

**Behavior:**
- Loads `<uuid>_proposed.json`
- Runs validation (see below); rejects with clear errors if invalid
- Sets `approved: true`, writes to `<uuid>_approved.json`, deletes `_proposed.json`
- Prints: "Approved. Run: `python -m pipeline.orchestrator source --source ... --uuid a2zero-year3 ...`"

**Validation rules:**
- No section has `line_start > line_end`
- No two `is_chunk: true` sections have overlapping line ranges
- All `line_start` and `line_end` values are within `1..total_lines`
- At least one section has `is_chunk: true` (otherwise nothing gets extracted)
- The `approved` flag in the file is currently `false` (refuses to re-approve an already-approved file)

### `source` — the existing ingest command (modified)

```bash
python -m pipeline.orchestrator source \
  --source prepared/annual-reports/a2zero-year3.md \
  --uuid a2zero-year3 \
  --title "..." \
  [--auto-approve] \
  ...
```

**New behavior:**
- If the source would route to LDP (`_should_use_ldp` returns True):
  - Looks for `<uuid>_approved.json`. If it exists, loads it and uses its section map. Skips `parse_section_map()` entirely.
  - If `_approved.json` is missing:
    - With `--auto-approve`: silently runs `parse_section_map()` and proceeds (current behavior). Logs: `[orchestrator] WARNING: --auto-approve bypassed the chunking gate.`
    - Without `--auto-approve`: refuses with a clear error: `"No approved section map for <uuid>. Run 'python -m pipeline.orchestrator preflight ...' first, review the preview, then 'approve'. Or pass --auto-approve to bypass the gate."`
- If the source routes to the small-doc path (no LDP): gate is bypassed entirely, no warning needed. Small docs don't have chunks to review.

The `--auto-approve` flag exists as an escape hatch for cases where you trust mechanical chunking (batch ingests of homogeneous sources you've already validated the pattern for).

---

## Interaction with the Rest of the Pipeline

**Comprehend (Pass 1A)** is unaffected. The integration plan depends on the digest + source text, not on the section map. Comprehend runs at its usual point in the orchestrator pass.

**Holistic synthesis (Pass 1B)** is unaffected. It reads the full source, not chunks.

**LDP (Pass 2)** changes one line of orchestration: instead of calling `parse_section_map(source_content, uuid)` to generate the map fresh, it loads from `<uuid>_approved.json`. Downstream chunk processing is unchanged — once the map is loaded, the chunk loop behaves identically.

**Pass 3 (finalize)** is unaffected.

**Backward compatibility:**
- CAP-2020, Year 1, Year 2 are already ingested. Their existing `<uuid>_structure.json` files (the legacy filename) stay where they are; the orchestrator doesn't touch them.
- The new gate only fires on *future* ingests starting with Year 3.
- The legacy `<uuid>_structure.json` filename and `<uuid>_approved.json` are distinct; no risk of collision.

---

## Where the Code Lives

A new module: `pipeline/pass2a_pre_chunking.py`. Public surface:

```python
def generate_proposed_map(
    source_content: str,
    source_uuid: str,
    section_maps_dir: str,
    force: bool = False,
) -> tuple[str, str]:
    """Run parse_section_map; write proposed.json + preview.md. Returns (json_path, preview_path).
    Raises if approved.json exists and force=False."""

def approve_proposed_map(
    source_uuid: str,
    section_maps_dir: str,
) -> str:
    """Validate proposed.json; promote to approved.json. Returns approved.json path.
    Raises ValueError with all validation errors if invalid."""

def load_approved_map(
    source_uuid: str,
    section_maps_dir: str,
) -> dict | None:
    """Load <uuid>_approved.json. Returns None if missing (caller decides how to handle)."""

def render_preview_markdown(section_map: dict, source_content: str) -> str:
    """Build the human-readable preview from a section map + source body."""

def validate_section_map(section_map: dict) -> list[str]:
    """Return list of validation errors (empty if valid)."""
```

Changes to existing modules:

| File | Change |
|------|--------|
| `pipeline/orchestrator.py` | Add `preflight` and `approve` subcommands; modify `source` subcommand to check for approved map (and respect `--auto-approve` flag) |
| `pipeline/pass2a_chunk_loop.py` | In `run_ldp_ingest`, replace inline `parse_section_map(...)` call with `load_approved_map(uuid)` and a fallback to mechanical when `--auto-approve` was passed (signaled via a new kwarg) |

---

## Open Questions

These are decisions worth making explicitly. My recommendations follow each.

1. **Token estimation in the preview.** The preview shows estimated tokens per chunk (using 4 chars/token heuristic). Should we instead use an actual tokenizer (tiktoken)? **Recommendation:** stick with the heuristic. The preview is for human eyeballing, not precise budgeting. The heuristic is accurate to ±20% which is fine for "is this chunk too big?" judgment.

2. **Should `preflight` print a summary to stdout?** Yes — at minimum: number of proposed chunks, total source lines covered, any sections marked `is_chunk: false`. **Recommendation:** yes, terse stdout summary. The user reads the preview file for details.

3. **What if the human deletes the proposed.json before running approve?** `approve` should error with a clear message: "No proposed map for <uuid>. Run preflight first." **Recommendation:** yes — but no special recovery logic. The human reruns preflight.

4. **Section map versioning.** Today: `ldp_version: "1.0"`. The new fields bump it to `1.1`. **Recommendation:** version-bump and add a comment to the LDP loader that 1.0 maps without `is_chunk` should default to "true for depth 1-2, false otherwise" — keeping backward compat with the existing year1/year2 maps if they ever get re-loaded.

5. **Tests for the validation rules.** All six validation cases (negative ranges, overlaps, out-of-bounds, no chunks, already-approved, missing-file) should have unit tests. **Recommendation:** yes, one test per validation case.

6. **Smoke test for Year 3.** The plan should include a smoke test: run `preflight` on Year 3, inspect the preview, run `approve`, then attempt `source` and confirm it now loads the approved map. **Recommendation:** yes — this is exactly the shakedown the user asked for.

---

## Out of Scope

- **Integration plan preview gate.** If the user later wants a HITL review of the Comprehend output before downstream passes commit to it, that's a separate feature.
- **Chunk content editing in the JSON.** The human edits *boundaries* (line_start, line_end, is_chunk). They don't edit the actual chunk text — that lives in the source file.
- **GUI / web review interface.** Plain JSON + plain markdown. Edit in any editor. Anything fancier is a tooling decision for later.
- **Automated chunk quality detection.** Heuristics like "this chunk is huge" or "this chunk has no headings" could surface as warnings during preflight. Useful but distinct work.
- **Re-approving an already-approved map.** If you need to re-review after ingest, manually delete `_approved.json` and re-run preflight. Don't build an "edit approved" command.
- **Migration tooling for legacy `<uuid>_structure.json` files.** Those are already ingested. No need to touch them.
