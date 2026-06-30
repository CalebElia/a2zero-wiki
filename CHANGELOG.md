# Changelog

All notable changes to the a2zero-wiki project are documented here.
Format: reverse-chronological. Each entry covers a working session or meaningful milestone.

---

## 2026-06-29 — Comprehend → Plan → Write architecture

**What changed:**
- **`pipeline/comprehend.py`** — new module implementing Pass 1A: reads `wiki/digest.md` plus the source, calls an LLM to produce a structured integration plan, validates the plan's slugs via the existing `synthesis_validation` machinery, persists to `wiki/integration-plans/<source-uuid>.json`, and pre-loads entity page bodies for `retrieve-for-context` (capped at 30k tokens, prioritized by `extends` + mention frequency).
- **`pipeline/holistic_synthesizer.py`** — `synthesize_source()` now accepts `integration_plan` and `digest_content` kwargs. Replaces the legacy `integration_block` (raw strategy bodies) with a plan + digest injection block. Legacy fallback preserved for callers that don't pass the new kwargs.
- **`pipeline/ldp.py`** — `extract_quads_chunked()` and `run_ldp_ingest()` accept `integration_plan` + `retrieved_bodies` kwargs and prepend them as a cached prefix to each chunk's context. Plan is a prior, not a constraint — LDP still creates pages for entities outside the plan as before.
- **`pipeline/run_ingest.py`** — orchestrates Comprehend before Pass 1. Hard-fails the ingest when `digest.md` exists but the Comprehend LLM call errors (don't waste downstream tokens). Graceful fallback (no LLM call, empty plan) when no digest exists (first-ingest path). Per-ingest telemetry appended to `wiki/meta/ingest-stats.jsonl`.
- **`wiki/integration-plans/`** — new directory for integration plan artifacts, committed for audit trail. Each `<source-uuid>.json` records how that ingest mapped the source onto existing wiki state.
- **`wiki/meta/ingest-stats.jsonl`** — per-ingest telemetry (Comprehend skipped flag, plan size, extends/new-entities/retrieve counts, retrieved-chars total).
- **18 new tests** in `tests/test_comprehend.py` (13) + integration tests added to `tests/test_holistic_synthesizer.py`, `tests/test_ldp.py`, `tests/test_run_ingest.py` (5 collectively). Total suite: 205 passed, 1 skipped.
- **Spec:** `docs/architecture/comprehend-plan-write.md`. **Plan:** `docs/superpowers/plans/2026-06-29-comprehend-plan-write.md`. **Branch:** `feat/digest-injection` (draft PR opened for review).

**Why:** Year 1 and Year 2 ingests both produced visible entity fragmentation because the LLM responsible for the integration decision never saw what the wiki already knew. We compensated downstream with alias resolution and lint cycles, but the *fundamental* problem was upstream: the holistic synthesizer conflated reading with writing, treating each source as if it were the only one. The Comprehend split makes the integration decision an explicit, structured artifact (the plan), and the plan flows downstream to inform both the Writer pass and the LDP chunk extraction. Per-ingest cost stops growing with wiki size — the digest is constant-size regardless of how many entities exist.

---

## 2026-06-29 — Synthesis validation loop

**What changed:**
- **`pipeline/synthesis_validation.py`** — new module implementing a Write → Validate → Revise loop for `synthesize_wiki`. Deterministic validator checks every entity slug emitted by the synthesis and narrative LLM calls against the filesystem; broken references trigger a scoped Reviser LLM call that substitutes from the inventory, drops from structured fields, or demotes wikilinks to plain text in prose.
- **Two validation points** in `synthesize_wiki()`: after `build_strategy_synthesis()` (catches ghosts before they are written to strategy frontmatter) and after `build_digest_narrative()` (catches ghosts the narrative LLM invents during digest assembly).
- **Reverted the inventory-binding language** from `_STRATEGY_SYNTHESIS_SYSTEM` — the Writer is again free to reach for plausible entities; correctness is enforced at the validation boundary instead of via prompt constraints.
- **Removed `_resolve_synthesis_slugs`, `_SUPPRESS_SLUGS`** from `synthesize_wiki.py` (moved into the Validator).
- **`wiki/meta/synthesis-ghosts.log`** — append-only log of dropped ghost slugs for human review. Recurring entries signal entities worth either creating as pages or adding to `SUPPRESS_SLUGS` permanently.
- **20 new tests** in `tests/test_synthesis_validation.py` covering BrokenRef/ValidationReport dataclasses, structured validation (alias resolution, type-sort, suppress list, deduplication), narrative wikilink parsing, ghost logging, and Reviser fallback behavior. Total suite: 187 passed, 1 skipped.
- **`registry/entity_aliases.json`** — added `a2zero-program` alias (recurring ghost surfaced via the new log) → OSI.
- **Spec:** `docs/architecture/synthesis-validation-loop.md`. **Plan:** `docs/superpowers/plans/2026-06-29-synthesis-validation-loop.md`.

**Why:** We were responding to every ghost-reference by tightening the synthesis prompt and growing an inline suppress list. That doesn't generalize (novel ghosts kept appearing across runs) and over-constrains (last iteration's "only use inventory slugs" rule wiped out `core-actors` for four strategies whose inventories were sparse). Separating the analytical pass (Writer) from the mechanical correctness pass (Validator + Reviser) lets each be optimized independently. The post-implementation smoke test produced zero ghost references in any strategy synthesis frontmatter and zero broken wikilinks in `digest.md` — the cleanest output of the entire session.

