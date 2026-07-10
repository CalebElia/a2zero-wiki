# A2Zero Wiki — Action Plan

*Derived from `docs/project-evaluation-2026-07-09.md`. Each item lists status, why it matters, concrete steps, and files touched. Work top to bottom within "Now" unless noted; items are otherwise independent of each other except where a dependency is called out.*

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

## Item 1: World-time grounding — DONE (2026-07-09, `feat/world-time-grounding`, commit `3768899`)

**Why:** The digest and every strategy's `synthesis.year-over-year-arc` currently narrate ingest dates ("across a2zero-year1 through a2zero-year5, 2026-06-25 to 2026-07-02") instead of the real 2019–2025 program history. For a project whose product is "how did this unfold, so another city can replicate it," this inverts the wiki's core asset. This is upstream of almost everything else on this list — the eval harness, the commitment ledger, and the timeline all need real dates to be meaningful, so it goes first.

**Dependency note:** Read `docs/architecture/strategy-foundation-progression.md` and `docs/architecture/knowledge-synthesis-architecture.md` before touching `pass1b_synthesize.py` or `phase_c_synthesize.py` per CLAUDE.md's standing instruction. Per CLAUDE.md's dev workflow, this is a "bigger experiment" (touches ingest + synthesis prompts) — use a feature branch, not direct commits to `main`.

- [x] **1.1 — Add real-world period metadata to source frontmatter.** Add `covers-period-start` / `covers-period-end` (or a single `covers-period: [YYYY-MM, YYYY-MM]`) to the YAML frontmatter of all 6 `wiki/sources/**/*.md` pages. Determine actual reporting periods from each source document's own text (CAP-2020 published 2020; annual reports each cover one program year — confirm exact month ranges by reading the source bodies, don't guess from filenames).
- [x] **1.2 — Wire period metadata into Pass 0.** Update the YAML-injection step in `pipeline/orchestrator.py` (Pass 0 copy+inject) so future sources require or prompt for `covers-period` at ingest time, rather than relying on manual backfill forever.
- [x] **1.3 — Update Pass 1B and Phase C prompts to use real periods, not ingest dates.** In `pipeline/pass1b_synthesize.py` and `pipeline/phase_c_synthesize.py` (`build_strategy_synthesis`), change the prompt instructions so `year-over-year-arc` narration is anchored to each source's `covers-period`, not `ingest_date`/`last-updated`. Audit `extract_ingest_history` (referenced in CLAUDE.md's strategy-foundation-progression section) — it currently returns ingest dates; it needs to also carry each source's real period.
- [x] **1.4 — Regenerate synthesis with the corrected grounding.** Re-run `python -m pipeline.phase_c_synthesize --wiki-root wiki` (all 7 strategies + digest) once 1.1–1.3 land, so `synthesis.year-over-year-arc` and the digest's cross-strategy narrative reflect real dates. Diff the before/after digest to confirm the ingest-date phrasing is gone.
- [x] **1.5 — Spot-check output.** Read the regenerated Strategy 1 and Strategy 7 pages plus `wiki/digest.md`; confirm no residual "a2zero-year1 through a2zero-year5 (2026-...)" phrasing remains anywhere in `wiki/strategies/` or `wiki/digest.md`.
- [x] **1.6 — Add a regression test.** Add a test (likely in `tests/test_holistic_synthesizer.py` or a new `tests/test_phase_c_synthesize.py` case) asserting that generated arc/digest text does not contain ingest-date patterns when real `covers-period` data is present — guards against this regressing silently again, the same way the Foundation/Progress bug did.
- [x] **1.7 — Update CLAUDE.md / SCHEMA.md** with the new `covers-period` frontmatter field on source pages, following existing documentation conventions.

**Exit criteria:** every strategy page's `synthesis.year-over-year-arc`, `wiki/digest.md`'s cross-strategy synthesis, and the entity map's `arc:` lines narrate real 2019–2025 program history; test suite green; a test exists that would catch a future regression to ingest-date narration.

---

## Item 2: Anticipated-event lifecycle & duplicate resolution — DONE (2026-07-09, `feat/event-dedup`)

**Why:** Three pages currently exist for one event (the SEU authorization vote) plus a duplicated 2020-03-20 meeting across two directories — a structural pattern (annual reports announce future events, next report describes them happening) that will get worse once council minutes and news are ingested.

