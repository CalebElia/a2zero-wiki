# A2Zero Wiki — Project Brief

This file is loaded automatically into every Claude Code session. Read it before doing anything else.

## What This Project Is

A2Zero-wiki is the knowledge-graph pipeline for **Grapevine** — an AI policy accelerator that mines proven city programs and produces replication playbooks for other jurisdictions. This repo ingests Ann Arbor's carbon neutrality planning documents and produces a structured Obsidian wiki that can be queried by AI agents downstream.

Current source: **Ann Arbor A2ZERO Living Carbon Neutrality Plan (CAP 2020)** — fully ingested.
Next sources: Five annual progress reports (`prepared/annual-reports/a2zero-year1..5.md`) — cleaned, awaiting ingest.

## Directory Map

```
raw/                  ← PDFs and unprocessed source files (immutable originals)
prepared/             ← Cleaned markdown, reviewed, awaiting ingest (HITL gate)
  cap/                  ← cap-2020.md (pattern copy; already ingested)
  annual-reports/       ← year1..5.md (year1 ingested, year2..5 awaiting ingest)
wiki/                 ← Obsidian vault (everything here is intentionally ingested)
  sources/              ← Source documents copied here by ingest step 0
  plans/                ← One per city's climate action plan; parent of its strategy set (added 2026-07-09)
  strategies/           ← 7 strategy pages (strategy-1 through strategy-7)
  overviews/            ← One per source document
  actors/               ← Organizations, agencies, commissions, people
  initiatives/          ← Programs, projects, policies
  locations/            ← Geographic entities
  political-events/     ← Council votes, elections, public hearings
  technology/           ← Technology types with deployment/barrier details
  funding-events/       ← Specific grant awards and dollar allocations
  meetings/             ← Deliberative body meetings where A2Zero items were discussed
  framing/              ← Communications strategies / advocacy framings (planned — none yet on disk)
  contradictions/       ← Cross-source tensions and conflicts (planned — none yet on disk)
  topics/               ← Aggregate/curated synthesis pages (human-promoted from meta/query-log.md via topic-promote)
  index.md              ← Auto-rebuilt by Pass 3
  log.md                ← Append-only ingest log
  hot.md                ← Most-recent session summary (overwritten each Pass 3)
meta/                 ← Pipeline governance files, outside the vault — never queryable content (query-log.md, schema-drift.md, synthesis-ghosts.log, ingest-stats.jsonl, relationship-lexicon.md)
integration-plans/    ← Comprehend audit trail (<source-uuid>.json), outside the vault — never queryable content
blackboard/           ← Quads (structured fact triples) + section maps
registry/             ← entity_registry.json, entity_aliases.json, merge-log.jsonl
pipeline/             ← All Python ingest code
tests/                ← pytest suite (137 tests, 1 skipped — must stay green)
archive/              ← Prior wiki snapshots (v1, v2, v3-pre-ingest)
docs/superpowers/     ← Historical implementation plans and specs from earlier sessions
docs/architecture/    ← Locked architectural decisions and design rationale (read before speccing new pipeline work)
CHANGELOG.md          ← Reverse-chronological session-by-session change log
SCHEMA.md             ← Page types, frontmatter schemas, ontology governance
research-agenda.md    ← Source-selection priorities (human-maintained, not read by pipeline)
review-queue.md       ← Live inbox: structural/semantic/backlink lint findings awaiting decisions
```

## Three-Pass Ingest Pipeline

Run with:
```
python -m pipeline.orchestrator source \
  --source prepared/<type>/<uuid>.md \
  --uuid <uuid> \
  --title "<title>" \
  --quads-path blackboard/quads.jsonl \
  --wiki-root wiki \
  --review-queue review-queue.md \
  --section-maps-dir blackboard/section_maps
```

Optional flags on the `source` subcommand:
- `--include-quads` — Also run quad extraction (off by default; the quad linter is paused pending schema redesign, so quads are token-expensive and unused)
- `--quads-only` — Pass 2 quad extraction only; skip Pass 1 and wiki writes
- `--auto-approve` — Bypass the chunking gate (see below); generate section map mechanically

