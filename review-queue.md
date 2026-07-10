
## Staleness Lint — 2026-07-07 (source: a2zero-year5)

- [STALE_ENTITY] `actors/washtenaw-area-apartment-association.md` — source a2zero-year5 mentions this entity (2× as: property owners, local property owners) but the page has no a2zero-year5 citation — possible missed update
## Contradiction Sweep — 2026-07-10

### [CONTRADICTION_PROPOSED] contradictions/wheeler-center-landfill-solar-capacity-24mw-cap-2020-vs-20mw
- Related initiative: [[initiatives/landfill-solar-project]]
- Confidence: 0.92
- Reasoning: [digest open-question match] The 4MW discrepancy (24MW vs 20MW) represents a 17% reduction in planned renewable generation capacity from the same project, which directly affects assessed progress toward Ann Arbor's 100% renewable energy goal and the claimed offset of ~80% of municipal energy usage. If the project was re-scoped downward, that change is not acknowledged or explained on the initiative page.
- Action: [ ] APPROVE_CREATE  [ ] DISMISS  [ ] DEFER
- Notes: Likely the same real-world conflict as the already-backfilled `contradictions/wheeler-center-mw-discrepancy.md` (24MW vs 20MW at the same landfill site), just discovered via `initiatives/landfill-solar-project.md` instead of `initiatives/wheeler-center-solar-park.md` — the automated dedup only caught 1 shared source (cap-2020) between the two, below its 2-source threshold. Worth checking whether `landfill-solar-project.md` and `wheeler-center-solar-park.md` are themselves duplicate initiative pages for the same project before deciding APPROVE_CREATE vs DISMISS — recommend DISMISS in favor of the existing page unless they turn out to be genuinely distinct.

```markdown
---
type: contradiction
title: "Wheeler Center Landfill Solar capacity: 24MW (CAP 2020) vs 20MW (Year 3 report)"
sources:
- '[[sources/annual-reports/a2zero-year3]]'
- '[[sources/cap/cap-2020]]'
cross-source: true
status: unresolved
related-initiatives:
- '[[initiatives/landfill-solar-project]]'
tags:
- solar
- landfill
- local-energy
- emissions-reduction
source-first-seen: '[[sources/annual-reports/a2zero-year3]]'
last-updated: '2026-07-10'
---

## Conflicting claims

**cap-2020:** "By 2030, the City-owned landfill and surrounding property has 24 MW of installed solar capacity... By the end of 2023, a 24MW solar installation is fully operational at the former Ann Arbor landfill and on the land held in PUD with Pittsfield Township." ([[sources/cap/cap-2020|cap-2020]])

**a2zero-year3:** "Continued working on a project to create a 20MW solar installation on the City's capped landfill, which, when complete, would be one of the largest landfill solar projects in the nation." ([[sources/annual-reports/a2zero-year3|a2zero-year3]])

## Why it matters

The 4MW discrepancy (24MW vs 20MW) represents a 17% reduction in planned renewable generation capacity from the same project, which directly affects assessed progress toward Ann Arbor's 100% renewable energy goal and the claimed offset of ~80% of municipal energy usage. If the project was re-scoped downward, that change is not acknowledged or explained on the initiative page.

## Best-guess explanation

The project was likely re-scoped between CAP 2020 and Year Three implementation planning, possibly due to site constraints, permitting limitations, or revised partnership terms with DTE Energy or Pittsfield Township, but no source explicitly documents this change or its rationale.

_Surfaced by a contradiction sweep against initiatives/landfill-solar-project — human review required before this page is considered final; see docs/contradiction-tracking-assessment-2026-07-10.md for the mechanism._
```

### [CONTRADICTION_PROPOSED] contradictions/aging-in-place-efficiently-10-year-cost-estimate-150000-page
- Related initiative: [[initiatives/aging-in-place-efficiently]]
- Confidence: 0.82
- Reasoning: The initiative page misquotes the CAP 2020 cost estimate for this program, understating it by $5,000. While small in absolute terms, this is a factual inaccuracy in a cited source that could affect comparisons of program costs across the A2Zero portfolio.
- Action: [ ] APPROVE_CREATE  [ ] DISMISS  [ ] DEFER
- Notes: _Add any notes before approving_

