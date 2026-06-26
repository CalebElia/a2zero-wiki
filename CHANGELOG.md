# Changelog

All notable changes to the a2zero-wiki project are documented here.
Format: reverse-chronological. Each entry covers a working session or meaningful milestone.

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