- [x] **2.1 — Manual cleanup now.** Merge `wiki/political-events/2024-11-01-ann-arbor-seu-authorization-vote.md` and `2024-11-05-ann-arbor-seu-authorization-vote.md` into one page (keep the more complete 11-05 version, redirect/alias the 11-01 slug); decide whether `november-2024-seu-ballot-question.md` (the anticipatory year4 page) should be merged in or marked superseded via the alias registry. Resolve the 2020-03-20 meetings/political-events duplicate the same way.
- [x] **2.2 — Add `status: anticipated | occurred` to the political-event schema** (`SCHEMA.md` + `_pages.py`/`_models.py` validation) so forward-looking mentions ("voters will decide in November 2024...") are marked distinctly from confirmed outcomes.
- [x] **2.3 — Add a "resolve-pending" field to the Comprehend integration plan** (`pass1a_comprehend.py`) so next-year ingests can look up prior `anticipated` events and update them in place instead of creating new pages.
- [x] **2.4 — Add a semantic-lint heuristic** in `phase_b_lint.py --semantic`: same `event-type` + overlapping `programs-authorized` + dates within ~60 days ⇒ propose merge (currently semantic lint likely relies on title/body fuzzy matching, which date-prefixed slugs defeat).
- [x] **2.5 — Regression test** covering the merge heuristic against the exact SEU-vote fixture pattern.

**Follow-on (not in the original scope, done 2026-07-09 on `feat/ontology-nesting`):** the same review session surfaced a broader ontology-nesting gap (Plan→Strategy→Initiative→sub-initiative containment) — see `docs/architecture/ontology-nesting-model.md`.

---

## Next — Item 3: Resurrect contradiction tracking

**Why:** `contradicts` already exists in the integration-plan schema and is unsurfaced; wiki-v1 had 3 real contradiction pages, current wiki has 0 after 6 sources. This is the highest-value content type for a replication-playbook product and the plumbing is 90% built.