---

## 2026-06-28 — Multi-provider LLM switching layer

**What changed:**
- **`pipeline/llm.py`** — new provider-agnostic adapter. `chat()` (non-streaming) and `stream_chat()` (streaming, returns `None` on max_tokens truncation) read `LLM_PROVIDER` (default `"anthropic"`) and `LLM_MODEL_OVERRIDE` from the environment. Strips Anthropic-specific `cache_control` keys from message content before sending to OpenAI — OpenAI caches automatically and rejects explicit annotations.
- **All 7 pipeline modules** migrated off direct Anthropic SDK calls: `holistic_synthesizer`, `wiki_pages`, `wiki_writer`, `lint_wiki`, `merge_pages`, `raw_to_sources`, `ldp`, `synthesize_wiki`.
- **15 new tests** in `tests/test_llm.py` covering both providers, model selection, `LLM_MODEL_OVERRIDE` env var, `_strip_cache_control` behavioral tests, and Anthropic/OpenAI streaming.
- **All existing test mocks simplified** — `patch("pipeline.X.anthropic.Anthropic")` chains → `patch("pipeline.X.chat")` or `patch("pipeline.X.stream_chat")` returning plain strings.
- **`requirements.txt`** — added `openai>=1.0.0`.
- **`.env.example`** — documents `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL_OVERRIDE`.
- **`CLAUDE.md`** — new Environment Variables section.

**Why:** Two-provider A/B capability — GPT-5.4 ($2.50/M input, 1.05M context, 128k output) vs Claude Sonnet 4.6. Setting `LLM_PROVIDER=openai` switches the entire pipeline with no code changes. `cache_control` is stripped because OpenAI rejects explicit cache annotations (OpenAI caches automatically based on common prefixes).

---

## 2026-06-28 — Phase C: synthesize_wiki command (L1 + L2)

**What changed:**
- **`pipeline/synthesize_wiki.py`** — new Phase C command. Reads the clean post-lint entity layer, rebuilds machine-maintained `synthesis:` blocks in each of the 7 strategy pages (L1), and writes `wiki/digest.md` (L2): a ~4–6k-token briefing combining cross-strategy narrative, structured entity map, and recent ingest delta.
- **15 new unit + integration tests** in `tests/test_synthesize_wiki.py`. Key functions: `gather_strategy_entities()`, `extract_recent_delta()`, `build_strategy_synthesis()`, `write_strategy_synthesis()`, `build_digest_narrative()`, `assemble_digest()`, `write_digest()`.
- **`tests/fixtures/synthesize_wiki/wiki/`** — minimal fixture entity tree (3 pages: solarize-ann-arbor, glrea, electrification-campaign) for integration tests.
- **`CLAUDE.md`** — Phase C command reference added; test count updated to 152.
- **Two bugs caught and fixed by code review:** (1) `gather_strategy_entities()` now strips `[[]]` wikilink brackets from `related-strategies` values before matching (real wiki format vs bare slug format); (2) `assemble_digest()` uses plain-text source reference in Recent delta instead of an unresolvable `sources/.../uuid` wikilink.

