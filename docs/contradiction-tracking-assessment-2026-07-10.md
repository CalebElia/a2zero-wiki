# Contradiction Tracking — Value Assessment & Retroactive Backfill Plan

*Prepared 2026-07-10, ahead of action-plan Item 3. Covers: what v1 built, what v2 already has, why v2 has produced zero contradiction pages across 6 ingests despite having the schema, three source-verified live examples of currently-unflagged contradictions, and a recommended path to both backfill and fix the underlying gap.*

---

## 1. What v1 had

`archive/SCHEMA_wikiV1.md` defined `contradiction` as page type #4, with a blunt, mandatory step in the ingest workflow itself (not optional, not a separate lint pass):

> "**Check for contradictions.** Compare any numeric claims (counts, dollar amounts, percentages, dates) against existing wiki pages. If two reports disagree, create a `contradiction` page rather than silently picking one."

Three pages exist in `archive/wiki-v1/wiki/contradictions/`, and they're genuinely good — not pedantic number-matching, but structured analytical writeups:

- **`wheeler-center-mw-discrepancy.md`** — CAP-2020 and Year 1 say 24MW for the landfill solar project; Years 2–4 consistently say 20MW. The page lays out three possible explanations (right-sized design, deferred phase, different site footprint) and states plainly: "Track Year 5 — if a final design... is announced with a specific MW capacity, that will be the definitive number."
- **`solarize-mw-scope.md`** — Year 5's own report contains three irreconcilable solar figures (5.4MW Solarize-only, 6.5MW "since A2ZERO adoption," 11.88MW "dashboard") and states the practical stakes directly: at 5.4–6.5MW the city is at 7–8% of the 78MW 2030 target; at 11.88MW it's at 15%. "The difference matters for Year 6 planning."
- **`city-facility-audit-count.md`** — Year 1 says 6 facilities audited; Year 2 says 4; Year 4 says 6 again. The page tracks the ambiguity across four annual reports, updating its own best-guess interpretation as each new report arrives, without ever forcing false certainty.

Every page follows the same shape: conflicting claims side by side with exact citations, a "why it matters" section tying the ambiguity to something a reader would actually act on, and a best-guess explanation that stops short of inventing resolution the sources don't support.

## 2. What v2 already has — this is not a missing-schema problem

I expected to find the `contradiction` type absent or half-specified. It isn't:

- `registry/valid_page_types.json` includes `contradiction`.
- `SCHEMA.md`'s current `### contradiction (Pass 2, low threshold)` section is, if anything, more permissive than v1's: *"Flag any detectable tension... The threshold is low: if something feels like tension rather than clear contradiction, create the page anyway."*
- `pipeline/pass2b_extract.py`'s `WIKI_PAGES_SYSTEM` prompt has a full `6. CONTRADICTION` block with the exact frontmatter schema (`sources`, `cross-source`, `status`, `related-initiatives`) and body instructions matching v1's format.

So the type, the schema, and the extraction instructions all exist today, in the live prompt, on every ingest. And yet: **zero contradiction pages exist anywhere in the current wiki**, across 6 ingested sources covering the same reports v1 caught 3 real conflicts in.

## 3. Root cause: the prompt's dominant instruction actively discourages finding them