- [ ] **3.1 — Surface non-empty `contradicts` entries** from the integration plan into `review-queue.md` as a new lint-queue section (extend `phase_b_lint.py`).
- [ ] **3.2 — On human approval, write `wiki/contradictions/<slug>.md`** following the schema already defined in `SCHEMA.md`, citing both conflicting sources.
- [ ] **3.3 — Backfill the 3 known v1 contradictions** (Wheeler MW discrepancy, Solarize MW scope, facility audit counts) by porting them from `archive/wiki-v1/wiki/contradictions/` and re-verifying against current entity pages/sources.
- [ ] **3.4 — Sweep current digest `open-questions`** for latent contradictions already noted in prose (e.g. numbers that don't reconcile across annual reports) and promote the clearest 2–3 to formal contradiction pages as a proof of the pipeline.

---

## Next — Item 4: Golden-question eval harness

**Why:** Nothing currently measures whether the wiki actually answers questions correctly; the "compounding knowledge" property is unverified. This should land before further pipeline changes so those changes can be judged against it.

- [ ] **4.1 — Write 30–50 golden questions** with source-verifiable answers, spanning: easy lookups ("What % did the SEU vote pass with?"), cross-source arcs ("How did Solarize MW grow year over year?"), cross-strategy synthesis ("What blocks 100% renewable grid?"), and negative controls (questions the wiki should say it can't answer).
- [ ] **4.2 — Build a scoring harness** — run an agent against the vault per question, score citation-backed accuracy (correct / partially correct / wrong / hallucinated-citation).
- [ ] **4.3 — Wire it into the ingest cycle** as an optional post-Phase-C check, so future pipeline/prompt changes ("did the digest rewrite help?") have an objective before/after comparison.
- [ ] **4.4 — Run baseline now**, before Item 1's world-time fix and before Item 5's digest rewrite, to get a "before" score for comparison.

---

## Next — Item 5: Fix the digest's weakest layer

**Why:** The digest is injected into every Comprehend pass, so its quality compounds. Currently: boilerplate arc skeletons repeated across all 7 strategies, ~15 hedge-words ("appears to"), and `core-actors` populated for only 1 of 7 strategies — gutting the entity map's recall function.

- [ ] **5.1 — Make `core-actors` deterministic.** Replace the LLM-selected list with a computed top-N by backlink/mention count per strategy from the wikilink graph (script or `phase_c_synthesize.py` helper) — frees LLM budget for narrative sections.
- [ ] **5.2 — Add a Phase C validator rule** rejecting arc/narrative text with zero digits (blunt hedge-killer, consistent with the existing validate→revise loop in `phase_c_validate.py`).
- [ ] **5.3 — Re-run Phase C** after 5.1–5.2 and diff for reduced boilerplate/hedging and populated `core-actors` across all 7 strategies.
- [ ] **5.4 — Depends on Item 1.** Do this after world-time grounding lands, since arc text will be regenerated twice otherwise.

---

## Later — Item 6: Structure quantitative outcomes

**Why:** Numbers like "5.4 MW," "$10,000,000," "262 homes" exist only as prose today — not queryable. This also feeds the eval harness (Item 4) with ground truth.

- [ ] **6.1 — Add a `measurements:` frontmatter field** to the initiative page schema: list of `{metric, value, unit, as-of, source}` objects (`SCHEMA.md` + `_models.py` validation).
- [ ] **6.2 — Build a targeted extraction pass** over existing initiative page bodies (the numbers are already written in prose) to populate `measurements:` retroactively — one-time backfill script, similar in spirit to `_legacy/enrich_strategy_links.py`.
- [ ] **6.3 — Wire `measurements:` extraction into Pass 2 (LDP)** so future ingests populate it going forward without another backfill.

---

## Later — Item 7: Repo hygiene sweep

**Why:** Small but compounding drift that costs future contributors (including future Claude sessions) time.

- [ ] **7.1** `git rm -r --cached tests/__pycache__` and confirm `.gitignore` actually excludes it (currently tracked despite CLAUDE.md forbidding it).
- [ ] **7.2** Correct CLAUDE.md's test count (currently says 137/152 in two places; actual is 349 passed + 1 skipped).
- [ ] **7.3** Either implement `wiki/hot.md` (documented as rebuilt every Pass 3, doesn't exist) or remove the doc references to it.
- [ ] **7.4** Decide `meta/dossiers/` tracking status (currently untracked/`??` in git status) — commit or gitignore deliberately.
- [ ] **7.5** Decide the fate of the paused quad pipeline (`blackboard/`, `_legacy/quad_linter.py`, `_legacy/registry.py`, quad schema in `_models.py`): either name a concrete downstream consumer and revival timeline, or archive/delete it.

---

## Later — Item 8 (structural, not urgent): De-hardcode the 7-strategy assumption

**Why:** Grapevine's thesis is multi-city; "7 strategies" is currently baked into prompts, `phase_c_synthesize.py`, and the digest structure. Not urgent while single-city, but the longer it hardens the more expensive the eventual generalization.

- [ ] **8.1** Extract the strategy list/taxonomy into a config file (e.g. `wiki/strategy-taxonomy.json` or similar) read by `phase_c_synthesize.py` and the Pass 1B prompt, rather than being a hardcoded constant/count.
- [ ] **8.2** Confirm nothing else (tests, prompts, `SCHEMA.md`) assumes exactly 7 as a magic number.

---

## Novel directions (separate track — pursue opportunistically, not blocking the above)

- [ ] **A. Commitment ledger.** Resurrect v1's `commitments/` concept: extract each source's explicit next-year commitments once, then mark them `delivered / slipped / rescoped / vanished` with evidence on each subsequent ingest. Highest-value replication signal identified in the review.
- [ ] **B. Draft a playbook card now** (e.g. Solarize or SEU) as a forcing function — preconditions, timeline, costs, staffing, failure modes, transferability caveats — to surface which schema fields are missing before speculating further.
- [ ] **C. Typed dependency relations** (`enables` / `blocked-by` / `funded-by`) in the relationship lexicon, replacing prose-only statements like "adoption can only move as fast as financing allows."
- [ ] **D. `perspective:` frontmatter field** (`self-reported | deliberative | third-party`) on source pages — design before the first council-minutes/news ingest, not after.
- [ ] **E. Ingest one small second corpus** (e.g. another Ann Arbor plan with its own taxonomy) as a cheap stress test of the single-city assumptions in Item 8, before more infrastructure hardens around exactly 7 strategies.

---

## Sequencing rationale

1. **Item 1 (world-time)** first — fixes what the wiki *says*; everything downstream (eval harness ground truth, commitment ledger dates, timeline) needs real dates.
2. **Item 4 (eval harness)** early — baseline now, re-measure after Items 1 and 5, so every subsequent change is judged against evidence rather than intuition.
3. **Items 2, 3, 5** can proceed in parallel once Item 1 lands (Item 5 explicitly depends on it; Items 2 and 3 don't).
4. **Items 6, 7, 8** and the novel-directions track are lower urgency and can be picked up opportunistically.
