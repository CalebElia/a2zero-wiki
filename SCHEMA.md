# A2Zero Wiki — Schema V3

This file defines the architecture, page types, ingest rules, ontology governance,
and wikilink conventions for the A2Zero knowledge wiki. Read this before processing
any source document or querying the wiki.

---

## Architecture Overview

The A2Zero wiki uses a **three-layer medallion architecture**:

```
raw/             Immutable raw source files (PDFs, transcripts, originals)
sources/         Cleaned LLM-ready markdown — immutable, the citation anchor
wiki/            LLM-curated knowledge pages — the living wiki
blackboard/      Structured quad data (subject/predicate/object/source triples)
```

The previous medallion naming (`bronze/`, `silver/`) has been replaced with
self-documenting names that reflect what each layer actually is rather than its
position in an abstract pipeline pattern.

The wiki is an **Obsidian vault**. Every page is a Markdown file with YAML
frontmatter. Wikilinks (`[[slug|display]]`) are the primary relationship mechanism.
The Obsidian graph view reflects the citation graph.

---

## Folder Structure

```
wiki/
  index.md             Master catalog — one line per page, read FIRST on any query
  log.md               Append-only audit trail of every ingest/query/lint operation
  hot.md               ~500-word recent-state cache for cold-start session continuity
  overviews/           One synthesis page per source document (pass 1)
  strategies/          The 7 A2Zero strategy pages (pre-created stubs, bodies by pass 1)
  initiatives/         Named programs, pilots, projects (pass 1 stubs → pass 2 fills)
  actors/              Organizations and individuals (pass 1 stubs → pass 2 fills)
  locations/           Places and geographic units (pass 2)
  meetings/            Council meetings, public hearings (pass 2)
  topics/              Cross-cutting synthesis pages (candidate via pass 1, confirmed by human)
  contradictions/      Flagged tensions or inconsistencies (pass 2, low threshold)
  technology/          Technologies and tools (pass 2)
  political-events/    Legislative votes, elections, policy milestones (pass 2)
  meta/                Wiki governance files — not ingest output, not in index
    schema-drift.md    Proposed new types/verbs awaiting human review
    topic-candidates.md LLM-surfaced cross-cutting topics awaiting human promotion
    relationship-lexicon.md Approved relationship verbs with examples
  plans/               [DEPRECATED — replaced by overviews/]
```

---

## Three-Pass Ingest Pipeline

Every source document runs through three passes in order.

### Pass 1 — Holistic Synthesis (holistic_synthesizer.py)

**Reads the full source document before writing anything.** This is the most
important rule. Chunked extraction produces redundant, low-quality synthesis
because no chunk has cross-document context.

#### Writer → Evaluator → Editor loop

Pass 1 uses three sequential LLM calls rather than a single generation:

1. **Writer** — reads the full document, produces a draft JSON with four sections:
   `overview`, `strategy_bodies`, `stub_pages`, `topic_candidates`
2. **Evaluator** — reads the source AND the Writer draft, produces a structured
   critique: accuracy issues (hallucinations), completeness gaps (missed content),
   format issues (malformed wikilinks), redundancy (duplicate strategy body content),
   overall score (1-10), and `proceed_to_edit` flag
3. **Editor** — reads the source, draft, and critique, produces the final revised
   JSON addressing every flagged issue

If `proceed_to_edit: false` (score < 4), the Writer re-runs with the evaluator's
`accuracy_issues` fed back as context before the Editor step. Structural validation
(`_validate_synthesis_output`) wraps the Editor output; failures retry the Editor
with the error list appended.

**Model**: Sonnet 4.6 for all three steps. **max_tokens**: Writer 16384,
Evaluator 4096, Editor 16384. The `[FULL DOCUMENT]` block is marked with
`cache_control` so the Evaluator and Editor pay cache-read price on the document.

#### Pass 1 output (four sections)

```json
{
  "overview": { "slug": "...", "frontmatter": { ... }, "body": "..." },
  "strategy_bodies": [ { "slug": "strategies/...", "body": "..." }, ... ],
  "stub_pages": [
    {
      "type": "initiative",
      "title": "Community Choice Aggregation",
      "slug": "initiatives/community-choice-aggregation",
      "parent-strategy": "strategy-1-renewable-grid",
      "one-liner": "Municipal bulk renewable energy purchasing for all residents and businesses"
    }
  ],
  "topic_candidates": [
    { "title": "Environmental Justice", "rationale": "Appears across Strategies 1, 3, and 7 with equity framing" }
  ],
  "log_summary": "One sentence."
}
```