**Default mode is wiki-only.** Quad extraction adds ~1 LLM call per chunk and produces output that no downstream pipeline currently consumes.

For a complete step-by-step run guide with HITL gates, see [docs/how-to-run-ingest.md](docs/how-to-run-ingest.md).

### Chunking gate (HITL — required for LDP-routed sources)

Long documents that route to LDP (Pass 2 chunked extraction) require a human-reviewed section map. Three-step workflow:

```
python -m pipeline.orchestrator preflight --source prepared/<type>/<uuid>.md --uuid <uuid>
# Review blackboard/section_maps/<uuid>_preview.md
# Optionally edit blackboard/section_maps/<uuid>_proposed.json directly
python -m pipeline.orchestrator approve --uuid <uuid>
python -m pipeline.orchestrator source --source ... --uuid <uuid> ...
```

If `source` runs without an approved map and `--auto-approve` is not passed, it refuses with a clear error. Small documents (those that don't trigger LDP) bypass the gate entirely. See `docs/architecture/chunking-gate.md`.

**Pass 0 (copy + YAML inject):** Source file copied from `prepared/<type>/<uuid>.md` → `wiki/sources/<type>/<uuid>.md`. If the prepared file has no YAML frontmatter, one is injected (`uuid`, `source_type` inferred from directory, `title`, `ingest_date`, plus `covers-period-start`/`covers-period-end` if passed via `--covers-period-start`/`--covers-period-end` on the `source` subcommand).

**World-time grounding — `covers-period-start` / `covers-period-end`:** Every source page carries these two fields (`YYYY-MM`), recording the *real-world* period the document covers (e.g. an annual report's fiscal year) — never to be confused with `ingest_date`, which only records when the pipeline happened to run. `pipeline/phase_c_synthesize.py::extract_ingest_history` reads these fields to ground `synthesis.year-over-year-arc` and the digest's cross-strategy narrative in actual program chronology (2019–2025 for A2Zero) rather than pipeline bookkeeping dates. Always set these two flags when ingesting a new source — see `docs/action-plan-2026-07-09.md` Item 1 for the incident this fixes (arcs were narrating ingest dates, not program history) and `docs/project-evaluation-2026-07-09.md` for the full writeup.

**Pass 1A (Comprehend):** Reads `wiki/digest.md` plus the source and produces a structured integration plan saved to `integration-plans/<source-uuid>.json`. The plan (5 fields: `strategies-touched`, `extends`, `new-entities`, `retrieve-for-context`, `theme-connections`) flows downstream into both the holistic Writer (Pass 1B) and the LDP chunk extraction (Pass 2), informing which entities to extend vs. create and which existing page bodies to pre-load as integration context. Hard-fails when digest exists but the LLM call errors. Graceful fallback (no LLM call, empty plan) when no digest exists yet (first-ingest path). After Comprehend, a deterministic name-index scan augments the plan with `scan-flagged` entities the LLM missed and records budget-dropped bodies in `context-dropped`; both fields persist in `integration-plans/<uuid>.json` alongside the LLM-produced fields. Per-ingest telemetry lands in `meta/ingest-stats.jsonl`. See `docs/architecture/comprehend-plan-write.md` and `docs/architecture/deterministic-recall-floor.md`.

**Pass 1B (holistic synthesis):** Full-document read. Writer → Evaluator → Editor loop, now informed by the integration plan + digest. Produces: overview page, strategy body text, stub pages for all entities mentioned in the document. Uses streaming API (`max_tokens=64000`).

**Pass 1.5 (alias resolution):** Every proposed entity slug is resolved through `registry/entity_aliases.json` before writing. Known aliases redirect to the canonical page and trigger an LLM merge if the canonical page has real content.

**Pass 2 (chunked LDP):** Section-by-section extraction. Each chunk produces actor/initiative/location/political-event/technology/funding-event/meeting pages. Integrates into existing stubs from Pass 1.

**Pass 3 (finalize):** Rebuilds `index.md`, seals `log.md`, overwrites `hot.md`.

Post-ingest linting (on-demand). **Recommended order: semantic → backlink → structural**, not independent/arbitrary order. Structural's `BROKEN_LINK` repair (redirect a stale slug vs. create a new stub) requires the entity graph to already be stable — semantic merges can rename or delete a page after the fact, invalidating a broken-link fix made against it. Backlink only adds links to entities that already have pages, so it benefits from semantic running first for the same reason but doesn't block structural. Re-run `--structural` after each of the other two passes' `--apply` to get a clean picture, since merges/links can shift which links are actually broken. `--staleness` is per-ingest (not part of this state-scoped ordering) and complements structural — run it after each ingest, independent of the semantic/backlink/structural cycle:
```
python -m pipeline.phase_b_lint --wiki-root wiki --staleness     # flag entities the new source mentions but whose pages gained no citation; run after each ingest (optional --source-uuid)
python -m pipeline.phase_b_lint --wiki-root wiki --semantic      # near-duplicate detection (LLM); apply first
python -m pipeline.phase_b_lint --wiki-root wiki --backlink      # find missed entity mentions in strategy/overview bodies; apply next
python -m pipeline.phase_b_lint --wiki-root wiki --structural    # broken links, orphans; run last, after the entity graph is stable
python -m pipeline.phase_b_lint --wiki-root wiki --apply         # execute approved proposals from review-queue.md
```

One-time enrichment (rarely needed; used after prompt changes):
```
python -m pipeline._legacy.enrich_strategy_links --wiki-root wiki [--dry-run]
```

Phase C synthesis (run after lint + apply, before next ingest):
```
python -m pipeline.phase_c_synthesize --wiki-root wiki                                             # rebuild all 7 strategies + digest
python -m pipeline.phase_c_synthesize --wiki-root wiki --strategy strategies/strategy-1-renewable-grid  # single strategy
python -m pipeline.phase_c_synthesize --wiki-root wiki --digest-only                              # rebuild digest from existing synthesis: blocks
```

The synthesizer runs each LLM output through a deterministic validator that checks every entity slug against the filesystem. Broken references trigger a scoped Reviser LLM call that either substitutes a real entity or drops the bad slug; dropped slugs are logged to `meta/synthesis-ghosts.log` for human review. Recurring entries in that log signal entities worth either creating as pages or adding to `SUPPRESS_SLUGS` in `pipeline/phase_c_validate.py`. See `docs/architecture/synthesis-validation-loop.md`.

## Pipeline Modules

| File | Role |
|---|---|
| `orchestrator.py` | CLI entry point + three-pass orchestration |
| `pass1a_comprehend.py` | Pass 1A Comprehend: read digest + source → integration plan |
| `recall_scan.py` | Deterministic recall floor: entity name index + source scan + plan augmentation |
| `pass2a_pre_chunking.py` | HITL chunking gate: preflight + approve subcommands |
| `pass1b_synthesize.py` | Pass 1B Writer→Evaluator→Editor loop |
| `pass2a_chunk_loop.py` | Long-document chunk loop with section maps |
| `pass2b_extract.py` | Pass 2 chunk extraction (calls chunk loop for long docs) |
| `pass2c_merge.py` | LLM merge for duplicate page bodies |
| `pass3_finalize.py` | Pass 3 helpers: `rebuild_index`, `append_log`, `update_hot` |
| `phase_b_lint.py` | Post-ingest linting (structural, semantic, backlink, apply) |
| `phase_c_synthesize.py` | Phase C synthesis: L1 strategy blocks + L2 digest |
| `phase_c_validate.py` | Validate → Revise loop for phase_c_synthesize outputs |
| `schema_governance.py` | Relationship-lexicon prompt injection + schema-drift parse/apply loop |
| `topic_synthesize.py` | Query-log capture/promotion + topic page regeneration |
| `_aliases.py` | Pass 1.5 alias resolution |
| `_pages.py` | Page primitives (build/write/append) + `VALID_PAGE_TYPES` + quad extraction |
| `_models.py` | `WikiPage` dataclass + quad schema validation |
| `_llm.py` | Multi-provider LLM client (Anthropic / OpenAI) |
| `_legacy/enrich_strategy_links.py` | One-time pass to inject entity wikilinks into strategy bodies |
| `_legacy/raw_to_sources.py` | PDF → cleaned markdown (currently paused) |
| `_legacy/post_ingest.py` + `_legacy/quad_linter.py` | Quad pipeline review-queue generation (paused pending schema design) |
| `_legacy/registry.py` | Legacy entity registry (used by quad linter) |

## Key Conventions

**Slugs:** kebab-case, type-prefixed in the filesystem but not in wikilinks.
- File: `wiki/actors/ann-arbor-city-council.md`
- Wikilink: `[[actors/ann-arbor-city-council]]` or `[[actors/ann-arbor-city-council|Ann Arbor City Council]]`

**Source citations:** Always inline wikilinks, never bare text.
- Pattern: `([[sources/cap/cap-2020|cap-2020]])`

**Source-first-seen:** Frontmatter field. Must be a vault-relative wikilink: `[[sources/cap/cap-2020]]` not `[[sources/cap-2020]]` (the type subdirectory matters).

**Stub pages:** Created by Pass 1 with body `<!-- Body populated by holistic synthesizer -->`. Pass 2 replaces the stub body on first write; subsequent ingests integrate (merge) rather than replace.

**Stub detection:** `not bool(re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip())` — strips HTML comments before checking if body has real content.

**Alias registry:** `registry/entity_aliases.json` — canonical source of truth for entity name variants and temporal relationships. Every write in Pass 1 and Pass 2 resolves through this registry (Pass 1.5). Entries have: `canonical`, `type`, `aliases`, `relationship` (`name-variant`|`predecessor`|`absorbed-by`), optional `as-of`/`notes`. Approved lint proposals are automatically written back here by `lint_wiki --apply`.

**Program-produced collectives (working groups, ambassador corps, volunteer cohorts) stay typed `initiative`, not `actor`, even when cited as a partner/collaborator elsewhere.** `partners:` is a general related-entity field (initiative slugs already appear inside it dozens of times), not actor-only. Don't spawn a subsidiary `actor/` page for an initiative's own output — that recreates the exact "two pages, one concept" duplication semantic lint exists to catch. Redirect any actor-shaped mention to the initiative's canonical page and seed an alias-registry entry (e.g. `a2zero-ambassadors` → `initiatives/a2zero-ambassadors-program`) so future ingests resolve it the same way automatically.

**Merge log:** `registry/merge-log.jsonl` — append-only audit trail for every approved entity merge or temporal succession. Each entry: `date`, `action`, `from`/`into` (or `predecessor`/`successor`), `approved-by`. Use `git show <hash>:wiki/<path>.md` to recover any deleted page from git history.

**Review queue:** `review-queue.md` is a live inbox, not an append log. Each lint pass (`--structural`, `--semantic`, `--backlink`) replaces its own section. Annotated proposals (`[x] APPROVE_...` / `[x] KEEP_SEPARATE`) are cleared by `--apply`; unactioned and `DEFER`'d proposals stay.

**Schema drift:** When the LLM encounters an entity that doesn't fit any approved `type:` from `VALID_PAGE_TYPES`, it writes the page using the closest approved type AND adds `proposed-type: <new-type>` to the frontmatter. The pipeline auto-logs an entry to `meta/schema-drift.md` for HITL review, in the same `## <date> | Proposed type: "..." | Written as: "..." | Page: "..."` + `Resolution: [ ]` checkbox format `phase_b_lint.py --apply` already knows how to parse. Check the box and run `python -m pipeline.phase_b_lint --wiki-root wiki --apply` (same command used for `review-queue.md`) — approval adds the type to `registry/valid_page_types.json` (loaded into `VALID_PAGE_TYPES` in `pipeline/_pages.py` at import time) and strips `proposed-type:` from affected pages. `schema-drift.md` is append-only: resolved entries get an in-place `**Resolved ...**` marker rather than being deleted, unlike `review-queue.md`. Every unresolved entry also surfaces as a `SCHEMA_DRIFT_PENDING` finding on the next `--structural` run — nothing sits silently.

**Relationship lexicon:** `meta/relationship-lexicon.md` documents the approved frontmatter fields (Layer 1) and body-prose verbs (Layer 2) the LLM should prefer. Its content is injected into both the Pass 1B Writer prompt and the Pass 2 chunk-extraction prompt (`pipeline/schema_governance.py::build_lexicon_block`), wrapped in the standard `[RELATIONSHIP LEXICON]...[END RELATIONSHIP LEXICON]` bracket convention.

**Topic candidates → query-log.md:** The Writer's `topic_candidates` output (cross-cutting themes it noticed, phrased as a question with a citable `draft_narrative`) is logged directly into `meta/query-log.md` via `topic_synthesize.append_query_log_entry` — the same file and promotion path (`topic-promote`) a human-asked question uses. There is no separate `topic-candidates.md` system anymore; it's retired in favor of this single unified flow. Every unresolved `query-log.md` entry surfaces as a `QUERY_LOG_PENDING` finding on the next `--structural` run.

## Environment Variables

```bash
ANTHROPIC_API_KEY=sk-ant-...   # required for default operation
OPENAI_API_KEY=sk-...          # required when LLM_PROVIDER=openai
LLM_PROVIDER=anthropic         # "anthropic" (default) or "openai"
LLM_MODEL_OVERRIDE=            # force a specific model ID (optional)
```

Set these in your shell or copy `.env.example` → `.env` and `source .env` before running the pipeline. Never commit `.env`.

The pipeline uses `LLM_PROVIDER` to select the backend; `LLM_MODEL_OVERRIDE` bypasses the internal model map entirely and routes to the literal model ID string you provide.

## What NOT to Do

- Never create or edit files in `wiki/` directly during a pipeline run — use the pipeline functions.
- Never commit `wiki/.obsidian/workspace.json` — it is gitignored.
- Never commit `.DS_Store` or `__pycache__/` — gitignored.
- Never add source files directly to `wiki/sources/` — they must come from `prepared/` via the ingest step 0 copy.
- Never call `messages.create()` for long generations — use `messages.stream()` context manager (`max_tokens=64000` requires streaming).
- Never remove `betas=` parameter workaround note — SDK 0.111.0 doesn't use it; cache_control works natively.

## Development Workflow

**Small changes** (bug fixes, content edits, config): commit directly to `main`.

**Bigger experiments** (new pipeline pass, lint_wiki, new source type): use a feature branch.

```bash
git checkout -b feat/<name>      # create branch from current main
git push -u origin feat/<name>   # push branch to GitHub
gh pr create                     # open pull request when ready
gh pr merge --squash             # merge and delete branch
```

**Reverting a bad commit:**
```bash
git log --oneline                # find the bad commit hash
git revert <hash>                # creates a new "undo" commit — safe, keeps history
git push                         # push the revert
```

**Reverting a merged PR:** Go to the PR on GitHub → "Revert" button → creates a new revert PR automatically.

## Tests

```bash
python -m pytest tests/ -q       # must be green before any commit to main
```

152 tests, 1 skipped (intentional). If tests break, fix them before continuing — do not bypass.

## Active Architectural Direction

**Read `docs/architecture/knowledge-synthesis-architecture.md` before speccing or implementing any pipeline changes.**

The pipeline is being upgraded to close a fundamental LLM-Wiki design gap: the extraction pass currently has no visibility into existing wiki content, breaking the compounding-knowledge property. The solution is a GraphRAG-inspired synthesis hierarchy:

- **L0** — Entity pages (exists)
- **L1** — Strategy synthesis pages (exist as prose, need LLM-maintained `synthesis:` section)
- **L2** — `wiki/digest.md` — cross-strategy narrative + entity map, injected into every Comprehend pass (~4-6k tokens)

The upgraded ingest cycle: **Phase A** (extraction) → **Phase B** (lint + human review) → **Phase C** (`synthesize_wiki` command rebuilds L1 → L2) → **Phase D** (ready for next ingest). Synthesis must come after lint — the digest encodes the wiki's state and must encode a clean, reviewed state.

Implementation order: `synthesize_wiki` command → digest injection into Comprehend pass → Comprehend/Plan split → strategy `synthesis:` sections.

## Strategy Page Foundation / Progression Split

**Read `docs/architecture/strategy-foundation-progression.md` before touching `pipeline/pass1b_synthesize.py`'s strategy-writing logic or `pipeline/phase_c_synthesize.py`'s `build_strategy_synthesis`.**

A 2026-06-30 content-quality audit found that strategy pages were silently losing CAP-2020 foundational content (targets, cost estimates, dominant mechanisms) on every ingest once `wiki/digest.md` existed — the Writer prompt was only shown a compressed digest, not the actual prior page text, and the write path did an unconditional full-body overwrite. Fixed 2026-07-01.

Every strategy page body now has two `##` sections:

- **`## Foundation`** — CAP-2020's original design intent (target %, cost estimate, dominant mechanism), extracted once directly from `wiki/sources/cap/cap-2020.md` via `scripts/migrate_strategy_foundation.py`. **Frozen forever after that one-time migration.** No pipeline pass may ever regenerate it — `pipeline/pass1b_synthesize.py::_write_synthesis` raises `RuntimeError` if it's ever asked to write a strategy page with no Foundation section, rather than silently proceeding.
- **`## Progress Synthesis`** — LLM-regenerated each ingest. Pass 1B now always injects the FULL existing Progress Synthesis text into the Writer prompt (not gated on digest absence, per the bug above) so facts accumulate instead of compressing.

Helpers: `_split_strategy_sections(body)` / `_assemble_strategy_body(foundation, progress)` in `pipeline/pass1b_synthesize.py`. Phase C's `build_strategy_synthesis` also now receives `foundation_text` and full `ingest_history` (via `extract_ingest_history`), so the `synthesis.core-target` field and `year-over-year-arc` cite real Foundation figures and real ingest dates instead of boilerplate.

## Ontology Nesting Model — Plan → Strategy → Initiative → sub-initiative

**Read `docs/architecture/ontology-nesting-model.md` before adding new relationship fields or touching `pipeline/phase_c_synthesize.py`'s `_load_strategies_from_plan`/`ALL_STRATEGIES`.**

A 2026-07-09 review-queue session found that semantic lint kept misreading genuine containment relationships (a longstanding program vs. a specific pilot spun off from it) as either duplicates or supersessions, because no frontmatter field existed to express "this initiative is a specific instantiation of that ongoing one." The same review surfaced that the canonical "A2Zero" plan page was itself mistyped as an `initiative` nested *under* one of its own child strategies — backwards from the real hierarchy.

Fixed 2026-07-09:
- New `plan` page type (`wiki/plans/<slug>.md`) sits above `strategy`. `strategies:` on the plan page lists its children; `parent-plan:` on each strategy page points up. `_load_strategies_from_plan()` reads this as the source of truth for which strategies to rebuild in Phase C, falling back to the hardcoded `ALL_STRATEGIES` constant only when no `plans/` page exists — this is what lets a second city's plan, with a different strategy count, work without a pipeline code change.
- New `part-of` / `sub-initiatives` field pair for strict initiative-to-initiative containment (program ⊃ pilot), distinct from the many-to-many `related-strategies` tagging. See `meta/relationship-lexicon.md` for the full field documentation and the extraction-failure pattern this fixes.
- A body that *produces* a deliverable (a working group writing a strategy document) is a different pattern from program/pilot containment and is NOT modeled with `part-of` — see the lexicon for why, and how that case is handled with prose cross-links instead.

## GitHub

Repo: https://github.com/CalebElia/a2zero-wiki (private)
Branch protection: `main` is protected — direct pushes blocked for experimental work.