**Why:** Establishes the L1 and L2 layers defined in `docs/architecture/knowledge-synthesis-architecture.md`. Closes Step 1 of four implementation steps in the knowledge synthesis upgrade. Next: wire `digest.md` injection into the holistic synthesizer's Comprehend pass (Plan 2).

---

## 2026-06-26 — Lint Improvements + Entity Continuity Layer

**What changed:**
- **Structural lint: TYPE_MISMATCH check** — `structural_lint()` now detects pages whose `type:` frontmatter doesn't match their containing directory (e.g. `type: initiative` living in `topics/`). Emits `[TYPE_MISMATCH]` finding. Added `_EXPECTED_TYPE_BY_DIR` and `_CANONICAL_DIR_BY_TYPE` constants to `lint_wiki.py`.
- **Semantic lint: cross-directory comparison** — Before the per-directory loop, `semantic_lint()` now collects misrouted pages from `topics/` (any page with a non-`topic` type frontmatter) and pools them into the correct type group for comparison. Topics-page duplicates of initiatives/actors are now surfaced automatically.
- **Pass 1.5: fuzzy title resolution** — `alias_registry.py` gains `fuzzy_resolve_slug_for_title()` (threshold 0.82 — higher than semantic dedup to avoid false redirects). Called as a third fallback after exact slug and exact title resolution in both `holistic_synthesizer.py` and `wiki_writer.py`. Catches year-over-year name drift like "Ann Arbor Solarize Program" → `solarize-ann-arbor`.
- **Post-ingest alias seeding** — `alias_registry.py` gains `seed_aliases_from_ingest()`: scans all entity pages first-seen in the current source and registers their display titles in `entity_aliases.json`. Called automatically in Pass 3 of `run_ingest.py`. On subsequent ingests, fuzzy title resolution has titles to match against.
- **Retroactive seeding** — Ran seeding against all three ingested sources (CAP 2020, Year 1, Year 2): 345 new alias entries added. Year 3+ ingests will benefit immediately.

**Why:** Year 2 ingest produced fragmented pages for three flagship initiatives (Bryant Decarbonization, SEU, Solarize Ann Arbor) that required manual consolidation. Two failure modes identified: (1) misrouted pages in `topics/` were invisible to semantic lint (now fixed); (2) year-over-year name drift bypassed exact alias matching (now fixed with fuzzy resolution + seeding). These changes close both gaps before Year 3 ingest.

---

## 2026-06-26 — Year 2 Ingest, Post-Ingest Lint Cycle, Entity Consolidation