`stub_pages`: entities the Writer identified as worth tracking from the holistic
read — typically 20-50 items. The orchestrator creates minimal stub files for
these BEFORE Pass 2 begins, so major entities exist on disk even if their
primary section gets truncated in chunked extraction.

`topic_candidates`: cross-cutting themes the Writer noticed but which require
human judgment to promote to full `wiki/topics/` pages. Written to
`wiki/meta/topic-candidates.md`, not to `wiki/topics/` directly.

#### What Pass 1 writes

- `wiki/overviews/<source-uuid>.md` (new overview page)
- Strategy bodies written or integrated into `wiki/strategies/*.md` stubs
- Stub files at slugs listed in `stub_pages`
- Entry in `wiki/index.md`
- Entry appended to `wiki/log.md`
- Candidates appended to `wiki/meta/topic-candidates.md`

Only runs if `wiki/overviews/<source-uuid>.md` does not already exist (idempotent).

#### Multi-source integration — the living encyclopedia principle

The wiki is a **living encyclopedia**, not an append log. Every write to an existing
page is an integration pass, not an addition. This applies to **all page types** — strategy
pages written by Pass 1, and initiative, actor, location, framing, and all other pages
written by Pass 2.

**The read-understand-integrate model:**

1. Before writing to a page that already has content, the LLM reads the existing body.
2. It is instructed to integrate: preserve prior facts, add new depth and nuance from
   the current source, do not duplicate what is already there.
3. The output **replaces** the existing body with a coherent whole — a reader who has
   never seen the prior version should find it fully self-contained.

**Pass 1 implementation (strategy pages):** `synthesize_source()` reads all existing
strategy page bodies and includes them in the Writer's context as
`[EXISTING STRATEGY WIKI CONTENT]`. `_write_synthesis()` detects whether a strategy
page already has real content (beyond the initial stub comment) and calls
`_replace_wiki_page_body()` rather than `append_to_wiki_page()`.

**Pass 2 implementation (all other pages):** When the chunk extraction LLM produces
content for an entity whose page already exists, the existing page body is included in
the chunk context header alongside the known-entities list. The WIKI_PAGES_SYSTEM prompt
instructs the LLM to produce integrated body content. The pipeline replaces the page
body rather than appending.

This prevents the v2 failure mode: blind appending across five annual report ingests
produced four near-identical paragraphs per strategy page. The same failure would occur
for any page type if the integration principle is not enforced.

### Pass 2 — Extraction (wiki_writer.py via ldp.py)

Extracts and fills leaf-node pages: initiatives, actors, locations, meetings,
political-events, contradictions, technology.

**Short documents** (< ~1,000 lines or < 10 headings): `extract_wiki_pages_from_chunk()`
runs once on the full document body — no chunking loop, single API call. The stub
list from Pass 1 is still passed as context.

**Long documents** (LDP gate): section map → chunk loop. Each chunk is prefixed
with a context header (document title + section path + known-entity list from Pass 1
stubs) before the LLM sees it.

The known-entity list gives Pass 2 a checklist: "these entities were identified
from the full document — populate their stubs when you encounter them; don't
create duplicates under different slugs."

Pass 2 retains full autonomy to discover entities not in the stub list. These
"bonus pages" are created normally. The stub list is a floor, not a ceiling.

**Forbidden in Pass 2:** `overview`, `strategy`, `topic`, `synthesis`.
These types are owned by Pass 1 or human curation. See `PASS2_FORBIDDEN_TYPES`
in `pipeline/wiki_writer.py`.

Chunk boundaries: depth-2 headings are the primary unit. Depth-1 headings are
clipped to end before their first depth-2 child to prevent oversized catch-all chunks.

### Pass 3 — Finalization (wiki_index.py)

After all chunks are processed:
1. `rebuild_index(wiki_root)` — synchronizes `wiki/index.md` with all current page frontmatter
2. `append_log(...)` — seals the run with a summary line in `wiki/log.md`
3. `update_hot(wiki_root, summary)` — overwrites `wiki/hot.md` with session summary

---

## Infrastructure Files

### wiki/index.md

Master catalog. **Read this first** before answering any query. Format:

```markdown
# A2Zero Wiki Index

_143 pages — last updated 2026-06-23_

## overviews
- [[overviews/cap-2020|Ann Arbor A2Zero Living Carbon Neutrality Plan (2020)]]

## strategies
- [[strategies/strategy-1-renewable-grid|Strategy 1: 100% Renewable Energy Grid]]

## initiatives
- [[initiatives/community-choice-aggregation|Community Choice Aggregation]]
```

