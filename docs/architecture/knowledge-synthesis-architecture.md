# Knowledge Synthesis Architecture
## How the A2Zero Wiki Accumulates Understanding Across Sources

*Locked in: 2026-06-26. Decisions from design conversation, pre-implementation.*

---

## The Core Problem: LLM-Wiki's Broken Compounding Property

The foundational insight behind LLM-Wiki (Karpathy, 2025) is that the wiki is both *output* and *memory* — it should function as a living knowledge base that compounds understanding across sources, not a document index. Each new source should be integrated against what the system already knows, not processed in isolation.

The current pipeline breaks this property. When the LDP extraction pass reads a new annual report section-by-section, it has no visibility into what the wiki already says about the entities mentioned. It produces pages as if the wiki were empty. This is why three flagship A2Zero initiatives — Bryant Neighborhood Decarbonization, the Sustainable Energy Utility, and Solarize Ann Arbor — each fragmented across 2-3 disconnected pages during the Year 2 ingest. Each extraction pass saw mentions of the same initiative under slightly different names and created new pages rather than updating existing ones.

**The naive fix doesn't work:** injecting all existing wiki pages as context before every extraction would cost 120,000+ tokens per ingest and produce quality degradation from context overload before the wiki reaches 200 pages.

The solution requires a synthesis architecture that gives the LLM *structured, compressed knowledge* about the wiki before it reads a new source — enough to orient itself and make good integration decisions, without flooding the context window.

---

## GraphRAG as the Conceptual Frame

Microsoft's GraphRAG system (Edge et al., 2024) addresses an analogous problem: how do you answer "global" questions about a large knowledge corpus when no single context window can hold the full corpus?

GraphRAG's answer is a **hierarchical summarization pipeline**:

1. Extract entities and relationships from raw text → knowledge graph
2. Run community detection on the graph (Leiden algorithm) → clusters of related entities
3. Generate **community reports** — LLM-written summaries of each cluster
4. Build **meta-community summaries** from the community reports
5. At query time, retrieve from the appropriate level of the hierarchy based on query scope

The key insight GraphRAG demonstrates: **the right retrieval unit for "global" questions is not a document or an entity, but a community summary** — a synthesized account of a cluster of related entities and their relationships.

This maps directly onto our problem. The "global question" we need to answer at the start of every ingest is: *"What does the wiki already know, and how does this new source relate to it?"* Individual entity pages don't answer that. A synthesis of what the wiki knows, organized by domain, does.

### The critical difference: we don't need community detection

GraphRAG runs Leiden because it doesn't know in advance how entities cluster. The A2Zero wiki does know: **the 7 A2Zero strategies are the communities, pre-defined by the plan itself.** This is strictly better than algorithmic detection because:

- The communities have human-meaningful names and stable identities
- They're semantically grounded in Ann Arbor's own policy vocabulary
- They don't drift as new sources are ingested
- Every entity page already carries `related-strategies:` frontmatter that assigns it to communities

The strategies replace community detection. We get GraphRAG's synthesis hierarchy without the graph computation.

---

## The Three-Level Synthesis Hierarchy

```
L2: wiki/digest.md          ← injected into every Comprehend pass (~4-6k tokens)
        ↑ built from
L1: wiki/strategies/strategy-*.md   ← rebuilt after each ingest (7 files, LLM-maintained)
        ↑ aggregated from
L0: wiki/actors/, initiatives/, etc.  ← entity pages (existing, produced by LDP)
```

### L0 — Entity Pages (exists, mature)

Individual pages for actors, initiatives, locations, political events, funding events, technology, meetings. Produced by Pass 1 (stub creation) and Pass 2 (LDP body extraction). 399 pages as of Year 2 ingest.

These are GraphRAG's entity nodes. They're leaf-level knowledge — specific facts about specific things.

### L1 — Strategy Synthesis Pages (exists as prose, needs LLM maintenance)

The 7 strategy pages currently contain prose bodies written by Pass 1's holistic synthesizer and manually edited. They function as community reports but are maintained ad hoc.

**Design decision:** Strategy pages need a structured machine-readable section in addition to their human-readable prose body. The structured section is what L2 aggregates from; the prose body is what humans read.

Structured section format (to be added to each strategy page):

```yaml
synthesis:
  core-initiatives: [solarize-ann-arbor, wheeler-center-solar-park, ...]
  core-actors: [glrea, solar-moonshot, osi]
  year-over-year-arc: "31% residential growth Y1→Y2; commercial pilot launched"
  open-questions: ["DTE intervention outcomes pending", "5MW Y3 target feasibility"]
  cross-strategy-links: [bryant-neighborhood-decarbonization, sustainable-energy-utility]
  last-rebuilt: "2026-06-26"
```

