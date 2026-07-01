# Comprehend → Plan → Write

## How `wiki/digest.md` Gets Wired Into the Ingest Pipeline

*Spec: 2026-06-29. Extends [knowledge-synthesis-architecture.md](./knowledge-synthesis-architecture.md). Pre-implementation. Branch: `feat/digest-injection`.*

---

## The Problem This Solves

The holistic synthesizer at the front of every ingest does two things in one LLM call: it reads the full source AND writes the strategy bodies, overview, and entity stubs. This conflates *understanding* with *writing* — the LLM treats the new source as if it's the only source the wiki has ever seen.

The Year 1 and Year 2 ingests both produced visible fragmentation as a result:
- Bryant Neighborhood Decarbonization fractured across 3 disconnected pages
- Sustainable Energy Utility fractured similarly
- Solarize Ann Arbor produced two near-duplicate pages

The alias registry caught some of this at write-time (Pass 1.5), and the lint cycle caught more during human review. But the *fundamental* problem is that the LLM responsible for the integration decision never sees what the wiki already knows. We compensated downstream; we did not solve upstream.

The architecture doc (`knowledge-synthesis-architecture.md`) prescribed a fix: split the holistic synthesizer into two distinct LLM calls — **Comprehend** (reads digest + source, produces a structured integration plan) and **Write** (the existing Writer→Evaluator→Editor loop, now guided by the plan). The LDP chunk-by-chunk extraction (Pass 2) then operates against the same plan, with retrieval of specific entity page bodies for the entities the plan flagged.

`synthesize_wiki` + the validation loop (built in the prior session) produce the clean, trustworthy `digest.md` that this architecture depends on. Without those, injecting a digest full of ghost references would just propagate hallucinations into every future ingest. With them, the digest is safe to inject. This spec wires it in.

---

## The Architecture

```
                  ┌─────────────────────────┐
                  │  wiki/digest.md         │
                  │  (L2 from Phase C)      │
                  └──────────┬──────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
┌───────────────────────┐      ┌─────────────────────────┐
│  Pass 1A: Comprehend  │      │  Pass 2: LDP (existing) │
│  (NEW LLM call)       │      │  now guided by plan     │
│  source + digest      │      │  + retrieve-for-context │
│  → integration plan   │      │  bodies                 │
└──────────┬────────────┘      └─────────────────────────┘
           │                              ▲
           │  plan (JSON)                 │
           │  persisted to                │  plan read from disk
           │  wiki/integration-plans/     │
           ▼                              │
┌────────────────────────────────┐        │
│  Pass 1B: Write                │        │
│  Writer → Evaluator → Editor   │────────┘
│  (existing loop)               │
│  now sees plan + digest        │
│  + source                      │
└────────────────────────────────┘
```

**Call A — Comprehend.** A new LLM call inserted at the start of Pass 1. Reads `wiki/digest.md` plus the new source. Output: a structured JSON integration plan (schema below). Written to `wiki/integration-plans/<source-uuid>.json` for audit trail and for Pass 2 to consume.

**Call B — Write.** The existing Writer→Evaluator→Editor loop in `holistic_synthesizer.py`. Now its user-message context includes the integration plan in addition to the source. The Writer is no longer naive — it has both the digest's compressed prior over the wiki and the Comprehend pass's verdict on how this source maps to that prior. The prompt structure of the Writer/Evaluator/Editor does not change; only the input context expands.

**Pass 2 — LDP extraction.** Reads the integration plan from disk at startup. For each chunk, the LLM prompt includes:
- The plan's `extends` and `new-entities` lists (what to expect)
- The page bodies for entities in `retrieve-for-context` (what to integrate against)
- The chunk text itself

The LDP still performs bottom-up extraction. The plan is a prior, not a constraint — if LDP finds an entity not in the plan, it creates a page as before. But the plan tells LDP what to look for, which entities to update vs. create, and which existing content to integrate against. This is where contradictions get detected (LDP sees both the new claim and the existing page body in one context).

---

## The Integration Plan Schema

Persisted to `wiki/integration-plans/<source-uuid>.json`. Five fields, each carrying its weight:

```json
{
  "source-uuid": "a2zero-year3",
  "generated-at": "2026-07-15T10:34:00Z",
  "digest-rebuilt": "2026-06-29",

  "strategies-touched": [
    "strategies/strategy-1-renewable-grid",
    "strategies/strategy-3-building-efficiency"
  ],

  "extends": [
    {
      "slug": "initiatives/solarize-ann-arbor",
      "new-data": "Year 3 installation totals, new participating zip codes, LMI uptake metrics"
    },
    {
      "slug": "initiatives/sustainable-energy-utility",
      "new-data": "Capitalization update, governance structure finalization"
    }
  ],

  "new-entities": [
    {
      "slug": "initiatives/electrification-expo-2023",
      "type": "initiative",
      "title": "Electrification Expo 2023",
      "rationale": "Multi-stakeholder event referenced 5+ times across pp 12-18"
    }
  ],

  "retrieve-for-context": [
    "initiatives/solarize-ann-arbor",
    "initiatives/sustainable-energy-utility",
    "initiatives/bryant-neighborhood-decarbonization"
  ],

  "theme-connections": [
    "Source frames Bryant decarbonization as proof-of-concept for citywide rollout — connects Strategy 2 (electrification) and Strategy 7 (equity)",
    "Grid capacity expansion now explicitly tied to building electrification timeline (cross-cuts Strategy 1 and 2)"
  ]
}
```

**Per-field semantics:**

| Field | Drives | Downstream consumer |
|---|---|---|
| `strategies-touched` | Bounds `synthesize_wiki` rebuild scope | Future `synthesize_wiki --strategies-touched-from <plan>` invocation |
| `extends` | Tells LDP which existing entities expect new data | LDP chunk extraction loop |
| `new-entities` | Pre-declares pages LDP should create | LDP + Pass 1.5 alias resolution |
| `retrieve-for-context` | Selects entity bodies to load as context | LDP chunk prompt assembly |
| `theme-connections` | Surfaces cross-strategy patterns for humans | `review-queue.md` annotations, future synthesis prompts |

**Contradiction detection is explicitly NOT a Comprehend responsibility.** It happens downstream in LDP, where the Write pass sees both the new source claim AND the existing page body and can spot conflicts directly. The arch doc proposed `confirms` and `contradicts` fields in the plan, but they require the Comprehend pass to know specific factual claims about entities — which the digest deliberately compresses out. Pushing contradiction-detection to LDP is structurally more robust.

---

## How the Plan Flows Through Each Pass

### Pass 1A — Comprehend (new)

**Input context:**
- `wiki/digest.md` (~4-6k tokens) — as a `cache_control` block
- The full source document (~10-50k tokens) — as a `cache_control` block
- A user message: "Produce the integration plan as JSON conforming to the schema."

**Output:** Integration plan JSON. Passed through the validator (reusing `pipeline/synthesis_validation.py` machinery) to strip ghost slugs from `extends` and `retrieve-for-context`, then written to `wiki/integration-plans/<source-uuid>.json` before Pass 1B begins.

**Failure modes — two distinct cases:**

1. **No digest exists** (first ingest of a wiki with zero prior sources): graceful fallback. Skip Comprehend entirely, write an empty plan, let Pass 1B and Pass 2 run in current naive behavior. The first source produces the seed digest; subsequent ingests benefit from Comprehend.

2. **Digest exists but Comprehend LLM call fails** (API error, malformed JSON): **hard fail.** Halt the ingest before any downstream tokens are spent. The user fixes the cause (rerun with different model, retry on API outage, debug the source) and re-invokes. Rationale: the wiki has a digest, which means we're past the seed phase. Spending tokens on Pass 1B Writer + Pass 2 LDP after losing the integration benefit is wasteful; better to fail fast and retry cleanly.

### Pass 1B — Plan-Guided Write (existing Writer→Evaluator→Editor, now informed)

The existing `synthesize_source()` function in `holistic_synthesizer.py` keeps its three-call loop. The change is to its input context. The current `integration_block` (which injects raw strategy bodies) gets replaced with:

```
[INTEGRATION PLAN — read this first]
<plan JSON>

[WIKI DIGEST — current state of the wiki]
<digest.md content>

[FULL DOCUMENT]
<source text>
```

The Writer's system prompt gets a small addition explaining that the plan represents the integration verdict and should be used to guide which strategies to extend, which entities to create new, and which to update vs. duplicate. Evaluator and Editor inherit the same context.