The `contradicts` field described in `docs/architecture/knowledge-synthesis-architecture.md` as part of the Comprehend integration plan was never actually implemented (`pipeline/pass1a_comprehend.py`'s real `empty_plan()` has no such key) — and `docs/architecture/comprehend-plan-write.md` explains why: contradiction detection was deliberately assigned to LDP (Pass 2), not Comprehend, because "the Write pass sees both the new claim AND the existing page body and can spot conflicts directly."

That's the right call in principle — LDP *does* get both pieces of information. Here's the actual injection point (`pipeline/pass2a_chunk_loop.py:322-327`):

```
[RETRIEVED ENTITY PAGES — integrate new findings into these]
--- initiatives/wheeler-center-solar-park ---
<existing body, currently saying 20MW>
[END RETRIEVED ENTITY PAGES]
```

And the system prompt's governing instruction for what to do with that block (`WIKI_PAGES_SYSTEM`, `pipeline/pass2b_extract.py:36-47`, the **READ-UNDERSTAND-INTEGRATE** section):

> "Preserve all prior facts (they came from earlier sources and **are still valid**)... Your body content **REPLACES** the existing body — write a complete whole, not an appendage"

This is the instruction the model is actually primed by at the exact moment a contradiction would become visible — old fact and new fact sitting side by side in context — and it tells the model the old fact is "still valid" and to produce one smooth replacement body. There is no branch in this instruction for "if the new number conflicts with the old number, keep both and flag it instead of merging." The `CONTRADICTION` type definition exists, but it's item 6 of 9 in a much longer prompt, disconnected from the specific block where the LLM is holding two conflicting numbers in its hands. The instruction actively pointed right past the type that exists to catch this.

This is a structural gap, not a threshold-tuning problem — no amount of "flag tension aggressively" language in the `CONTRADICTION` section fixes it if the block that actually presents the conflicting evidence tells the model, in the same breath, to smooth it into one replacement narrative.

## 4. Proof: three live, currently-unflagged contradictions in today's wiki

I didn't take this on faith — I re-verified all three v1 cases against the current sources and current pages.

**Wheeler Center MW — still live, still unresolved as of Year 5.**
- `wiki/sources/cap/cap-2020.md:712`: *"By the end of 2023, a **24MW** solar installation is fully operational at the former Ann Arbor landfill..."*
- `wiki/sources/annual-reports/a2zero-year1.md:28`: *"studies on the feasibility and cost of a **24MW** solar installation..."*
- `wiki/sources/annual-reports/a2zero-year2.md` onward: consistently **20MW**.
- `wiki/strategies/strategy-1-renewable-grid.md`'s frozen **Foundation** section (correctly) still says *"a 24 MW landfill solar project by 2030"* — CAP-2020's original figure, preserved as designed.
- `wiki/initiatives/wheeler-center-solar-park.md`'s current body says only **20MW**, with zero mention that the original target was 4MW higher. The two pages in the same wiki, both currently live, disagree — and nothing links them.
- I checked Year 4 and Year 5 for a resolution: Year 4 secures $5M and "continues strategizing"; Year 5 doesn't mention the project's capacity at all. The discrepancy v1 flagged is **not stale** — it is exactly as unresolved today as it was when v1 caught it.
- The digest's own Strategy 1 `open-questions` field already senses this, in vague unanchored form: *"Whether the landfill solar concept advances to full development and at what scale."* The synthesis layer is already circling the ambiguity; it just has nowhere precise to put it.

**Solarize MW scope — all three figures present in the source, only two survive to the page, and neither survival is flagged as scope-ambiguous.**
- `wiki/sources/annual-reports/a2zero-year5.md`: 5.4MW (Solarize only), 6.5MW ("since A2ZERO adoption"), 11.88MW ("dashboard reports"). All three, verbatim, same report.
- `wiki/initiatives/solarize-ann-arbor.md`'s current body: cites 5.4MW and 6.5MW back to back as if they're just two data points on a continuum — no flag that a third figure (11.88MW, more than double 5.4MW) exists for the same reporting year with no stated reconciliation. The 78MW-target math v1 called out (7–8% vs. 15% progress) is exactly as live today.

**Facility audit count — a related but distinct finding: this one is a *recall gap*, not (only) a contradiction-detection gap.**
- Year 1: "6 City facilities" audited. Year 2: "4 City facilities." Year 4: "six municipal facilities."
- `wiki/initiatives/municipal-building-decarbonization-audits.md`'s `source-first-seen` starts at **Year 3** — Year 1's "6 facilities" claim doesn't appear on any current page at all. This isn't a case of two facts being smoothed into one; it's a case of one fact never being captured. Worth fixing, but it's a job for the deterministic-recall-floor mechanism (already built, `pipeline/recall_scan.py`), not the contradiction-detection prompt fix below. I'd track it separately rather than force it into Item 3's scope.

## 5. Is this worth doing — real value, or busywork?

Real value, and concretely so, not just "more content for its own sake":

- **It changes an assessed number, not just adds a caveat.** Whether Solarize progress reads as 7% or 15% of the 78MW target is not cosmetic — it's the actual number a replication consultant or a city council member would use to judge whether the program is on track. Smoothing it into flat prose doesn't just lose nuance, it silently picks a number.
- **It's the layer no other page type can hold.** Annual reports are self-congratulatory by construction (CLAUDE.md's own framing of the Grapevine thesis leans on this). The tension between what CAP-2020 promised (24MW) and what got built (20MW, unconfirmed even 5 years later) is exactly the kind of signal a city considering replication needs and won't get from reading any single source in isolation — it only exists by comparing sources, which is this wiki's whole reason for existing over a flat document index.
- **The synthesis layer is already half-finding these on its own.** The digest's `open-questions` already contains language that's clearly circling real, specific, citable discrepancies (the Wheeler example above) without ever landing on them. That's wasted signal sitting one inference-step away from being useful.

