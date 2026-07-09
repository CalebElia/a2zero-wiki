# A2Zero Wiki — Project Evaluation

*Reviewed 2026-07-09. Covers repo structure, architecture docs, pipeline code, and wiki content across all 516 pages after 6 ingested sources (CAP-2020 + annual reports Year 1–5).*

## Verdict up front

This is a genuinely well-engineered system. The core architectural bet — that a pre-defined strategy taxonomy can replace GraphRAG's community detection, giving a synthesis hierarchy without graph computation — is correct, elegant, and honestly written up. The content compounding is *actually working*: the Sustainable Energy Utility page traces a five-year arc (proposal → options analysis → ballot → 79% authorization → $5M startup funding) with per-source citations from four different documents merged into one coherent narrative. That's the hard thing this project set out to do, and it does it.

The weaknesses are not in the pipeline machinery — they're in the **knowledge model**: time is confused, events duplicate, outcomes aren't structured, contradictions were dropped, and there's no way to measure whether the wiki actually answers questions well. All fixable, and mostly cheaper to fix than what's already been built.

---

## What is genuinely good

**1. The "LLM proposes, deterministic layer verifies, human gates" pattern — applied consistently.** This is the strongest engineering idea in the repo, and it shows up everywhere: the deterministic recall floor (`recall_scan.py`) backstops Comprehend's fallible holistic read with a name-index scan; `phase_c_validate.py` checks every LLM-emitted slug against the filesystem and logs dropped ghosts to `meta/synthesis-ghosts.log`; the chunking gate forces human review of section maps before LDP runs; the alias registry makes entity resolution deterministic once a human approves a merge once. Most LLM-pipeline projects trust the model or distrust it wholesale; this one puts verification at exactly the joints where hallucination enters.

**2. The Foundation/Progress split is a mature response to a real failure.** The 2026-06-30 audit caught strategy pages silently losing CAP-2020 targets on every ingest — a classic LLM-compression death spiral. The fix wasn't a prompt tweak; it was structural: Foundation frozen forever, extracted once deterministically, with a `RuntimeError` guard so the pipeline *cannot* regenerate it. That's the right instinct — turn a content-quality bug into an invariant the code enforces.

**3. Phase ordering rationale (lint before synthesis) is correct and rare.** The insight that the digest encodes wiki state and therefore must encode a *clean, human-reviewed* state — otherwise errors compound into every future Comprehend pass — is the kind of feedback-loop thinking most ingest pipelines miss entirely. The whole A→B→C→D cycle exists to protect the compounding property.

**4. Content quality is high and citation discipline is nearly perfect.** Only 8 of ~500 entity pages lack an inline source citation (all minor federal-agency actor stubs). Strategy 1's Progress Synthesis is dense, specific (5.4 MW Solarize cumulative, $10M Bryant geothermal, 67 sites in Electric Customer Choice, 79% SEU vote), and accumulates rather than compresses. Zero orphaned stubs remain across 516 pages.

**5. Governance surfaces close their own loops.** Schema drift can't rot silently (`SCHEMA_DRIFT_PENDING` resurfaces on every structural lint); query-log entries resurface as `QUERY_LOG_PENDING`; the review queue is a live inbox rather than an append log; merges have an audit trail with git-recoverable deletions. 349 fast tests, all green. 136 commits with disciplined messages. The remediation dossiers in `meta/dossiers/` show a full backward staleness sweep was actually completed, not just planned.

> The architecture doc's key move — "the 7 A2Zero strategies *are* the communities, pre-defined by the plan itself" — works because city climate plans are self-taxonomizing documents. This is a property of the domain, not luck: nearly every municipal CAP is organized into named strategy pillars. That means the GraphRAG-without-Leiden trick generalizes to other cities, which quietly de-risks the Grapevine expansion more than the docs acknowledge.

---

## Real issues that will bite

### 1. World-time and pipeline-time are conflated — the most important issue

The digest and every `synthesis.year-over-year-arc` say things like *"Baseline set in cap-2020 on 2026-06-24; across a2zero-year1 through a2zero-year5 (2026-06-25 to 2026-07-02)…"* — those are **ingest dates**, ten days of pipeline runs, presented as if they were the program's history. The actual story spans 2019–2025. For a project whose entire product is *"how did this program unfold over time, so another city can replicate it,"* real-world chronology is the core asset, and right now it's second-class: sources carry no `covers-period` metadata, and there is no timeline layer at all (wiki-v1 had one; v3 dropped it). A downstream agent reading the digest would learn the wiki's build history, not Ann Arbor's.

### 2. Event deduplication fails systematically on the "anticipated → occurred" pattern

