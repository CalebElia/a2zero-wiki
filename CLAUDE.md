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
  topics/               ← Aggregate/curated synthesis pages (human-promoted from topic-candidates)
  meta/                 ← Governance files (schema-drift.md, topic-candidates.md, relationship-lexicon.md)
  index.md              ← Auto-rebuilt by Pass 3
  log.md                ← Append-only ingest log
  hot.md                ← Most-recent session summary (overwritten each Pass 3)
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
python -m pipeline.run_ingest source \
  --source prepared/<type>/<uuid>.md \
  --uuid <uuid> \
  --title "<title>" \
  --quads-path blackboard/quads.jsonl \
  --wiki-root wiki \
  --review-queue review-queue.md \
  --section-maps-dir blackboard/section_maps
```

Optional flags on the `source` subcommand:
- `--wiki-only` — Pass 1 + Pass 2 wiki extraction only; skip quad extraction and review-queue
- `--quads-only` — Pass 2 quad extraction only; skip Pass 1 and wiki writes

**Pass 0 (copy + YAML inject):** Source file copied from `prepared/<type>/<uuid>.md` → `wiki/sources/<type>/<uuid>.md`. If the prepared file has no YAML frontmatter, one is injected (`uuid`, `source_type` inferred from directory, `title`, `ingest_date`).

**Pass 1 (holistic synthesis):** Full-document read. Writer → Evaluator → Editor loop. Produces: overview page, strategy body text, stub pages for all entities mentioned in the document. Uses streaming API (`max_tokens=64000`).

**Pass 1.5 (alias resolution):** Every proposed entity slug is resolved through `registry/entity_aliases.json` before writing. Known aliases redirect to the canonical page and trigger an LLM merge if the canonical page has real content.

**Pass 2 (chunked LDP):** Section-by-section extraction. Each chunk produces actor/initiative/location/political-event/technology/funding-event/meeting pages. Integrates into existing stubs from Pass 1.

**Pass 3 (finalize):** Rebuilds `index.md`, seals `log.md`, overwrites `hot.md`.

Post-ingest linting (on-demand):
```
python -m pipeline.lint_wiki --wiki-root wiki --structural    # broken links, orphans
python -m pipeline.lint_wiki --wiki-root wiki --semantic      # near-duplicate detection (LLM)
python -m pipeline.lint_wiki --wiki-root wiki --backlink      # find missed entity mentions in strategy/overview bodies
python -m pipeline.lint_wiki --wiki-root wiki --apply         # execute approved proposals from review-queue.md
```

One-time enrichment (rarely needed; used after prompt changes):
```
python -m pipeline.enrich_strategy_links --wiki-root wiki [--dry-run]
```

## Pipeline Modules

| File | Role |
|---|---|
| `run_ingest.py` | CLI entry point + three-pass orchestration |
| `holistic_synthesizer.py` | Pass 1 Writer→Evaluator→Editor loop |
| `wiki_writer.py` | Pass 2 chunk extraction (calls LDP for long docs) |
| `ldp.py` | Long-document chunk loop with section maps |
| `wiki_pages.py` | Page primitives (build/write/append) + `VALID_PAGE_TYPES` + quad extraction |
| `wiki_index.py` | Pass 3 helpers: `rebuild_index`, `append_log`, `update_hot` |
| `alias_registry.py` | Pass 1.5 alias resolution |
| `merge_pages.py` | LLM merge for duplicate page bodies |
| `lint_wiki.py` | Post-ingest linting (structural, semantic, backlink, apply) |
| `enrich_strategy_links.py` | One-time pass to inject entity wikilinks into strategy bodies |
| `raw_to_sources.py` | PDF → cleaned markdown (currently paused) |
| `post_ingest.py` + `quad_linter.py` | Quad pipeline review-queue generation (paused pending schema design) |
| `models.py` | `WikiPage` dataclass + quad schema validation |
| `registry.py` | Legacy entity registry (used by quad linter) |

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

**Merge log:** `registry/merge-log.jsonl` — append-only audit trail for every approved entity merge or temporal succession. Each entry: `date`, `action`, `from`/`into` (or `predecessor`/`successor`), `approved-by`. Use `git show <hash>:wiki/<path>.md` to recover any deleted page from git history.

**Review queue:** `review-queue.md` is a live inbox, not an append log. Each lint pass (`--structural`, `--semantic`, `--backlink`) replaces its own section. Annotated proposals (`[x] APPROVE_...` / `[x] KEEP_SEPARATE`) are cleared by `--apply`; unactioned and `DEFER`'d proposals stay.

**Schema drift:** When the LLM encounters an entity that doesn't fit any approved `type:` from `VALID_PAGE_TYPES`, it writes the page using the closest approved type AND adds `proposed-type: <new-type>` to the frontmatter. The pipeline auto-logs an entry to `wiki/meta/schema-drift.md` for HITL review. Approve a proposed type by adding it to `VALID_PAGE_TYPES` in `pipeline/wiki_pages.py`.

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

137 tests, 1 skipped (intentional). If tests break, fix them before continuing — do not bypass.

## Active Architectural Direction

**Read `docs/architecture/knowledge-synthesis-architecture.md` before speccing or implementing any pipeline changes.**

The pipeline is being upgraded to close a fundamental LLM-Wiki design gap: the extraction pass currently has no visibility into existing wiki content, breaking the compounding-knowledge property. The solution is a GraphRAG-inspired synthesis hierarchy:

- **L0** — Entity pages (exists)
- **L1** — Strategy synthesis pages (exist as prose, need LLM-maintained `synthesis:` section)
- **L2** — `wiki/digest.md` — cross-strategy narrative + entity map, injected into every Comprehend pass (~4-6k tokens)

The upgraded ingest cycle: **Phase A** (extraction) → **Phase B** (lint + human review) → **Phase C** (`synthesize_wiki` command rebuilds L1 → L2) → **Phase D** (ready for next ingest). Synthesis must come after lint — the digest encodes the wiki's state and must encode a clean, reviewed state.

Implementation order: `synthesize_wiki` command → digest injection into Comprehend pass → Comprehend/Plan split → strategy `synthesis:` sections.

## GitHub

Repo: https://github.com/CalebElia/a2zero-wiki (private)
Branch protection: `main` is protected — direct pushes blocked for experimental work.
