# Semantic Lint — Rename Detection, Safe Redirect, Cycling Fix

## Closing the Rename-Drift Blind Spot in Duplicate Detection

*Spec drafted 2026-07-10; implemented 2026-07-10 on `feat/rename-detection-lint`. Supersedes the original two-proposal draft — see "What changed from the draft" below.*

---

## The problem

`semantic_lint()` (`pipeline/phase_b_lint.py`) finds duplicate pages in two stages: a cheap title-similarity filter (`fuzzy_candidates`, `difflib` ratio, gated at 0.65) proposes candidate pairs, then an LLM verdict call decides same/distinct/succession. Nothing reaches the LLM unless its **title** survives that gate first.

This is structurally blind to **rename drift**: a page whose title changes entirely as a project moves proposal→implementation. Found 2026-07-10 during a contradiction sweep: `initiatives/landfill-solar-project.md` (CAP-2020's proposal-stage name) and `initiatives/wheeler-center-solar-park.md` (the concrete name once design began) are the same real-world project. Their titles score:

```
difflib.SequenceMatcher(None, "landfill solar project", "wheeler center solar park").ratio() = 0.47
```

Below the 0.65 gate — the pair never reached the LLM, even though `landfill-solar-project.md`'s own body already stated the rename in prose: *"also referred to as the Wheeler Center Landfill Solar Project and later the Wheeler Center Solar Park."* A prior synthesis pass recognized the rename and wrote it down; nothing downstream consumed it.

Two adjacent issues surfaced during investigation and are fixed here:

- **No safe apply path for renames.** Every approved merge runs a full LLM body-merge (`pass2c_merge.merge_pages`, up to 8192 output tokens) even to fold a thin proposal-era stub with nothing worth reconciling.
- **A live re-proposal cycling bug.** `semantic_lint()` re-derives candidates from raw page state every run; `KEEP_SEPARATE` was not even parsed by `_parse_approved_proposals()` and was silently dropped by `_cleanup_review_queue()`; `merge-log.jsonl` recorded only *positive* actions. A pair a human marked KEEP_SEPARATE re-proposed indefinitely.

---

## What shipped

### 1. Rename-phrase scanner — `--alias-phrases` (near-zero LLM cost)

`alias_phrase_lint(wiki_root)` scans every page body for rename cue phrases (`also referred to/known as`, `later the …`, `now called/known as …`, `renamed to/as …`), captures the **title-case proper-noun run(s)** after each cue, and splits any captured span on chaining conjunctions (`and later`, `and now`) so a chained "X and later Y" yields both X and Y. Each candidate name is fuzzy-matched (`fuzzy_candidates`, threshold 0.75 — tighter than 0.65 since the phrase is already a strong prior) against titles of *other* pages in the same type directory. A hit emits an `ALIAS_DETECTED` proposal to `review-queue.md`, with the source sentence as evidence. **No per-candidate LLM call** — the whole pass is regex + stdlib fuzzy match.

Direction is deterministic: the phrase-containing page is the old name (redirect source); the matched page is canonical (survivor). The scanner consults the keep-separate store (below) and skips already-decided pairs.

**Corrected capture (the key fix):** the draft's single greedy `([^,.;()]+)` capture grabbed the whole chained clause as one blob → **0.47** fuzzy score, *missing its own motivating example*. Anchoring capture on a title-case run and splitting on chaining conjunctions yields `"Wheeler Center Solar Park"` → **1.00**. Title-case anchoring also rejects non-name constructions ("also referred to as **a** pilot program" — lowercase).

Run once against the live wiki: exactly one proposal (the landfill→wheeler pair), zero false positives across the whole corpus.

### 2. Safe REDIRECT apply action + deterministic content-preservation safeguard

On approved `APPROVE_REDIRECT`, `apply_proposals()` runs a deterministic containment check: is every substantive (≥5-word) sentence of the old page — wikilinks/citations stripped so differing citations don't mask shared facts — already present in the canonical page?

- **Contained → safe REDIRECT (no LLM):** rewrite inbound links (`_rewrite_inbound_links`), register a `name-variant` alias (`add_alias`), append merge-log, delete the old page.
- **Old page has unique facts → automatic fallback to the full LLM MERGE** (`merge_pages`), which preserves both bodies. Never a silent delete.

The check errs toward MERGE on any doubt — a false merge costs one LLM call, a false redirect loses content, so the conservative bias is correct. The human approves "resolve this rename"; the system picks redirect-vs-merge by whether content would be lost. (Git history is a backstop, not the primary safeguard.)

### 3. Durable KEEP_SEPARATE memory (fixes the cycling bug)

Approving `[x] KEEP_SEPARATE` (or `DISMISS`) now records the decided page-pair durably as a `KEEP_SEPARATE` action in `registry/merge-log.jsonl` (reusing the append-only audit log, no new file). `_load_keep_separate_pairs()` reads them slug-keyed (so suppression survives a later rename), and `semantic_lint()` + `alias_phrase_lint()` skip any decided pair before the LLM verdict / before emitting. A rejected pair is never re-proposed.

Invalidation (v1): suppress by page-pair identity until a human clears the log entry. If both bodies later change materially a stale suppression could persist — a v2 refinement, not built.

### Pass ordering

`--staleness` → **`--alias-phrases`** (cheapest, highest-precision, evidence-based) → `--semantic` → `--backlink` → `--structural`.

---

## What changed from the draft (and why Proposal 1 was dropped)

The original draft proposed a second detection path: **IDF-weighted tag-token structural pairing** for `initiatives/` (widen candidates by rare shared tag tokens, feeding the same LLM verdict). It was dropped after measurement:

- Tag-overlap candidates are **~99% net-new** — only 3–5 of them overlap with what fuzzy-title already catches, so the pair count is almost entirely *added* LLM verdict cost.
- Catching the motivating landfill/wheeler case requires `max_doc_frequency ≥ 4` (its only discriminating shared token, `landfill`, has corpus frequency 4) → **~330 net-new LLM verdict calls per `--semantic` run** (449 at the draft's default cap of 5), growing with corpus size.
- That's heuristic-limited recall *with* LLM-verdict cost — and it just catches cases the near-free rename scanner (Proposal 2) already catches.

**Embeddings are the correct breadth play, deferred to a separate future project.** Cost structures invert: one embedding call per *changed* page (~1000× cheaper than an LLM verdict call, cacheable) + local cosine similarity (~free) as a high-recall pre-filter, with only the top-K genuinely-similar pairs sent to the LLM verdict. Embeddings would also catch landfill/wheeler (semantically close despite low edit distance). The original spec deferred embeddings citing *infrastructure* cost — but at ~500 pages that infra is light (a vector sidecar + one embed call per changed page), and the per-token cost is far below Proposal 1's. When breadth beyond prose-narrated renames is wanted, embeddings — not tag tokens — are the path.

---

## Out of scope

- **Embeddings-based similarity** — the deliberate next breadth project (see above). Keep as the fallback if the rename scanner's prose-narration requirement proves too narrow once more sources are ingested.
- **Extending the scanner or a structural pass to a per-ingest-scoped mode** — `semantic_lint`/`alias_phrase_lint` currently run over the whole corpus each invocation (the scanner is cheap enough that this is fine). Per-ingest scoping matters mainly for an expensive pass like the dropped Proposal 1; revisit only if embeddings land and need it.
