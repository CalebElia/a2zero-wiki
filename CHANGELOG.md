# Changelog

All notable changes to the a2zero-wiki project are documented here.
Format: reverse-chronological. Each entry covers a working session or meaningful milestone.

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
- Wired three-pass orchestration into `run_silver_ingest`: holistic → chunked LDP → finalize.
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
