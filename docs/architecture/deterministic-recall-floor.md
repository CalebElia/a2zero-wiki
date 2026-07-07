# Deterministic Recall Floor

## Closing the Silent-Staleness Gap

*Spec: 2026-07-06. Extends [comprehend-plan-write.md](./comprehend-plan-write.md) and [knowledge-synthesis-architecture.md](./knowledge-synthesis-architecture.md). Implemented, branch `feat/deterministic-recall`.*

---

## The Problem This Solves

The Comprehend/Plan/Write architecture (`comprehend-plan-write.md`) fixed the fragmentation problem — the Writer no longer treats each new source as if it's the only one the wiki has ever seen. But a second, quieter failure mode was hiding behind it: **recall**, not comprehension.

### The verified failure chain

The Year 5 annual-report ingest exposed the gap end to end:

- `wiki/digest.md` named 76 of 497 entities in the wiki — **15.3% coverage**. The digest is a deliberately lossy top-N compression (that's its job at L2), but every downstream pass inherited that compression as its entire prior over "what the wiki already knows."
- The Comprehend pass, reading only that digest plus the new source, produced an integration plan covering 36 slugs.
- `initiatives/bryant-neighborhood-decarbonization` — mentioned **8 times** in the Year 5 source — appeared in neither the digest's top-N nor the Comprehend plan. It was invisible to Pass 1B's `stub_pages` reasoning and invisible to Pass 2's `extends`/`retrieve-for-context` lists.
- The page was silently never updated. No error, no warning, no review-queue entry. The only trace was the ingest log looking normal.

### The root principle

Every recall pathway in the pre-fix pipeline was **LLM judgment, chained three deep**: digest top-N compression → Comprehend plan selection → Writer's own `stub_pages` reasoning. Each stage is a probabilistic filter, and probabilistic filters compound multiplicatively, not additively — a 70%-recall stage feeding another 70%-recall stage yields roughly 49% end-to-end recall, with no stage aware that the ones before it already dropped information.

Failures were not uniform across the entity graph. They concentrated on **mid-tier entities**: important enough to be mentioned repeatedly in a new source, not important enough to survive the digest's top-N cut or catch an LLM's attention against a 50k-token document. And the failure was **self-reinforcing** — an entity dropped from one ingest's plan is even less likely to appear in the next digest rebuild (fewer citations, less synthesis weight), making it more likely to drop again.

---

## The Principle

**Comprehension is LLM work; recall is mechanical.**

Deciding *how a new fact relates to existing knowledge* — is this an extension, a contradiction, a new entity, a duplicate under another name — genuinely requires judgment, and that's what Comprehend and the Writer are for. But deciding *whether a string that names an existing entity appears in a new document* requires no judgment at all. It is a lookup. Routing that question through an LLM's finite attention was the bug: it added no value and introduced exactly the loss the recall floor exists to eliminate.

The fix does not replace Comprehend. It adds a deterministic backstop underneath it that guarantees a floor: every entity the wiki already has a page for, and that the new source names by any known surface form, is surfaced to the pipeline — independent of digest compression, independent of Comprehend's judgment, independent of the Writer's attention budget.

---

## The Mechanism As Built

### 1. The name index (`build_entity_name_index`)

A single dict — `{lowercased name: canonical slug}` — built fresh at the start of every ingest from three sources, in override order (aliases win over generated titles):

1. **Computed verb-prefix variants.** CAP-2020 titles carry a leading verb ("Support Aging in Place Efficiently") that later annual reports drop ("Aging in Place Efficiently"). Both forms are computed at index-build time from a fixed list of prefixes (`Support`, `Expand`, `Launch`, `Promote`, ... ). The alias registry is deliberately **not** polluted with these — they're mechanical derivations, not curated canonical knowledge.
2. **Page titles**, read from frontmatter (or derived from the filename if the title field is missing).
3. **Registry aliases** (`registry/entity_aliases.json`), mapped to their canonical slug — but only if that canonical page actually exists on disk.

Names shorter than 4 characters are dropped even with boundary matching (acronym noise — bare "SEU" would false-positive constantly; the registry's longer variants like "the SEU" or "Ann Arbor SEU" still reach the scanner).

**The paren-suffix lesson.** The first implementation used `\b` word-boundary regex on both ends of each name. That's wrong for roughly 6% of real indexed names (39 of 653 in the production index) — anything ending in a non-word character, most commonly parenthetical acronyms like "... (MDOT)". `\b` after a literal `)` requires the *next* character to be a word character to fire, which inverts the actual intent and silently never matches those names in ordinary prose (a name at the end of a sentence, followed by a space or period, never matches). The fix replaces `\b` with lookarounds that express the real requirement directly: `(?<!\w)` before the name, `(?!\w)` after — "not embedded inside a longer word," with no assumption about what character comes next.

### 2. The scan (`scan_source_for_known_entities`)

Single-pass, not one `findall` per name. All indexed names are compiled into one alternation pattern, **longest name first** (so "Ann Arbor Sustainable Energy Utility" matches before the shorter "Sustainable Energy Utility" would eat part of it), and the whitespace-normalized source text is scanned once. A naive per-name loop measured ~2s against the largest real source (cap-2020, 278KB); the single-pass alternation runs in 0.31s against the same file with a 653-name index — a fixed cost paid once per ingest regardless of index growth, not O(names × text).

Output: `{slug: {"matched-names": [...], "mentions": int}}` for every entity the source names at least once.

### 3. Plan augmentation (`augment_integration_plan`)

Folds scan hits into the Comprehend plan **before** it's persisted or consumed downstream:

- Slugs already covered by the LLM (`extends`, `new-entities`, or already in `retrieve-for-context`) are left alone — the scan is a recall floor, not an override of LLM judgment.
- Everything else lands in a new `scan-flagged` list, explicitly separate from `extends`, carrying `matched-names` and `mentions` for audit-trail provenance ("mechanical, not LLM judgment" is visible in `integration-plans/<uuid>.json` itself).
- The same missing slugs are appended to `retrieve-for-context`, ordered by mention count, so they compete for body-retrieval budget on the same terms as everything else — but always *after* the LLM-flagged entries, which keep first claim.

### 4. Awareness vs. bodies — the two-tier budget (decision 1a)

Two distinct things ride the plan into the chunk prompts, and they are capped completely differently:

- **Awareness** — the `scan-flagged` entries themselves (~80 chars each: slug, matched names, mention count) — is **never capped**. It rides the plan JSON into every chunk prompt uncapped. This alone prevents the Bryant failure class: even with no page body loaded, Pass 2 knows the correct existing slug to target, and `write_or_append_page` appends the new facts under a source marker instead of silently doing nothing or creating a duplicate.
- **Bodies** — the full page text for `retrieve-for-context` slugs — is governed by `RETRIEVE_TOKEN_BUDGET`, raised from 30,000 to **60,000 tokens**. Year 5 telemetry showed 14k tokens used by 15 LLM-flagged entities alone; a ~50-entity scan addition at ~2k chars average adds roughly another 25k tokens, landing around 39k combined — comfortably inside 60k with headroom for larger sources. Uncapping bodies entirely was rejected: that recreates the naive full-wiki-injection approach the architecture doc already rejected for cost and context-degradation reasons, and multiplying it across every chunk prompt (rather than once per ingest) would make it far worse, not better.

Any residual drop (a pathological source matching 100+ entities) is never silent: it's (a) printed at ingest time as a loud warning, (b) recorded in the persisted plan itself as `context-dropped: [slugs]`, and (c) the first thing the staleness lint cross-checks. The design bets on getting the budget right up front from real telemetry; the lint exists to verify only the knowingly-deprioritized tail, not to catch a design that was wrong from the start.

### 5. Per-chunk scoped body injection (decision 1b)

The LDP chunk loop re-runs the scanner against **each chunk's own text** and injects only the bodies of entities that chunk actually mentions, intersected with the doc-level `retrieved_bodies` already loaded under the 60k budget.

This is a deliberate scope split by *function*, not an accident of implementation convenience:

- **Bodies are integration material** — heavy (a full page can run several KB), and only useful when the chunk is actually discussing that entity. Doc-wide injection would multiply every body across all ~12 chunk prompts (up to ~720k input tokens per ingest at the 60k budget, most of it irrelevant to any given chunk — the context-rot risk the architecture doc already warned about). The alternative of per-entity sequential retrieval calls was also rejected: it inverts the cost structure (each call re-pays the system prompt and full chunk text — ~660k tokens for 120 calls in the Year 5 shape) and produces divergent phrasings of the same co-occurring facts with no cross-reference consistency. It also hands retrieval initiative back to LLM judgment mid-extraction — exactly the failure class this plan eliminates.
- Per-chunk deterministic scoping keeps single-shot chunk calls, batches co-occurring facts into one coherent write, and preserves the reproducible audit trail, landing around 60–150k total body tokens per ingest at maximal relevance density.
- The small-document path (one chunk = the whole document) is unaffected — scoping is a no-op there.

### 6. The plan block stays doc-wide (decision 1c)

The `[INTEGRATION PLAN]` block — including the uncapped `scan-flagged` awareness entries — is **not** per-chunk scoped, even though bodies are. This is the same "scope by function" split from the other direction: plan entries are *orientation* material (small, ~3k tokens total, and true for the whole document, not one chunk), not *integration* material.

Doc-wide plan entries let each chunk resolve boundary-bleeding references ("this funding," "the program above") that span chunk edges, suppress duplicate page creation for entities the plan already routed elsewhere, and — the decisive reason — keep awareness unconditional. If the per-chunk scanner misses a paraphrased mention in one chunk, that chunk loses the *body* but keeps the *awareness* entry, so extraction still targets the right slug instead of creating a duplicate. Scoping the plan block too would make both layers conditional on the same string-matching step, recreating per-chunk invisibility at a different layer.

### 7. Prompt ordering is a cache constraint, not a style choice (decision 1d)

Chunk prompts assemble stable-prefix-first: `system → [INTEGRATION PLAN] → KNOWN ENTITIES context` (byte-identical across every chunk call in one ingest) *then* `[RETRIEVED ENTITY PAGES] (per-chunk, varies) → [SECTION CONTENT]`. Anthropic's explicit `cache_control` and Azure OpenAI's automatic prefix caching both key off identical leading byte sequences (above ~1024 tokens) — the repeated doc-wide block is amortized to a fraction of nominal cost across ~12 chunk calls per ingest, but only if nothing chunk-specific precedes it in the prompt. This is treated as load-bearing, not incidental: reordering it would silently blow up caching without changing correctness, an easy regression to introduce and hard to notice without watching token costs directly.

### 8. Staleness lint — the retrieval-method-independent outcome instrument

`--staleness` is a separate lint mode (not folded into `--structural`, because it's ingest-cycle-scoped — it needs a source UUID — while structural is state-scoped). It re-runs the exact same scanner against the ingested source post-hoc and files a `STALE_ENTITY` finding for every matched entity whose page gained no citation to that source.

This is deliberately the same mechanism as the recall floor itself, run after the fact: it doesn't matter *how* an entity should have been surfaced (Comprehend, scan-flagged, or Writer judgment) — if the source names it and the page shows no trace of the new source, that's the observable failure, independent of which upstream stage should have caught it. Findings carry a `[context-dropped at ingest]` annotation when the slug was in that ingest's recorded `context-dropped` list, so human triage sees the knowingly-deprioritized tail first, distinct from a genuine miss. Findings are informational only — a mention can legitimately go uncited when a source simply repeats an already-recorded fact — so there is no auto-fix; a human triages via the standard `review-queue.md` flow.

### 9. Writer link-preservation rule (Task 121, same root cause)

A smaller, related fix rides the same plan: the Writer's system prompt now requires it to (a) preserve every `[[...]]` wikilink already present in the existing Progress Synthesis text it's shown, rather than dropping links on paraphrase, and (b) link first mentions of any entity listed in the plan (`extends`, `retrieve-for-context`, or `scan-flagged`) using the plan's slug — the `stub_pages` linking rule only ever covered genuinely new entities the Writer itself creates. Both are instances of the same underlying gap: LLM output silently regressing wiki structure that a deterministic source already knew the answer to.

---

## Design Decisions

| # | Decision | Why |
|---|---|---|
| 1 | Scan hits go to `plan["scan-flagged"]` + `plan["retrieve-for-context"]`, never `plan["extends"]` | Keeps mechanical provenance distinct from LLM judgment in the audit trail; preserves `load_retrieved_bodies()`'s existing extends-first priority order |
| 1a | Awareness (scan-flagged entries) is never capped; only bodies are, under `RETRIEVE_TOKEN_BUDGET`; drops are loud, recorded, budgeted | Prevents invisibility even under budget pressure; uncapping bodies entirely would recreate the rejected full-wiki-injection cost/context-rot problem, multiplied per chunk |
| 1b | Retrieved bodies are injected per-chunk scoped (re-scanned per chunk, intersected with loaded bodies), not doc-wide | Doc-wide injection multiplies irrelevant body text ~12× per ingest; per-entity sequential calls invert cost and break cross-reference consistency; per-chunk scoping keeps single-shot calls with maximal relevance density |
| 1c | The `[INTEGRATION PLAN]` block (including scan-flagged) stays doc-wide, never per-chunk scoped | Scope by function: plan entries are small, document-global orientation material; scoping them too would make awareness conditional on the same string-matching step bodies are, recreating invisibility |
| 1d | Chunk prompts assemble stable-prefix-first (`system → plan → known entities` then per-chunk body/section content) | Anthropic/Azure prefix caching keys on identical leading bytes; reordering silently destroys the ~12x-per-ingest cache amortization without any visible correctness change |
| 2 | Name index is computed at build time, not stored; verb-prefix variants generated on the fly | `entity_aliases.json` stays a curated canonical-resolution registry; mechanical derivations don't belong mixed in with curated knowledge |
| 3 | Boundary (not naive `\b`) matching, case-insensitive, minimum name length 4 | Lookarounds `(?<!\w)...(?!\w)` correctly match names ending in non-word characters (parenthetical acronyms); length floor avoids acronym false-positive noise |
| 4 | `--staleness` is a separate CLI mode, not part of `--structural` | Ingest-cycle-scoped (needs a source UUID) vs. structural's state-scoped model; defaults to the last line of `meta/ingest-stats.jsonl` when no UUID given |
| 5 | Findings are informational, human-triaged, no auto-fix | A mention can legitimately go uncited (source repeats an old fact); auto-fixing would risk fabricating citations |

---

## Real-Data Verification

Measured against the already-ingested wiki and the recorded Year 5 integration plan, no re-ingest and no LLM calls:

- **653-name index** built from the full wiki (titles + verb-prefix variants + registry aliases).
- Retroactive scan of the Year 5 annual-report source against that index matched **91 entities** total; of those, **72 would have been `scan-flagged`** beyond what the recorded Comprehend plan already covered — including `initiatives/bryant-neighborhood-decarbonization`, confirming the regression this plan targets is exactly what the scan catches.
- Combined body-retrieval set (Comprehend's `retrieve-for-context` + the scan-flagged additions): **87 slugs, 137,541 characters, ≈34,000 tokens** — comfortably inside the 60k-token budget with zero drops (`context-dropped` would be empty for this real case).
- Scan runtime: **0.31 seconds** against the largest real source in the wiki (`wiki/sources/cap/cap-2020.md`, 278KB) — confirming the single-pass alternation fix scales acceptably at current wiki size.

---

## Appendix: Embeddings Deferral

Embedding-based retrieval is explicitly out of scope for this work, deferred until one of three concrete triggers fires (not a vague "eventually," per the plan's design intent):

1. **`STALE_ENTITY` review reveals recurring *paraphrase-only* mentions** the string scan structurally cannot see — an entity referred to only by description, never by any indexed name or alias.
2. **New source types with informal language land** — council transcripts (the expected first case) name entities far more loosely than CAP-2020's structured prose and the annual reports' consistent titling.
3. **The wiki exceeds ~1,000 entity pages** — the point at which Comprehend's holistic read of the digest (already a compressed summary) stops reliably orienting even a human reader, let alone an LLM's attention, and per-chunk retrieval starts winning on recall even without the caching advantage the current pre-loaded approach has.

**When triggered, the validation approach is:**

- **Citation-derived gold sets for offline recall@K evals.** Existing wikilink citations in the wiki's own body text are ground truth — pages already known to genuinely reference each other. Recall@K against that gold set, offline, before ever wiring embeddings into a live ingest.
- **Embeddings propose, LLM+HITL dispose.** Same pattern as everywhere else in this pipeline (semantic lint, synthesis validation): a deterministic/statistical mechanism proposes candidates, and a human or an LLM-with-human-review decides. Embeddings never write directly.
- **Index rebuilt in Phase C, alongside the digest.** Not a separate maintenance job — embedding rebuild rides the same synthesis cycle that already rebuilds `digest.md`, so there's one point in the ingest lifecycle where "the wiki's summarized state" gets regenerated, not two independently-drifting caches.
- **Whole-page embedding, no chunking layer.** Entity pages are already small, focused units (that's the point of the L0 page-per-entity design) — adding a sub-page chunking layer on top would reintroduce the same chunk-boundary problems this plan just solved for LDP extraction, for no benefit at the entity-page granularity.
- **Staleness lint remains the end-to-end instrument** regardless of retrieval mechanism — it validates outcomes ("did this entity's page get updated"), not the retrieval method that produced them, so it needs no changes when/if embeddings are added.

### Known residual

**Paraphrase-only mentions evade string matching.** An entity discussed only by description — never by its title, a verb-prefix variant, or a registry alias — will not be caught by the scan, by design (this is exactly what makes it mechanical rather than semantic). This is the designated embeddings trigger (#1 above), not a bug in the current implementation; the staleness lint is the instrument that surfaces it when it happens.

**Registry-alias noise, tracked separately.** Some curated aliases in `entity_aliases.json` are over-broad — bare "the City," bare "A2Zero" — and inflate mention-count ordering in `scan-flagged`/`retrieve-for-context` without adding real recall value (a generic term matching everywhere doesn't help distinguish one entity from another). This doesn't break correctness (mention count only affects budget priority ordering, not whether an entity is flagged at all) but is worth a follow-up alias-registry cleanup pass, tracked separately from this plan.
