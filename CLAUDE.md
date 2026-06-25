# A2Zero Wiki — Project Brief

This file is loaded automatically into every Claude Code session. Read it before doing anything else.

## What This Project Is

A2Zero-wiki is the knowledge-graph pipeline for **Grapevine** — an AI policy accelerator that mines proven city programs and produces replication playbooks for other jurisdictions. This repo ingests Ann Arbor's carbon neutrality planning documents and produces a structured Obsidian wiki that can be queried by AI agents downstream.

Current source: **Ann Arbor A2ZERO Living Carbon Neutrality Plan (CAP 2020)** — fully ingested.
Next sources: Five annual progress reports (`prepared/annual-reports/a2zero-year1..5.md`) — cleaned, awaiting ingest.

## Directory Map

```
raw/                  ← PDFs and unprocessed source files (bronze)
prepared/             ← Cleaned markdown, reviewed, awaiting ingest (HITL gate)
  cap/                  ← cap-2020.md (pattern copy; already ingested)
  annual-reports/       ← year1..5.md (ready to ingest)
wiki/                 ← Obsidian vault (everything here is intentionally ingested)
  sources/              ← Source documents copied here by ingest step 0
  strategies/           ← 7 strategy pages (strategy-1 through strategy-7)
  overviews/            ← One per source document
  actors/               ← Organizations, agencies, commissions
  initiatives/          ← Programs, projects, policies
  locations/            ← Geographic entities
  political-events/     ← Council votes, elections, public hearings
  topics/               ← Aggregate/curated pages (not pipeline-generated)
  index.md              ← Auto-rebuilt by Pass 3
  log.md                ← Append-only ingest log
  hot.md                ← Frequently linked pages
blackboard/           ← Quads (structured fact triples) + section maps
registry/             ← entity_registry.json, entity_aliases.json
pipeline/             ← All Python ingest code
tests/                ← pytest suite (101 tests, 1 skipped — must stay green)
archive/              ← Prior wiki snapshots
docs/                 ← Empty; reserved for design docs
```

## Three-Pass Ingest Pipeline

Run with: `python -m pipeline.run_ingest silver --source prepared/<type>/<uuid>.md --uuid <uuid> --title "<title>" --quads-path blackboard/quads.jsonl --wiki-root wiki --review-queue review-queue.md --section-maps-dir blackboard/section_maps`

**Pass 0 (copy):** Source file copied from `prepared/<type>/<uuid>.md` → `wiki/sources/<type>/<uuid>.md`.

**Pass 1 (holistic synthesis):** Full-document read. Writer → Evaluator → Editor loop. Produces: overview page, strategy body text, stub pages for all entities mentioned in the document. Uses streaming API (`max_tokens=64000`).

**Pass 2 (chunked LDP):** Section-by-section extraction. Each chunk produces actor/initiative/location/political-event pages. Integrates into existing stubs from Pass 1.

**Pass 3 (finalize):** Rebuilds `index.md`, seals `log.md`.

Post-ingest linting (not yet implemented): `python -m pipeline.lint_wiki` — on-demand.

## Key Conventions

**Slugs:** kebab-case, type-prefixed in the filesystem but not in wikilinks.
- File: `wiki/actors/ann-arbor-city-council.md`
- Wikilink: `[[actors/ann-arbor-city-council]]` or `[[actors/ann-arbor-city-council|Ann Arbor City Council]]`

**Source citations:** Always inline wikilinks, never bare text.
- Pattern: `([[sources/cap/cap-2020|cap-2020]])`

**Source-first-seen:** Frontmatter field. Must be a vault-relative wikilink: `[[sources/cap/cap-2020]]` not `[[sources/cap-2020]]` (the type subdirectory matters).

**Stub pages:** Created by Pass 1 with body `<!-- Body populated by holistic synthesizer -->`. Pass 2 replaces the stub body on first write; subsequent ingests integrate (merge) rather than replace.

**Stub detection:** `not bool(re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip())` — strips HTML comments before checking if body has real content.

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

101 tests, 1 skipped (intentional). If tests break, fix them before continuing — do not bypass.

## GitHub

Repo: https://github.com/CalebElia/a2zero-wiki (private)
Branch protection: `main` is protected — direct pushes blocked for experimental work.