```markdown
---
type: contradiction
title: "Aging in Place Efficiently 10-year cost estimate: $150,000 (page body) vs. $155,000 (cap-2020 source table)"
sources:
- '[[sources/cap/cap-2020]]'
cross-source: false
status: unresolved
related-initiatives:
- '[[initiatives/aging-in-place-efficiently]]'
tags:
- aging-in-place
- low-income-seniors
- weatherization
- energy-efficiency
source-first-seen: '[[sources/cap/cap-2020]]'
last-updated: '2026-07-10'
---

## Conflicting claims

**cap-2020:** "| Aging in Place Efficiently | $155,000 | Not Calculated | ... | LOCAL; JOBS; RES; HEALTH; $$; EQU |" ([[sources/cap/cap-2020|cap-2020]])

**cap-2020:** "The page body states: 'The 10-year cost is estimated at $150,000' — but the cap-2020 source table shows $155,000 for Aging in Place Efficiently." ([[sources/cap/cap-2020|cap-2020]])

## Why it matters

The initiative page misquotes the CAP 2020 cost estimate for this program, understating it by $5,000. While small in absolute terms, this is a factual inaccuracy in a cited source that could affect comparisons of program costs across the A2Zero portfolio.

## Best-guess explanation

An earlier extraction pass likely rounded or misread '$155,000' from the CAP 2020 table as '$150,000', silently introducing a $5,000 discrepancy without flagging the inconsistency.

_Surfaced by a contradiction sweep against initiatives/aging-in-place-efficiently — human review required before this page is considered final; see docs/contradiction-tracking-assessment-2026-07-10.md for the mechanism._
```

### [CONTRADICTION_PROPOSED] contradictions/federal-aid-secured-for-net-zero-affordable-housing-3000000-vs
- Related initiative: [[initiatives/net-zero-energy-affordable-housing]]
- Confidence: 0.82
- Reasoning: The page characterizes the federal aid as 'over $3,000,000,' implying a figure exceeding $3 million, while the source states exactly '$3 million' with no indication it exceeded that amount. This overstates the reported figure, which could affect assessments of funding progress toward affordable housing decarbonization goals.
- Action: [ ] APPROVE_CREATE  [ ] DISMISS  [ ] DEFER
- Notes: _Add any notes before approving_

```markdown
---
type: contradiction
title: "Federal aid secured for net zero affordable housing: $3,000,000+ vs $3,000,000"
sources:
- '[[sources/annual-reports/a2zero-year3]]'
cross-source: false
status: unresolved
related-initiatives:
- '[[initiatives/net-zero-energy-affordable-housing]]'
tags:
- affordable-housing
- net-zero
- equity
- health
source-first-seen: '[[sources/annual-reports/a2zero-year3]]'
last-updated: '2026-07-10'
---

## Conflicting claims

**a2zero-year3:** "Collaborated with the Ann Arbor Housing Commission to secure $3 million in federal aid to advance net zero energy affordable housing in the City." ([[sources/annual-reports/a2zero-year3|a2zero-year3]])

**a2zero-year3:** "Page body states: 'the Ann Arbor Housing Commission secured over $3,000,000 in federal aid' — the source says exactly '$3 million', not 'over $3,000,000'" ([[sources/annual-reports/a2zero-year3|a2zero-year3]])

## Why it matters

The page characterizes the federal aid as 'over $3,000,000,' implying a figure exceeding $3 million, while the source states exactly '$3 million' with no indication it exceeded that amount. This overstates the reported figure, which could affect assessments of funding progress toward affordable housing decarbonization goals.

## Best-guess explanation

The page author likely added 'over' to hedge or approximate, but the source excerpt gives a precise '$3 million' figure with no qualifier suggesting it exceeded that amount. This is a minor but genuine numeric misrepresentation introduced during page drafting.

_Surfaced by a contradiction sweep against initiatives/net-zero-energy-affordable-housing — human review required before this page is considered final; see docs/contradiction-tracking-assessment-2026-07-10.md for the mechanism._
```