Concrete evidence: there are **three pages for the same SEU authorization vote** — `wiki/political-events/2024-11-01-ann-arbor-seu-authorization-vote.md` and `wiki/political-events/2024-11-05-ann-arbor-seu-authorization-vote.md` (both from year5, differing only in date precision) plus `wiki/political-events/november-2024-seu-ballot-question.md` (year4's forward-looking announcement, `outcome: other`). There's also the same 2020-03-20 partners meeting duplicated in both `meetings/` and `political-events/`. This isn't random noise — it's a *structural* pattern: annual reports announce future events, the next report describes them happening, and the pipeline has no "pending event resolved" mechanic, while date-prefixed slugs defeat fuzzy-title dedup. As council minutes and news get ingested (the stated next sources), event volume goes way up and this class of duplicate will dominate lint queues.

### 3. Contradiction tracking regressed to zero — and it's the differentiating content

The archive shows wiki-v1 had three real contradiction pages (Wheeler MW discrepancy, Solarize scope, facility audit counts). The current wiki has **zero** after six sources, `contradicts` is defined in the integration plan but unsurfaced (acknowledged in the arch doc's own future-directions section), and the digest's open-questions repeatedly note that self-reported numbers don't reconcile. For replication playbooks, "where the official record disagrees with itself" is precisely the high-value signal a consultant can't get from reading the PR. Annual reports are self-congratulatory by construction; the tension layer is where truth lives.

### 4. No measurement of whether the wiki actually works

The downstream consumer is "AI agents producing replication playbooks," but nothing tests retrieval utility. There's no golden-question eval set, `topics/` has only 2 pages, and the query-log flywheel — which is nicely built — is essentially unused. There are 349 tests proving the *pipeline* works and zero evidence the *knowledge base* answers questions correctly. The compounding-knowledge property is currently an article of faith. Relatedly, quantitative outcomes exist only as prose: "5.4 MW," "$10,000,000," "262 homes" are locked inside paragraphs, not queryable as structured data, and the digest itself repeatedly admits "the ingested inventory does not provide quantitative results" for strategies 4 and 5.

### 5. The digest — the single most-leveraged artifact — is the weakest written layer

It's injected into *every* Comprehend pass, so its quality compounds. Right now: all seven arcs share the same boilerplate skeleton ("Baseline set in cap-2020… appears to broaden from X into implementation via Y"); hedge-words ("appears to") appear ~15 times; `core-actors` lists exactly one actor for Strategy 1 and **none** for Strategies 2–7, which guts the entity map's recall function — the thing the digest exists to provide. Compare it with the strategy pages it aggregates from, which are far denser; compression is destroying information the level below already has.

### 6. Documentation and repo hygiene drift

Small but telling: CLAUDE.md claims 137 tests in one place and 152 in another (actual: 349); `wiki/hot.md` is documented as rebuilt every Pass 3 but doesn't exist; `framing/` and `contradictions/` are "planned" with zero pages after six sources; `tests/__pycache__/*.pyc` files are **tracked in git** (they show as modified in status) despite CLAUDE.md explicitly forbidding it; `meta/dossiers/` sits untracked. Also, the paused quad pipeline (`blackboard/`, four `_legacy` modules, quad schema in `_models.py`) lingers with no consumer — CLAUDE.md itself admits quads are "token-expensive and unused." Either define the consumer or delete it; half-alive subsystems tax every future contributor.

### 7. Single-city assumptions are hardening

"7 strategies" is baked into prompts, docs, Phase C, and the digest structure. Fine today — but Grapevine's thesis is multi-city, the arch doc's own future-directions section knows this, and every week of building against a hardcoded 7 raises the eventual extraction cost. Multi-city support isn't needed now; the strategy set should become *data* (a per-source-corpus config) rather than a constant.

---

## Novel directions worth real consideration

**A. Commitment ledger — resurrect v1's best idea as a deterministic diff.** Wiki-v1 had 100+ `commitments/` pages tracking specific yearly promises; v3 dropped the concept. Bring it back smarter: CAP-2020 and every annual report list explicit next-year commitments. Extract them once into a ledger, then have each ingest mark them `delivered / slipped / rescoped / vanished` with evidence. *Promise-versus-delivery over five years is the single most valuable replication signal that exists* — which commitments slipped, by how long, and what unblocked them. No other artifact in the climate-policy space does this systematically, and the data already contains it.

**B. Playbook cards as a forcing function.** The Grapevine product is replication playbooks — so generate a draft one now (e.g. Solarize or the SEU): preconditions (state law, millage funding, utility structure), timeline from concept to milestone, costs, staffing, failure modes, transferability caveats. The point isn't the card itself; it's that the attempt surfaces exactly which fields the wiki can't fill — and that gap list becomes the research agenda and schema roadmap, derived from the actual product instead of speculation.

**C. Dependency graph (`enables` / `blocked-by` / `funded-by` relations).** The digest already narrates the insight — "adoption programs can move only as fast as financing, utility coordination, and regulatory authority allow" — but as prose. Make it a typed relation in the relationship lexicon and it unlocks the killer replication query: *"City X has no millage and no CCA-enabling law — which A2Zero initiatives are actually available to them, and in what order?"* That's a question no document search can answer and a dependency graph answers trivially.

**D. Source-perspective weighting before news/council ingestion.** All six current sources are self-reported. When adversarial sources arrive (council minutes with dissent, news coverage, the DTE franchise fight, the EPA grant termination — pages already touch the last two), add `perspective: self-reported | deliberative | third-party` to source frontmatter so synthesis can triangulate rather than average. Design this *before* the first news ingest, not after it contaminates the digest.

**E. Stress-test single-city assumptions with a cheap second corpus.** Before more infrastructure hardens around "the 7 strategies," ingest one small second document set — even another Ann Arbor plan (Vision Zero, the Comprehensive Plan) with its own taxonomy. Everything that breaks is a Grapevine bug found early at one-tenth the eventual cost.

---

## Bottom line

Two weeks in, the pipeline's engineering discipline (deterministic verification layers, human gates at the right joints, frozen foundations, self-surfacing governance) exceeds most production LLM systems, and content demonstrably compounds across sources. The gaps are one level up, in the knowledge model: **time, events, outcomes, and disagreement** aren't yet first-class citizens, and nothing measures end-use quality. Recommended sequencing: world-time grounding first — it fixes what the wiki *says* — then the eval harness, which tells us whether anything else we change is actually working, then the commitment ledger, the shortest path from "impressive infrastructure" to "content nobody else has."

See `docs/action-plan-2026-07-09.md` for the tracked action list derived from this evaluation.