One line per page, grouped by type. Rebuilt automatically. Do not edit manually.

### wiki/log.md

Append-only audit trail. Format:

```markdown
## 2026-06-23 | cap-2020

Pass 1: Writer score 8/10. Overview written. 7 strategy bodies integrated.
        30 stubs created. 2 topic candidates surfaced.
Pass 2: 44 initiatives, 28 actors, 6 locations updated. 2 truncation warnings.
Pass 3: Index updated (143 pages).
```

### wiki/hot.md

~500-word summary of the most recent ingest. Overwritten (not appended) at end
of Pass 3. Read before index.md in a new session for immediate orientation.

### wiki/meta/schema-drift.md

Append-only record of LLM-proposed types or relationship verbs that had no
approved match. Human reviews periodically to approve (add to VALID_PAGE_TYPES)
or reject (reclassify). Format:

```markdown
## 2026-06-23 | Proposed type: "council-debate" | Written as: "meeting" | Page: "meetings/grid-modernization-hearing"
Title: 2023 Grid Modernization Hearing
Resolution: [ ] Approve new type  [ ] Keep as "meeting" + tag [council-debate]
```

The pipeline writes the page using the approved fallback type and captures
`proposed-type:` in the page's own frontmatter, so the page is immediately
navigable in Obsidian while awaiting human review.

### wiki/meta/topic-candidates.md

LLM-surfaced cross-cutting topics from Pass 1. Human promotes to `wiki/topics/`
or dismisses. Format:

```markdown
## Environmental Justice | Source: cap-2020 | 2026-06-23
Rationale: Equity framing appears across Strategies 1, 3, and 7 with specific
references to Bryant neighborhood and income-qualified programs.
Resolution: [ ] Promote to wiki/topics/environmental-justice.md  [ ] Dismiss
```

### wiki/meta/relationship-lexicon.md

Pre-seeded file (not generated by ingest) listing all approved relationship verbs.
Visible in Obsidian graph and searchable via full-text search.

---

## Ontology Governance — Semi-Open Schema

The A2Zero wiki uses a **semi-open ontology**: a pre-approved list of types and
relationship verbs, used first and strongly preferred, with a governed path for
proposing additions.

### Rule for LLM agents

1. **Use the closest approved type, even if imperfect.** Combine with tags for
   specificity. A `meeting` with tags `[council-debate, grid]` is always preferred
   over proposing a new `council-debate` type.
2. **Types vs. tags**: propose a new type only if the distinction changes HOW the
   page is processed or navigated (different frontmatter fields, different Pass 2
   behavior). If it's just semantic specificity, use a tag.
3. **When no approved type fits at all**: write the page using the **closest approved
   type** as `type:` AND add `proposed-type: <your-intended-type>` to the frontmatter.
   Never use an unapproved string as the primary `type` — it will fail validation and
   the page won't be written. The pipeline logs `proposed-type` to
   `wiki/meta/schema-drift.md` automatically for HITL review.

   Example — a zoning application doesn't fit any approved type:
   ```yaml
   type: political-event          # closest approved type
   proposed-type: zoning-application  # logged to schema-drift.md for review
   tags: [zoning, land-use]
   ```

4. **Same rule for relationship verbs**: use approved verbs from the lexicon; if
   none fit, use the closest and append the proposed verb to `schema-drift.md`.

### Current approved page types

**Pass 2 (chunked extraction):**
`initiative`, `actor`, `funding-event`, `technology`, `location`, `meeting`,
`framing`, `political-event`, `contradiction`, `mechanism`

**Pass 1 (holistic synthesizer only):**
`overview`, `strategy`

**Human-curated only:**
`topic`, `synthesis`

### Current approved relationship verbs

`implements`, `funds`, `supersedes`, `gates`, `enables`, `is part of`,
`was planned in`, `fulfilled in`, `missed in`, `contradicts`, `targets`,
`partners with`, `is administered by`

---

## Page Types

All pages have a `uuid:` field in frontmatter — SHA-256 of `(type + normalized title)`,
generated once at creation. The slug is for navigation; the UUID is the stable
identity across re-runs and slug changes.

### overview (Pass 1 only)

Path: `wiki/overviews/<source-uuid>.md`

One page per source document. The LLM-written synthesis of the full source.