The prose body stays human-editable. The `synthesis:` section is machine-maintained and overwritten by `synthesize_wiki` after each ingest cycle.

**Rebuild scope:** After each ingest, only strategies that were meaningfully touched by the new source need to be rebuilt. The integration plan (produced by the Comprehend pass) identifies which strategies are relevant, bounding the rebuild cost.

### L2 — Wiki Digest (to build: `wiki/digest.md`)

**Design decision: L2 and L3 are the same document.**

The initial design proposed separating L2 (cross-strategy synthesis for humans) from L3 (compressed digest for ingest injection). On examination, this separation is unnecessary friction — if L3 is purely derived from L2, they should be one file. The digest serves both audiences through structure:

```markdown
# Wiki Digest
*State as of: 2026-06-26 (post-Year-2 ingest, post-lint)*

## Cross-strategy synthesis          ← human-readable, substantive narrative
[What the wiki knows at the theme level. Where strategies connect.
What's unresolved. Which entities span multiple domains. This is
GraphRAG's "global answer" layer, maintained as a wiki artifact.]

## Strategy entity map               ← machine-readable, compact, structured
### Strategy 1 — Renewable Grid
initiatives: solarize-ann-arbor, wheeler-center-solar-park, ...
actors: glrea, solar-moonshot, osi
arc: ...
open: ...

### Strategy 2 — Electrification
...

## Recent delta                      ← recency signal for Comprehend pass
Last ingest: a2zero-year2 (2026-06-26). Added 148 pages.
Notable: a2r3, electrification-expo, aqmesh-air-quality-monitoring, commercial-solarize-pilot
```

The Comprehend pass injects the full `digest.md` as context before reading any new source. The narrative sections give it conceptual orientation; the entity map gives it the structured prior over what exists.

**Token budget:** ~4-6k tokens at current wiki size. Expected to grow linearly with the number of strategies (fixed at 7 for A2Zero) and the length of the entity map (grows with sources, but compressible by capping per-strategy entity lists at top-N).

---

## The Comprehend → Plan → Write Architecture

### Why "Comprehend" is separate from "Write"

The current holistic synthesizer does both in one pass: read the full source, then immediately write strategy bodies and entity stubs. This conflates understanding with writing. The LLM can't simultaneously read for comprehension and write for integration — it ends up treating the new source as if it's the only source.

**Design decision:** Split the holistic synthesizer into two distinct API calls.

**Call A — Comprehend** (reads: digest.md + new source):
Produces a structured integration plan:
```json
{
  "strategies-touched": ["strategy-1", "strategy-2", "strategy-3"],
  "confirms": [
    {"entity": "solarize-ann-arbor", "slug": "initiatives/solarize-ann-arbor",
     "new-data": "1.7MW additional in Year 2, 430+ total homes"}
  ],
  "extends": [
    {"entity": "bryant-neighborhood-decarbonization",
     "slug": "initiatives/bryant-neighborhood-decarbonization",
     "new-data": "EPA grant received, McKnight funding added"}
  ],
  "contradicts": [],
  "new-entities": ["electrification-expo", "aqmesh-air-quality-monitoring"],
  "retrieve-for-context": [
    "initiatives/solarize-ann-arbor",
    "initiatives/bryant-neighborhood-decarbonization",
    "initiatives/sustainable-energy-utility"
  ],
  "theme-connections": [
    "utility-pole-ev-charging connects Strategy 4 (VMT) to Strategy 1 (grid-edge solar)"
  ]
}
```

**Call B — Plan → LDP Write** (reads: integration plan + entity bodies from `retrieve-for-context` + source chunks):
The LDP pass operates guided by the integration plan. Each chunk prompt includes:
- The integration plan's verdict on which entities to expect
- The existing page bodies for entities in `retrieve-for-context`
- The source chunk text

The LDP still does its own bottom-up extraction and will surface entities not in the plan. When it does, it creates new entity pages as before. The plan is a prior, not a constraint.

### What the Comprehend→Plan step doesn't replace

The Comprehend pass is a holistic read — high recall on major entities, lower recall on specific details buried in tables, appendices, vote records, funding amounts. LDP remains the exhaustive ground-truth extraction. The relationship is:

- **Comprehend→Plan**: top-down map of what to expect and how to integrate it
- **LDP**: bottom-up excavation that fills in all the detail the holistic pass glosses over

Lint remains the backstop for noise that both passes produce: misrouted pages, near-duplicates for entities the alias registry didn't catch, missed backlinks. The lint cycle is not made redundant by better upstream passes — it catches the irreducible residual from any extraction process.