**Token impact:** Net reduction vs. today. Current `integration_block` injects all strategy bodies verbatim (~5-15k tokens depending on wiki growth). The digest is ~4-6k tokens regardless of wiki size, plus a small (~500 token) plan. Per-source cost goes *down* even as the wiki scales.

### Pass 2 — Plan-Guided LDP

`pipeline/ldp.py` reads `wiki/integration-plans/<source-uuid>.json` at the start of `process_long_document()`. For each chunk:

**Input context for the chunk extraction LLM:**
- The integration plan (cache_control'd, sent once per ingest run not per chunk)
- The bodies of entity pages in `retrieve-for-context` (also cache_control'd, sent once per ingest)
- The current chunk text

The plan's `extends` list tells the per-chunk LLM "if you see content about these entities, integrate into the loaded page bodies rather than creating new pages." The `new-entities` list tells it "creating these is sanctioned; don't second-guess."

**Explicit invariant:** if LDP finds an entity that is neither in `extends` nor in `new-entities`, it still creates a page exactly as it does today. The plan is a prior, not a constraint. The Comprehend pass cannot anticipate every entity buried in tables, appendices, or vote records — LDP's bottom-up exhaustive extraction remains the ground truth.

### How `retrieve-for-context` differs from today's behavior

Today, the per-chunk extraction LLM (`extract_wiki_pages_from_chunk` in `pipeline/wiki_writer.py:368`) receives only the chunk text and a section context header. It sees **zero existing wiki content** at extraction time. When the resulting extraction targets an entity that already has a page, a *separate* downstream LLM call (`_merge_pages`) reconciles the new body against the existing one — a damage-control reconciliation after the fact.

`retrieve-for-context` shifts this from damage control to prevention. By pre-loading the bodies of entities the plan flagged into the chunk extraction prompt itself, the LLM writes its extraction *in awareness* of prior content from the start:
- Less duplicate language to clean up downstream
- Focus on net-new information rather than re-stating known facts
- Consistent terminology and framing across ingests
- Fewer cases where `_merge_pages` has to reconcile genuinely conflicting writeups

The `_merge_pages` step still exists as a safety net for cases LDP didn't see coming, but the plan-driven retrieval is the new front-line integration mechanism.

**Cache strategy:** the digest, plan, and retrieved entity bodies are all stable across all chunks of a single ingest. They go in one large cached prefix that's reused across every chunk LLM call. This is the same `cache_control` pattern already used in `wiki_pages.py` for the `cached_document_block`.

---

## First-Ingest Fallback

When `wiki/digest.md` does not exist (clean wiki, first source ingest), the Comprehend pass is skipped entirely. An empty plan is written, Pass 1B and Pass 2 fall back to current naive behavior, and the first source ingests exactly as it does today. The synthesis layer produces the seed digest at the end of that cycle; the second ingest is the first one to benefit from Comprehend/Plan.

This is the same graceful-degradation pattern used by `enrich_strategy_links` and other one-time passes.

---

## Where the Code Lives

A new module: `pipeline/comprehend.py`. Public surface:

```python
def build_integration_plan(
    source_content: str,
    source_uuid: str,
    digest_content: str | None,
    run_date: str,
) -> dict:
    """Comprehend LLM call: read digest + source, produce structured integration plan.
    Returns an empty plan dict if digest_content is None (first ingest)."""

def write_integration_plan(plan: dict, plans_dir: str) -> str:
    """Write plan JSON to wiki/integration-plans/<source-uuid>.json. Returns path."""

def load_integration_plan(plans_dir: str, source_uuid: str) -> dict:
    """Load plan from disk. Returns empty plan if file missing (graceful fallback)."""

def empty_plan() -> dict:
    """Return the empty-plan skeleton used as fallback."""
```

Changes to existing modules:

| File | Change |
|------|--------|
| `pipeline/holistic_synthesizer.py` | Replace `integration_block` (lines 341-352) with plan + digest injection; call `build_integration_plan` before the Writer call |
| `pipeline/run_ingest.py` | Pass `wiki_root` deeply enough that Comprehend can load `digest.md`; expose `--skip-comprehend` flag for testing/debugging |
| `pipeline/ldp.py` | Load integration plan at start of `process_long_document()`; thread plan + retrieved entity bodies into each chunk's prompt |
| `pipeline/wiki_writer.py` | Same chunk-extraction context expansion as `ldp.py` (these two share the chunk loop) |
| `wiki/integration-plans/.gitkeep` | New directory for plan artifacts |
| `wiki/integration-plans/README.md` | One-paragraph explainer for humans browsing the vault |

The `integration-plans/` directory is committed (the plans are part of the audit trail), but git-gitkeep handles the bootstrap.

---

## Token and Cost Impact

**Per ingest, vs. current:**

| Call | Today | After |
|---|---|---|
| Pass 1 Writer | Source + all strategy bodies (~5-15k integration) | Source + digest + plan (~5k integration, smaller) |
| Pass 1 Evaluator | Same as Writer | Same as Writer |
| Pass 1 Editor | Same as Writer | Same as Writer |
| **Pass 1A Comprehend** | — | Source + digest (~10-50k source + 5k digest) |
| Pass 2 LDP (per chunk × N chunks) | Chunk text only | Chunk text + plan + retrieved bodies (cache_control'd) |

Net effect: **+1 LLM call per ingest** (Comprehend), **smaller integration_block in Pass 1** (digest replaces full strategy bodies), **bigger but cached prefix in Pass 2** (plan + retrieved bodies). Total token cost goes up by roughly the size of one digest read; throughput should be unchanged because Comprehend runs once per ingest and the rest is caching.

Critically: the per-ingest cost stops growing with wiki size. Today, every additional strategy body in the wiki bloats the Pass 1 context for every future ingest. After this change, the digest is the constant-size summary regardless of wiki growth.

---

## Open Questions

These need explicit decisions before implementation.

1. **Model selection for Comprehend.** Same as `synthesis` (Claude Sonnet / GPT-5.4), or a stronger model since this is the most consequential single LLM call in the pipeline? **Recommendation:** start with the existing `synthesis` model_hint. Add a dedicated `comprehend` hint if quality issues emerge.

2. **Plan versioning on re-ingest.** If the same source gets re-ingested (e.g., after fixing a prepared/ source file), does the new plan overwrite the old one, or do we keep both? **Recommendation:** overwrite. The plan reflects the *current* integration decision; old plans aren't useful artifacts. Git history preserves the diff if anyone needs it.

3. **`retrieve-for-context` size cap.** What if the Comprehend pass asks LDP to load too many entity bodies? **Recommendation:** cap by **token budget**, not entity count. Default: 30k tokens worth of retrieved bodies (roughly 10-30 pages at typical sizes). Prioritization when budget is exceeded:
    1. Entities also listed in `extends` (Comprehend explicitly expects new data for these)
    2. Then by frequency of mention across the plan's other fields (`theme-connections`, etc.)
    3. Drop overflow silently (long-tail entities fall back to today's `_merge_pages` behavior)

    All retrieved bodies go into **a single cached prefix shared by every chunk in the ingest** — see "Cache strategy" in the per-pass walkthrough. The pre-loaded context is paid for once per ingest, not once per chunk.

4. **Plan validation.** The Comprehend LLM emits slugs in `extends` and `retrieve-for-context`. Some may be ghosts (same problem we just solved for synthesis). **Recommendation:** reuse `validate_synthesis` machinery from `synthesis_validation.py` — pass the plan through a Validator before writing it to disk and before passing it to LDP. Same pattern, same module, no new code.

5. **What happens when LDP encounters an entity in `extends` whose page body wasn't pre-loaded?** Edge case: Comprehend says "extends solarize-ann-arbor" but doesn't put it in `retrieve-for-context`. LDP can either (a) silently fall back to today's behavior or (b) load the page lazily. **Recommendation:** option (a). If Comprehend made a mistake, it's a soft failure — LDP still works.

6. **Should the plan also drive `synthesize_wiki --strategies-touched-from <plan>`?** Currently `synthesize_wiki` regenerates the L1 synthesis blocks for all 7 strategies on every invocation. The plan's `strategies-touched` is a natural signal to narrow that — only re-synthesize the strategies the new source actually affected. **Recommendation:** out of scope for this PR. Add a follow-on issue. Don't bundle.

7. **Telemetry.** Should we log per-ingest stats (Comprehend duration, number of extends/new-entities, plan size in tokens) somewhere durable? **Recommendation:** yes — append a JSON line to `wiki/meta/ingest-stats.jsonl`. Cheap to write, useful for trend analysis as the wiki scales.

8. **Test strategy.** The new Comprehend module is testable with mocked LLM calls (cheap). The integration changes to `holistic_synthesizer.py` and `ldp.py` are harder — they have many existing tests that mock specific prompt structures. **Recommendation:** add unit tests for `pipeline/comprehend.py` covering plan generation, schema validation, fallback. Update existing `tests/test_holistic_synthesizer.py` and `tests/test_ldp.py` to mock the new plan-aware prompt assembly. One optional integration test gated on `ANTHROPIC_API_KEY`.

---

## When Dynamic Per-Chunk Retrieval Would Be the Right Call

This spec uses a **pre-loaded cached prefix** — Comprehend identifies the top entities, their bodies are loaded once per ingest, and every chunk's extraction LLM sees the same reference context. An alternative architecture would do **dynamic per-chunk retrieval**: read chunk → identify entities mentioned → search wiki → load matching pages → integrate. Documenting why we're not building that *yet*:

**The dynamic approach becomes the right call when:**

1. **Wiki scale exceeds Comprehend's holistic-read ceiling.** Today the wiki has ~360 entities. The holistic Comprehend pass reliably identifies the major entities a source will touch. As the wiki grows past ~1,000-2,000 entities, Comprehend's recall drops — it can't hold the whole entity universe in attention. At that point, per-chunk embedding-based retrieval becomes worth its cost because it catches what Comprehend missed.

2. **Sources span many strategies sparsely.** The pre-loaded prefix optimizes for a source that talks deeply about a focused set of entities. A source that name-drops 80 entities once each would either blow the token budget or get most entities dropped from `retrieve-for-context`. Dynamic retrieval handles sparse-many-entity sources better.

3. **The wiki develops dense cross-references that the digest can't compress.** Today the digest captures the L1 strategy synthesis adequately. If we ever need fine-grained entity-to-entity relationships in context (e.g., for contradiction detection that requires comparing specific claims across many pages), pre-loaded won't carry enough detail.

**Why we're not building it for this PR:**

- **Caching economics.** Pre-loaded prefix is sent once and cached for every chunk in the ingest. Dynamic retrieval breaks caching — each chunk gets a different prefix, every chunk pays full rate. At our current scale this is a 2-5× cost difference per ingest.
- **Per-chunk latency.** Dynamic retrieval requires two LLM calls per chunk (extract entity names → retrieve → integrate). Pre-loaded is one call per chunk.
- **The "noise" concern doesn't actually bite at current context lengths.** Long-context LLMs handle irrelevant reference material well. The system prompt can explicitly say "Use these reference pages only when the chunk discusses the same entity."
- **We have a backstop for missed entities.** Long-tail entities not in `retrieve-for-context` still get the existing `_merge_pages` reconciliation when their pages already have content. The pre-loaded approach handles the top N; the existing merge mechanism handles the long tail.

**Migration path:** If `synthesis-ghosts.log` or human review shows that integration quality degrades as the wiki grows (lots of cases where Comprehend missed an entity that the source actually does extend), that's the signal to add embedding-based dynamic retrieval as a *supplement* to `retrieve-for-context` — not a replacement.

---

## Out of Scope

To keep this change focused and reviewable:

- **`synthesize_wiki --strategies-touched-from <plan>`** — consume the plan to bound rebuild scope. Natural follow-on, separate PR.
- **Embedding-based `retrieve-for-context` supplementation.** The arch doc anticipates that as the wiki grows beyond 1,000 pages, the Comprehend pass will miss entities. Embedding-based retrieval can supplement. Not needed until then.
- **Plan-driven `review-queue.md` annotations.** `theme-connections` could become structured review-queue entries automatically. Useful but distinct work.
- **Changes to the existing Writer→Evaluator→Editor prompt structure.** This spec changes their *input context*, not their prompts. Prompt redesign is a separate concern.
- **Changes to Phase B (lint) or Phase C (synthesize_wiki).** Both consume plan artifacts (eventually) but neither produces them. Out of scope here.