```yaml
---
type: overview
uuid: "a3f8c2..."
title: "Ann Arbor A2Zero Living Carbon Neutrality Plan (2020)"
source-type: strategic-plan
source-ref: "[[silver/cap/cap-2020]]"
date: 2020-04
scope: community-wide
structure:
  - "Executive Summary"
  - "Seven Strategies"
  - "Implementation Actions"
  - "Appendices"
tags:
  - carbon-neutrality
  - a2zero
  - strategic-plan
last-updated: 2026-06-23
---
```

`structure:` (optional) — top-level section titles from the document TOC.
Useful for future sessions to orient within the source without re-reading it.

`source-type` values: `strategic-plan`, `annual-report`, `council-transcript`,
`news`, `research`.

Body: 3-5 paragraphs of synthesis prose. Not a table of contents — synthesize:
what does this document argue, what are the key commitments, what are the tensions.

When the holistic synthesizer creates this page, it also adds a `wiki-overview:`
backlink to the source file's frontmatter, making the link bidirectional:

```yaml
# Added to silver/cap/cap-2020.md by holistic_synthesizer:
wiki-overview: "[[overviews/cap-2020]]"
```

### strategy (Pass 1 only)

Path: `wiki/strategies/<slug>.md`

Pre-created stubs for the 7 A2Zero strategies. Bodies written by Pass 1 on first
ingest; integrated (read-understand-integrate) on each subsequent source ingest.
Never written by Pass 2.

```yaml
---
type: strategy
uuid: "b7d1e4..."
title: "Strategy 1: 100% Renewable Energy Grid"
strategy-number: 1
projections:
  - value: "40% of total A2Zero community GHG reduction by 2030"
    date: 2020-04
    source: "[[sources/cap/cap-2020]]"
outcomes: []
tags:
  - renewable-energy
  - grid
last-updated: 2026-06-23
---
```

`projections:` — quantitative targets or model projections from planning documents,
each with `value`, `date`, and `source` wikilink. Appended when a new source introduces
a projection; never overwritten.

`outcomes:` — measured results from annual reports or third-party evaluations. Same
structure as projections. Accumulates across ingests so the full trajectory is
machine-readable (e.g. for dashboard card extraction) without parsing prose.

Body: running synthesis updated each time a new source touching this strategy
is ingested via the read-understand-integrate model. Synthesize trends, tensions,
progress — do NOT concatenate bullet lists.

### initiative (Pass 1 stub → Pass 2 fills)

Path: `wiki/initiatives/<slug>.md`

A named program, pilot, project, or action item trackable across sources.

```yaml
---
type: initiative
uuid: "c9a2f1..."
title: "Community Choice Aggregation"
slug: community-choice-aggregation
parent-strategy: strategy-1-renewable-grid
status: planned
launched: null
projections:
  - value: "22% of community GHG reduction contribution by 2030"
    date: 2020-04
    source: "[[sources/cap/cap-2020]]"
outcomes: []
tags:
  - renewable-energy
  - cca
  - municipal-policy
source-first-seen: "[[sources/cap/cap-2020]]"
last-updated: 2026-06-23
---
```

`status` values: `planned`, `active`, `completed`, `stalled`, `unknown`.

`projections:` — quantitative targets from planning documents. Each entry: `value`
(string), `date` (YYYY or YYYY-MM), `source` (wikilink string). Populated by the
holistic synthesizer when a source document states a measurable target for this
initiative. New ingests append entries, never overwrite.

`outcomes:` — measured results from annual reports, case studies, or third-party
evaluations. Same structure as projections. Accumulates over time so the full
plan-vs-reality trajectory is machine-readable for dashboard extraction and
funder queries without requiring LLM prose parsing.

**Creation threshold**: create a page if the item has any of: (1) a proper name,
(2) attribution to a named organization with a defined role, (3) a budget, timeline,
or measurable target, (4) a name implying future tracking. When uncertain, create
a stub — a missed entity that recurs in Year 2 is worse than a thin page.

### actor (Pass 1 stub → Pass 2 fills)

Path: `wiki/actors/<slug>.md`

```yaml
---
type: actor
uuid: "d4b8e7..."
title: "Office of Sustainability and Innovations"
slug: office-of-sustainability-and-innovations
actor-type: city-department
role: party-responsible
tags:
  - city-government
  - sustainability
source-first-seen: "[[silver/cap/cap-2020]]"
last-updated: 2026-06-23
---
```