**What changed:**
- **Year 2 annual report ingest** (`a2zero-year2.md`) — `--wiki-only` flag (no quads). 148 pages written; wiki index at 399 entities across 11 types.
- **LDP threshold lowered** — `_should_use_ldp()` gate changed from `> 1000 lines AND > 10 headings` to `> 150 lines AND > 5 headings` so annual reports route through the chunked LDP path correctly.
- **Quad extractor hardened** — `extract_quads_from_source()` switched from `messages.create(max_tokens=8192)` to `messages.stream(max_tokens=16384)`; added code-fence stripping and `_recover_partial_quad_array()` for partial JSON recovery. Test mock updated to match streaming pattern.
- **Semantic lint cycle** — 20 proposals reviewed; 19 merges applied (actors: RMI→rmi, planning-dept duplicate, DDA duplicate; initiatives: ambassadors variant; locations: landfill variant; temporal succession: benchmarking ordinance). `merge-log.jsonl` and alias registry updated.
- **Backlink lint bug fixed** — `_llm_filter_candidates()` was sending full page bodies to the LLM, causing empty responses for long strategy pages. Fix: removed body from user message; LLM now receives only context snippets. Added code-fence stripping + empty-string guard. Same fix applied to semantic verdict parsing.
- **Apply bug fixed** — `apply_proposals()` was unconditionally accessing `p["page_a"]` before checking proposal type; LINK proposals use different keys and crashed after semantic merges succeeded. Fixed dispatch order with early `continue`. Also fixed case-sensitivity in LINK pattern matching (`re.IGNORECASE` + matched-text display alias).
- **Backlink lint cycle** — 35 proposals from second run (after bug fix); 21 APPROVE_LINK, 14 KEEP_UNLINKED. Applied cleanly.
- **Relationship lexicon expanded** — `wiki/meta/relationship-lexicon.md` rewritten to cover all three vocabulary layers: 19 frontmatter fields (table), 13 approved prose verbs, quad relations placeholder.
- **Entity consolidation — Bryant Neighborhood Decarbonization** — merged `topics/bryant-neighborhood-decarbonization` (misrouted Year 2 duplicate) and `initiatives/bryant-neighborhood-climate-action-grant` (milestone-level stub) into canonical `initiatives/bryant-neighborhood-decarbonization`. No link rewriting needed; all inbound links already used the initiatives/ slug.
- **Entity consolidation — Sustainable Energy Utility** — merged `topics/sustainable-energy-utility` (misrouted), `initiatives/sustainable-energy-utility-exploration` (sub-element), and `initiatives/ann-arbor-sustainable-energy-utility` (name variant) into new canonical `initiatives/sustainable-energy-utility`. Fixed 3 broken inbound links that already targeted the initiatives/ slug. Removed hallucinated alias entry (`sustainable-energy-utility-seu` → OSI).
- **Entity consolidation — Solarize Ann Arbor** — merged `initiatives/ann-arbor-solarize-program` (Year 2 name variant) into canonical `initiatives/solarize-ann-arbor`; absorbed `initiatives/solarize-toolkit` (program deliverable, not a standalone initiative) as milestone. GLREA + missy-stults inbound links rewritten. `commercial-solarize-pilot` and `ann-arbor-solar-stories` kept separate (genuinely distinct scope/leadership).
- **Restaurant page type fix** — three restaurant pages created by Year 2 ingest as `type: location` in `locations/` moved to `actors/` with correct `type: actor, actor-type: business` schema. Slugs: `zingermans-next-door-cafe`, `ginger-deli`, `el-harissa-market-cafe`.

**Why:** Year 2 ingest exposed two recurring failure modes in the pipeline: (1) the same initiative appearing under slightly different names across annual reports produces fragmented pages that bypass alias resolution; (2) misrouted pages (`type: initiative` living in `topics/`) are invisible to the semantic lint because it compares within directories. Manual consolidation was required for three flagship initiatives. See review-queue.md discussion for proposed lint improvements.

---

## 2026-06-26 — Year 1 Ingest, Backlink Lint, Naming Cleanup

**What changed:**
- **Year 1 annual report ingest** — first ingest after CAP 2020. Year 1 source file (`a2zero-year1.md`) had no YAML frontmatter; uncovered Pass 0 gap.
- **Pass 0 YAML auto-injection** — `run_ingest.py` now prepends YAML frontmatter (`uuid`, `source_type` inferred from `prepared/<type>/` directory, `title`, `ingest_date`) to any copied source file that lacks one. Files prepared with frontmatter pass through unchanged.
- **Strategy entity wikilinks** — tightened the holistic synthesizer prompt to REQUIRE wikilinks on first mention of every named entity in strategy bodies. Added `pipeline/enrich_strategy_links.py` for one-time enrichment of existing strategy pages (267-entity catalogue, LLM rewrite per page).
- **Backlink lint (`--backlink`)** — new librarian-style lint mode in `lint_wiki.py`. Two stages: (1) string-match every page title against the bodies of strategies and overviews (≥5 chars, longest-first, skipping already-linked text); (2) LLM filter per page that confirms each candidate before emitting a `LINK_PROPOSED` proposal. `--apply` inserts the wikilink at the first plain-text occurrence.
- **Review-queue redesign** — `review-queue.md` is now a live inbox, not an append log. `--structural` and `--semantic` and `--backlink` each replace their own section (only if unannotated). `_cleanup_review_queue` state machine clears resolved `[x] APPROVE_…` / `[x] KEEP_SEPARATE` blocks after `--apply`, leaving only `DEFER`'d and unannotated items.
- **Ambassadors merge** — merged `neighborhood-and-youth-ambassador-program` into `a2zero-ambassadors-program` directly (semantic lint missed the pair due to title distance). Wrote alias, rewrote 7 inbound links, appended to merge-log with diagnostic notes.
- **Naming cleanup — medallion vocabulary retired in code:**
  - `pipeline/silver_to_gold.py` → `pipeline/wiki_pages.py`
  - `extract_quads_from_silver()` → `extract_quads_from_source()`
  - `run_silver_ingest()` → `run_source_ingest()`
  - `silver` subcommand → `source` (new CLI: `python -m pipeline.run_ingest source --source prepared/...`)
  - `tests/test_silver_to_gold.py` → `tests/test_wiki_pages.py`
  - All `silver_body=` / `silver_content=` kwargs renamed to `source_body=` / `source_content=`
  - `mechanism` moved out of Pass 2 writable types (now human-curated only — requires ≥2 corroborating sources)