---

## The Four-Phase Ingest Cycle

**Design decision:** Synthesis (digest rebuild) must come *after* lint and human review, not during Pass 3.

**Why:** If the digest is rebuilt immediately after extraction, it encodes the dirty pre-lint state — including misrouted pages, near-duplicates, and broken links. The digest then propagates those errors into the next ingest's Comprehend pass. The system compounds mistakes.

The correct ordering:

```
Phase A — Extraction
  Pass 0: copy prepared/ → wiki/sources/, inject YAML
  Pass 1: Comprehend (reads digest.md) → integration plan
          Holistic write: strategy bodies, entity stubs
  Pass 2: LDP extraction guided by integration plan
  Pass 3: rebuild index.md, seed aliases, append log.md

  Command: python -m pipeline.run_ingest source --source prepared/... --wiki-only

Phase B — Review  [HUMAN GATE — cannot be skipped]
  python -m pipeline.lint_wiki --structural   # TYPE_MISMATCH, broken links, orphans
  python -m pipeline.lint_wiki --semantic     # near-duplicates, cross-directory
  python -m pipeline.lint_wiki --backlink     # missed entity mentions
  <human reviews and annotates review-queue.md>
  python -m pipeline.lint_wiki --apply        # execute approved proposals

Phase C — Synthesis  [run after --apply completes]
  For each strategy touched (from integration plan): rebuild synthesis: section
  Build wiki/digest.md: cross-strategy narrative + entity map + recent delta
  
  Command: python -m pipeline.synthesize_wiki --wiki-root wiki

Phase D — Ready for next ingest
  digest.md reflects post-lint, human-reviewed wiki state
  Next ingest reads it in Comprehend pass
```

The human review gate between Phase B and Phase C is structural, not optional. The wiki's synthesis layer should always reflect a state a human has signed off on.

---

## Design Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| L2 and L3 are the same document | `wiki/digest.md` serves both purposes | Separate docs = unnecessary sync friction if one derives from the other |
| Community detection | Not needed; 7 strategies are pre-defined communities | Strategies are semantically grounded, stable, human-legible — better than Leiden |
| Comprehend and Write are separate API calls | Two-call holistic synthesizer | Can't simultaneously read for comprehension and write for integration in one pass |
| Lint before synthesis rebuild | Phase B precedes Phase C | Synthesis encodes the wiki state; that state must be clean before it's summarized |
| Synthesis is a separate command | `synthesize_wiki`, not part of run_ingest | It depends on the human review gate — can't be wired into the automated pipeline |
| LDP remains independent extraction | Comprehend→Plan is a prior, not a constraint | Comprehend misses details; LDP catches everything; plan just improves LDP's decisions |
| Strategy pages have two layers | Prose body (human) + `synthesis:` section (machine) | Prose is the human artifact; structured section is what `synthesize_wiki` reads and writes |

---

## Future Directions

**Multi-city replication (Grapevine horizon):**
When a second city is ingested, the synthesis hierarchy gets a fourth level: a cross-city digest that answers "what does Ann Arbor know about this initiative type that Denver should read before we explain theirs?" The 7 A2Zero strategies become one city's community structure within a larger multi-city graph. Each city has its own L0/L1/L2 hierarchy; a shared L3 enables cross-city synthesis.

**Embedding-based retrieval at scale:**
The `retrieve-for-context` field in the integration plan currently lists entities identified by the holistic Comprehend pass. As the wiki grows beyond 1,000 pages, the Comprehend pass will miss more entities. The upgrade path: embed all entity pages, embed the incoming source, retrieve top-K by cosine similarity to supplement what the Comprehend pass identifies. The integration plan then has two sources: LLM-identified (holistic read) + embedding-retrieved (semantic similarity). The two are merged before the LDP Write pass.

**Contradiction tracking:**
The integration plan's `contradicts` field is defined but not yet surfaced anywhere in the wiki. Future: contradictions that survive lint review should be written to `wiki/contradictions/` as dedicated pages, per the schema already defined in CLAUDE.md.

---

## Implementation Order

1. **`synthesize_wiki` command** — reads L1 strategy pages, writes digest.md (Phase C command)
2. **Digest injection into Comprehend pass** — inject digest.md into holistic synthesizer before source read
3. **Split holistic synthesizer into Comprehend + Plan** — produce structured integration plan, use it to drive targeted LDP retrieval
4. **Strategy page structured section** — add `synthesis:` frontmatter block, wire into synthesize_wiki

See `docs/superpowers/plans/` for implementation plans as they're written per step.