`actor-type` values: `city-department`, `utility`, `nonprofit`, `university`,
`state-agency`, `federal-agency`, `private-company`, `individual`, `community-group`.

### contradiction (Pass 2, low threshold)

Path: `wiki/contradictions/<slug>.md`

Flag any detectable tension — hard factual conflicts between sources, ambiguity
within a single document, discrepancies between a claim and an existing wiki page.
The threshold is low: if something feels like tension rather than clear contradiction,
create the page anyway. Do not flatten it into the summary.

```yaml
---
type: contradiction
uuid: "e2c6d9..."
title: "CCA cost estimate discrepancy"
sources:
  - "[[silver/cap/cap-2020]]"
  - "[[silver/annual-report-year1]]"
status: flagged
tags:
  - cca
  - cost-estimate
last-updated: 2026-06-23
---
```

`status` values: `flagged` (tension detected, needs review), `unresolved`
(clear conflict confirmed), `resolved` (human-reviewed and closed).

Body: the conflicting claims side by side, exact section and source for each,
best-guess explanation if plausible. Can reference a single source if the
contradiction is within that document.

### framing (Pass 2)

Path: `wiki/framing/<slug>.md`

A communications strategy, messaging approach, or advocacy framing that shaped a
policy outcome. Captures how an initiative or political event was positioned publicly,
what role community advocates and coalitions played, and whether the framing succeeded
or failed. First-class page type for the Advocates audience: the political and
communications story is as important as the policy content.

```yaml
---
type: framing
uuid: "f3a8b2..."
title: "Community Benefits Framing for SEU Launch"
actor: "[[actors/a2zero-coalition]]"
related-initiative: "[[initiatives/sustainable-energy-utility]]"
related-event: "[[political-events/seu-council-vote-2022]]"
tags:
  - communications
  - coalition
  - seu
source-first-seen: "[[sources/annual-reports/annual-report-year2]]"
last-updated: 2026-06-23
---
```

Body: the framing approach, key messages, who carried them and to whom, what role
this communications strategy played in the policy outcome. Where relevant, note
whether the framing succeeded, failed, or evolved. Cross-reference associated
`political-event` and `actor` pages.

### topic (Pass 1 candidate → human-promoted)

Path: `wiki/topics/<slug>.md`

Cross-cutting synthesis pages spanning multiple strategies or sources. Topics
are surfaced by Pass 1 via `topic_candidates` in the Writer output and routed
to `wiki/meta/topic-candidates.md` for human review. A human either promotes
a candidate to a full topic page or dismisses it. Topics can also be
pre-created manually before ingest begins.

### Other Pass 2 types

| Type | Path | Notes |
|---|---|---|
| `location` | `wiki/locations/<slug>.md` | Neighborhoods, districts, specific sites |
| `meeting` | `wiki/meetings/<slug>.md` | Council meetings, public hearings |
| `technology` | `wiki/technology/<slug>.md` | Technologies, tools, infrastructure types |
| `political-event` | `wiki/political-events/<slug>.md` | Votes, elections, legislative milestones |

---

## Wikilink & Citation Conventions

### Format

```
[[slug]]                    — link only
[[slug|display text]]       — link with custom display
```

Slugs are relative to the vault root (no leading `wiki/`).

### Citation in body prose

```
The CCA is projected to reduce community emissions by 22% ([[silver/cap/cap-2020|cap-2020]]).
```

Never copy bullet lists verbatim. Synthesize and rephrase, then cite.

### Relationship verbs

Never write "related to." Use specific verbs from the approved lexicon
(see `wiki/meta/relationship-lexicon.md`):

```
implements, funds, supersedes, gates, enables, is part of,
was planned in, fulfilled in, missed in, contradicts, targets,
partners with, is administered by
```

If none fit, use the closest and append the novel verb to `schema-drift.md`.

### Source-to-wiki backlink chain

Every wiki page originating from a source document includes `source-first-seen`
in frontmatter. The source file is the most-connected node in the graph:

```
silver/cap/cap-2020.md
  ← (wiki-overview)        wiki/overviews/cap-2020.md  [bidirectional]
  ← (source-first-seen)    wiki/initiatives/cca.md
  ← (source-first-seen)    wiki/actors/osi.md
  ← (source-first-seen)    wiki/strategies/strategy-1-renewable-grid.md
  ...
```

---

## Ingest Workflow Summary

For each new source document:

1. Add cleaned markdown to `silver/<source-type>/<slug>.md`
2. Run `python -m pipeline.run_ingest silver --source <path> [--wiki-only]`
3. **Pass 1**: holistic synthesizer reads full doc → W→E→E loop → writes overview,
   strategy bodies, stub pages, topic candidates, seeds index, opens log entry
4. **Pass 2**: wiki extraction → populates stubs + discovers new pages;
   short docs use single-call extraction, long docs use chunk loop
5. **Pass 3**: synchronizes index with all page frontmatter, seals log, updates hot.md

---

## Rules the LLM Must Follow

1. **Read the full source document before writing any wiki page** (Pass 1 only).
2. **Check `wiki/index.md` before creating any page.** If a page exists, append — do not duplicate.
3. **Never write `overview` or `strategy` pages from Pass 2.**
4. **One page per entity** across all sources — update existing pages, do not create duplicates.
5. **Never overwrite `wiki/log.md`** — append only.
6. **Never overwrite `wiki/hot.md`** except at end of Pass 3.
7. **Validate before writing** — structural validation runs on Editor output before any disk write.
8. **Prefer approved types and relationship verbs.** Only propose new ones when no approved term fits.
9. **Use tags for specificity, types for structural differences** in how pages are processed.
10. **Cite specifically** — every claim in a wiki page body should be traceable to a wikilink.
11. **Low threshold for contradictions** — if it feels like tension, flag it; don't flatten it.
12. **Read-understand-integrate for all pages** — every write to an existing wiki page is an integration pass, not an append. Read the existing body first. Preserve prior facts. Add new depth and nuance from the current source. Do not duplicate. The output replaces the existing body as a coherent whole. This applies to strategy pages (Pass 1), initiative pages, actor pages, and all other page types (Pass 2).
13. **Distinguish projections from outcomes** — a quantitative figure from a planning document (e.g. "22% reduction by 2030") is a projection. A figure from an annual report or evaluation (e.g. "6.8% reduction measured in 2023") is an outcome. Both belong in the structured `projections:` / `outcomes:` frontmatter lists with dates and source wikilinks, not only in prose.

---

## V3 Change Log

| What changed | Why |
|---|---|
| `wiki/plans/` → `wiki/overviews/` | Generalizes to all source types, not just strategic plans |
| Writer → Evaluator → Editor loop | Prevents hallucination and completeness gaps in Pass 1 synthesis |
| `stub_pages` from Pass 1 Writer | Holistic read seeds entity stubs before chunked extraction; prevents dedup failures |
| `topic_candidates` from Pass 1 Writer | LLM surfaces cross-cutting themes without auto-promoting — HITL gate |
| `wiki/meta/` directory | Governance files (schema-drift, topic-candidates, relationship-lexicon) |
| Semi-open ontology with `schema-drift.md` | Approved list first; novel types proposed and flagged, not silently rejected |
| `uuid:` field on all pages | SHA-256 stable identity; slug can change without breaking entity resolution |
| `structure:` field on overview | Optional TOC captures document outline for future session orientation |
| Contradiction threshold lowered | Any tension flagged; `status: flagged` for uncertain cases |
| `strategy` added to `PASS2_FORBIDDEN_TYPES` | Strategy bodies require full-doc context; chunk extraction produced noise |
| `plan` type removed | Replaced by `overview` with `source-type: strategic-plan` |
| `wiki/index.md`, `wiki/log.md`, `wiki/hot.md` | Core LLM-wiki infrastructure (Karpathy pattern) |
| Prompt caching on `[FULL DOCUMENT]` block | W→E→E loop reuses same document — cache_control saves ~60% on calls 2 and 3 |
| max_tokens per step: 16384 / 4096 / 16384 | Writer/Editor need headroom; prior 8192 truncated 8 of 20 chunks |
| `silver/` → `sources/` (pending rename) | Wikilink citations self-documenting inside the vault |
| Chunk clipping: depth-1 ends before first depth-2 child | Prevents 3,000+ line catch-all chunks from duplicating all strategy content |
| Read-understand-integrate model for multi-source ingest | v2 failure: blind append across 5 annual report ingests produced 4 near-identical paragraphs per strategy; holistic synthesizer now reads existing page bodies before writing and replaces rather than appends |
| `projections:` + `outcomes:` structured frontmatter lists | Enables machine-readable plan-vs-reality trajectory tracking; dashboard cards and funder queries can extract dated figures without LLM prose parsing |
| `framing` type formally defined | Communications strategy and advocacy coalition pages are first-class entities for the Advocates audience |