- **Docs harmonized** — SCHEMA.md, CLAUDE.md, CHANGELOG.md, research-agenda.md updated to reflect current state. `wiki/meta/` directory stubbed with placeholder files for schema-drift / topic-candidates / relationship-lexicon.

**Why:** Year 2 ingest is next, and the team is about to grow. Drift between code, schema, and docs had accumulated to the point that a new collaborator reading SCHEMA.md would be misled. The naming cleanup retires the bronze/silver/gold medallion vocabulary fully — both file paths AND module/function/CLI names — so the codebase reads consistently with the data layers.

---

## 2026-06-25 — Dedup/Alias Enforcement + lint_wiki

**What changed:**
- Added `pipeline/alias_registry.py` — load/resolve/fuzzy helpers wrapping `registry/entity_aliases.json`.
- Added `pipeline/merge_pages.py` — LLM merge call combining two page bodies into one; fails safe to existing body on any failure.
- Pass 1.5 integrated into `holistic_synthesizer.py` and `wiki_writer.py`: every proposed entity slug is resolved through the alias registry before writing; known aliases redirect to the canonical page and trigger an LLM merge if the page has real content.
- Extended `entity_aliases.json` schema with `relationship`, `as-of`, `notes` fields; retrofitted all 13 existing entries with `relationship: name-variant`; added first `predecessor` entry (SEU → OSI).
- Added `pipeline/lint_wiki.py` with three modes: `--structural` (broken links, orphans), `--semantic` (fuzzy + LLM near-duplicate detection with proposals to review-queue.md), `--apply` (execute approved proposals: merge content, rewrite inbound links, update alias registry, log to `registry/merge-log.jsonl`).
- Created `registry/merge-log.jsonl` — empty append-only audit trail for all approved merges and temporal successions.

**Why:** Multi-document ingests were producing duplicate entity pages when the same real-world entity appeared under different names across source documents. The alias enforcement layer (Pass 1.5) prevents duplicates during ingest; `lint_wiki` surfaces and resolves any existing duplicates post-ingest with HITL review.

---

## 2026-06-25 — Vault Architecture & GitHub Setup

**What changed:**
- Introduced `prepared/` staging layer outside the Obsidian vault. Source files now live in `prepared/<type>/<uuid>.md` until ingest is triggered; `run_ingest.py` copies them into `wiki/sources/` as step 0. This ensures the vault only ever contains intentionally ingested content.
- Moved annual report source files (`a2zero-year1..5.md`) from `wiki/sources/annual-reports/` to `prepared/annual-reports/` — they are cleaned but not yet ingested.
- Added `prepared/cap/cap-2020.md` as a copy of the ingested CAP source to establish the directory pattern.
- Fixed `holistic_synthesizer.py` stub page wikilinks: was generating `[[sources/<uuid>]]` (missing type subdirectory), now correctly uses `[[<source_rel_path>]]` — eliminates ghost nodes in Obsidian graph.
- Added 4 aggregate pages manually curated from CAP 2020 appendices: `wiki/topics/a2zero-public-engagement-log.md`, `wiki/topics/a2zero-community-ideas-received.md`, `wiki/initiatives/a2zero-technical-advisory-committees.md` (appended TAC meeting log), `wiki/actors/a2zero-partner-organizations.md`.
- Restored `wiki/sources/cap/cap-2020.md` content (was zeroed out by a `rm -rf` during a move that hit a pre-existing pipeline stub at the same path).
- Created private GitHub remote and pushed full history.
- Created `CHANGELOG.md` and `CLAUDE.md`.

