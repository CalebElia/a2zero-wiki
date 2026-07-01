# Content Quality Audit — 2026-06-30

*Triggered by: post-Year-3-ingest review. Full audit performed by a dedicated read-only agent pass over all 4 sources (cap-2020.md, annual reports Y1–Y3) against extracted wiki content. Root-cause tracing for Issue 1 performed via direct code + git-history inspection.*

Structural health (links, tests, registry) was already confirmed clean in the 2026-07-01 health check. This audit is content-quality only: factual fidelity, genericness, hallucinated synthesis, and completeness.

---

## Issue 1 — Strategy pages lose foundational content on each ingest (SERIOUS)

**Status:** open — root cause identified, fix not yet implemented.

**Symptom:** All 7 `wiki/strategies/*.md` pages currently contain zero references to `cap-2020` (`grep -c "cap-2020" wiki/strategies/*.md` → 0 across the board). Prior to the Year 3 ingest, `strategy-1-renewable-grid.md` contained CAP-2020's foundational content: the 41%-of-emissions target, ~$4.1M cost estimate, Community Choice Aggregation as the dominant mechanism, the 2030 100%-renewable target. That content is gone. Confirmed via `git log -p` on the strategy pages — this is regression, not an original gap.

**Root cause (traced 2026-06-30):**

`pipeline/pass1b_synthesize.py`'s Writer prompt contains an explicit fact-preservation instruction (line 73–82):
> "READ-UNDERSTAND-INTEGRATE (applies when EXISTING STRATEGY WIKI CONTENT is provided): ... Preserve all prior facts — they came from earlier sources and are still true ... Do NOT discard prior synthesis"

But this instruction is conditional on the `[EXISTING STRATEGY WIKI CONTENT]` block being present in the prompt — and that block is only injected in the **legacy fallback path** (line 355, `else:` branch), which only fires when `digest_content` is `None` (i.e., no digest exists yet — the first-ingest case).

Once `wiki/digest.md` existed (after the Year 2 ingest), every subsequent Pass 1B call took the `if digest_content:` branch (line 346) instead, which injects only the ~83-line compressed digest with a much weaker instruction: "Build on it rather than re-stating known facts." The Writer never sees the actual full prior strategy body text again — only a lossy summary of it.

Compounding this: `_write_synthesis` (line 514–528) performs an unconditional full-body replace (`_replace_wiki_page_body`) regardless of whether the page was a stub or had substantial prior content — the `is_stub_only` branch and the "integrate" branch call the exact same function with the exact same arguments. There is no merge; there is only "regenerate from (lossy digest + new source) and overwrite."

**Net effect:** since the digest went live, strategy pages are being reconstructed each ingest from an increasingly compressed summary rather than the accumulated prose. Facts absent from the digest (which is itself only ~4-6k tokens, cross-strategy, narrative-focused) are permanently lost the moment they drop out of a digest rebuild. This is the opposite of the architecture's stated goal (`docs/architecture/knowledge-synthesis-architecture.md`) — compounding knowledge, not compounding forgetting.

**Secondary symptom, same root cause:** every strategy page's `year-over-year-arc` frontmatter field says "no multi-year trend data yet ingested" despite 3 years of ingested reports and despite the page's own prose discussing multi-year progression. This stale field flows verbatim into `digest.md`, so the next Comprehend pass will read a false claim about the wiki's own state as ground truth.

**Fix approaches:** see decision below.

---

## Issue 2 — Potential duplicate funding event (MODERATE)

**Status:** open — needs source-text re-verification before any merge action.

`wiki/funding-events/michigan-utility-pole-ev-2022.md` ($54,000, State of Michigan, "Utility-Pole EV Charging Pilot," sourced from Year 2's grant list) and `wiki/funding-events/michigan-ev-charger-grant-2023.md` ($54,000, State of Michigan, sourced from Year 3, describing itself as "the State's first utility pole EV charging program") plausibly describe the same award reported in two consecutive annual reports. Both claim "first" for essentially the same program. If real, an un-flagged duplicate risks double-counting $54K in any future funding aggregation.

**Not yet confirmed** — requires precise side-by-side re-read of the exact source passages in `a2zero-year2.md` and `a2zero-year3.md` (grant name, exact dollar figure, award date vs. implementation date) before deciding merge vs. keep-separate. Semantic lint's near-duplicate detection did not catch this pairing during the last lint pass — worth understanding why (different initiative-slug linkage on each page may have suppressed similarity scoring).

---

## Issue 3 — Templated/boilerplate entity pages (MODERATE, scope unknown)

**Status:** open — confirmed on a small sample, breadth across the full actor corpus (127 pages) not yet measured.

Confirmed identical (name-swapped only) boilerplate on:
- `wiki/actors/chip-ackerman.md` / `wiki/actors/jeff-bannister.md` — identical council-member bio sentence
- `wiki/actors/ginger-deli.md` / `wiki/actors/el-harissa-market-cafe.md` / `wiki/actors/zingermans-next-door-cafe.md` — identical A2R3 program sentence

In both cases the content is factually accurate to source (the source itself lists these entities together in a shared sentence) — the question is whether this is an acceptable reflection of genuinely repetitive source material, or a symptom of a prompt pattern that under-differentiates entities more broadly across the corpus. Scope not yet measured beyond these 5 pages.

---

## Issue 4 — Missing content (confirmed + likely more)

**Status:** open — specific known gaps identified; full CAP-2020 sweep not yet performed (agent audit only "read strategically," not exhaustively, given the source is 4,283 lines).

Confirmed missing (grep-verified, present in source, absent everywhere in wiki):
- **ICC Building Code Committees** (Year 1): *"Worked with the International Code Council (ICC) to introduce Building Code Committees and volunteered to serve on these committees."*
- **SolSmart Silver designation** (Year 1) — was present in the pre-Year-3 strategy-1 body (same content-loss mechanism as Issue 1), now absent everywhere.
- **92-organization Year-1 collaborator baseline** — `a2zero-collaborators-network.md` now starts its milestone history at Year 2's 110 orgs; the Year 1 baseline dropped.
- **Consumption-based emissions inventory cohort** (Year 1) — not found under that phrasing anywhere; needs confirmation it isn't captured under different wording before treating as missing.

**Not yet done:** a systematic pass through all 7 CAP-2020 strategy sections (the 4,283-line foundational document) checking for concrete initiatives/figures/programs with no wiki trace. The initial audit sampled this source strategically rather than exhaustively, given its size — a dedicated follow-up pass is warranted, especially since Issue 1's root cause means CAP-2020-sourced facts are the most likely to have been silently dropped.