## 6. Recommendations

**6.1 — Fix the prompt gap so future ingests stop silently smoothing conflicts.**
Add an explicit conflict check directly adjacent to the `[RETRIEVED ENTITY PAGES]` injection point and the READ-UNDERSTAND-INTEGRATE instruction — not just relying on the disconnected `CONTRADICTION` type definition six sections later. Something like: *"Before merging, compare any specific number (MW, dollar amount, percentage, count, date) in the new chunk against the retrieved existing body. If they refer to the same fact but disagree, do NOT silently pick one — keep both in the integrated body and additionally emit a `contradiction` page citing both."* This is a prompt change plus a regression-test fixture (two synthetic sources with a conflicting number, assert a contradiction page gets emitted) — small, contained, and the natural first step since it's what makes Item 3 self-sustaining rather than a one-time archaeology exercise.

**6.2 — Retroactive backfill of the 3 known cases, updated to current schema and current data.**
Port `wheeler-center-mw-discrepancy.md` and `solarize-mw-scope.md` directly — both are still live and unresolved as of Year 5, verified above. `city-facility-audit-count.md` should be backfilled too, but flagged as `cross-source: true` with a note that Year 1's "6 facilities" claim may need a `recall_scan.py` pass first to confirm it's genuinely absent everywhere before writing the contradiction body (don't want the contradiction page to be the *only* record of a fact that should also have its own citation on the initiative page).

**6.3 — A bounded one-time "contradiction sweep," not a full re-ingest.**
Rather than re-running extraction on all 6 sources, run a scoped LLM pass over the ~15–20 initiative pages with the highest quantitative density (solar/MW, GHG %, dollar costs, participation counts, facility counts — the same category as all 3 known cases) comparing each page's current synthesized numbers against a fresh read of every source that cites it. This is structurally the same shape as the existing lint passes (`phase_b_lint.py`) — I'd add it as a new `--contradiction-sweep` mode there rather than a one-off script, since it reuses the existing `contradiction` schema and review-queue human-gate pattern the project already trusts. Recommend running this *once* now as the backfill mechanism, then relying on 6.1's fixed prompt for everything going forward.

**6.4 — Treat the digest's `open-questions` as a lead list, not just prose.**
Several current open-questions are already unwittingly pointing at citable discrepancies (the Wheeler example). A cheap follow-up: when writing `open-questions` in Phase C, cross-check candidate phrasing against known numeric-figure clusters per entity and flag matches for human review as contradiction candidates — lower priority than 6.1–6.3, but a natural way to keep surfacing new ones without a dedicated sweep every time.

## Sequencing

Do 6.1 first (it's what makes the fix durable), 6.2 next (cheapest, highest-confidence, already fully verified above), then 6.3 (bounded cost, catches what the known 3 don't). 6.4 is opportunistic, not blocking.