**Why:** The vault was accumulating un-ingested source files as disconnected Obsidian graph nodes, adding noise to queries. The `prepared/` layer enforces a clear HITL gate between cleaning and ingestion.

---

## 2026-06-24 — Three-Pass Pipeline v3 + Full CAP 2020 Ingest

**What changed:**
- Completed and stabilized the three-pass ingest pipeline: Pass 1 (holistic synthesis: Writer → Evaluator → Editor), Pass 2 (chunked LDP extraction), Pass 3 (rebuild index.md, seal log.md).
- Raised all `max_tokens` to model ceiling (64,000) to eliminate truncation failures on long documents.
- Switched from `messages.create()` to streaming API (`messages.stream()` context manager) — required when `max_tokens > 10-minute threshold`.
- Fixed stub detection bug: replaced `body.startswith("<!--")` check with `re.sub(r"<!--.*?-->", "", body).strip()` in 4 locations — was misclassifying pages with real content after a leading HTML comment.
- Fixed first-strategy-write behavior: initial Pass 1 write now replaces the stub comment entirely rather than appending after it.
- Added `.gitignore` excluding `.DS_Store`, `wiki/.obsidian/workspace.json`, `.superpowers/` session artifacts, Python cache.
- Moved `sources/` into `wiki/sources/` so Obsidian wikilinks resolve correctly (vault root is `wiki/`).
- Ran full clean ingest of CAP 2020: produced 243 wiki pages across 8 types.

**Why:** Prior runs were failing due to token ceiling limits and the stub detection bug was causing Pass 1 to skip pages that already had real content.

---

## 2026-06-23 — Holistic Synthesizer + Wiki Index

**What changed:**
- Added `pipeline/holistic_synthesizer.py` — Pass 1 full-document read producing overview page, strategy bodies, and stub pages for Pass 2 to fill.
- Added `pipeline/wiki_index.py` — helpers for `index.md`, `log.md`, and `hot.md` per Obsidian vault conventions.
- Wired three-pass orchestration into `run_silver_ingest` (since renamed to `run_source_ingest`): holistic → chunked LDP → finalize.
- Removed `plan_extractor.py` — functionality absorbed into holistic synthesizer.
- Renamed `silver/` → `sources/` and `bronze/` → `raw/` throughout codebase for clarity.

**Why:** Prior two-pass design (plan extractor + LDP chunks) produced strategy pages without holistic context, leading to thin content and missed cross-cutting themes.

---

## 2026-06-22 — LDP Module + Pass 3 Entity Extraction

**What changed:**
- Added `pipeline/ldp.py` — chunked extraction for long documents using regex section maps.
- Added Pass 3 entity page extraction: actors, initiatives, locations, political events extracted per chunk.
- Threaded `silver_relative_path` through the extraction chain so all wiki pages cite their source with correct vault-relative wikilinks.
- Added strategy slug whitelist guard to prevent Pass 3 from creating spurious strategy pages.
- Wired Pass 3 into the LDP module and silver ingest runner.

**Why:** The CAP 2020 is ~280KB / 4,283 lines — too large for a single LLM context window. LDP (chunked) extraction was needed to cover the full document without truncation.

---

## 2026-06-21 — Pipeline Foundation

**What changed:**
- Bootstrapped project: directory structure, `SCHEMA.md`, `requirements.txt`, test fixtures.
- Built quad ID generation and schema validation.
- Built entity registry with alias resolution and disk persistence (`registry/entity_registry.json`).
- Built bronze-to-silver converter (PDF extraction + LLM cleaning).
- Built silver-to-gold quad extractor with dedup and schema validation.
- Built wiki page builder/writer with YAML frontmatter.
- Built append-only wiki page update (Pass 4).
- Built quad linter (schema, duplicate, dark matter detection).
- Built post-ingest pipeline generating `review-queue.md` with 3-tier triage.
- Built end-to-end ingest runner connecting all passes.

**Why:** Initial build-out of the A2Zero wiki pipeline — transforming the Ann Arbor CAP 2020 PDF into a structured, queryable Obsidian knowledge graph for the Grapevine policy replication platform.
