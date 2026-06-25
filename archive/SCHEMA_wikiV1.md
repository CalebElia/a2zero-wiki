# A2ZERO Wiki — Schema & Ingest Rules

This file defines how to ingest A2ZERO annual reports into the wiki. Read this
in full before processing any document in `raw/`.

## Source corpus

Five annual reports (`raw/a2zero-year1.md` through `raw/a2zero-year5.md`),
each covering one year of progress against Ann Arbor's A2ZERO climate plan.
Each report is structured around the same 7 strategies and ends with a
"Next Steps" section describing planned work for the following year.

This stable structure is the backbone of the wiki. Strategy pages should
almost never be created or renamed — only appended to. Everything else
(initiatives, commitments, topics) grows organically.

## Page types

Every wiki page has YAML frontmatter. Required field: `type`. Optional OKF-
aligned fields: `title`, `description`, `tags`, `timestamp`. Additional
fields below are specific to this project.

### 1. `strategy` — one of the 7 fixed A2ZERO strategies

Path: `wiki/strategies/<slug>.md`

```yaml
---
type: strategy
title: "Strategy 1: 100% Renewable Energy Grid"
strategy-number: 1
tags: [renewable-energy, grid]
---
```

Body: a running synthesis of progress across all years, organized
chronologically by year, with links out to `initiatives/` pages for any
named program. Do not just concatenate bullet lists from each report —
synthesize: what's the trend, what stalled, what accelerated.

### 2. `initiative` — a named program, pilot, or project

Path: `wiki/initiatives/<slug>.md`

```yaml
---
type: initiative
title: "Solarize Toolkit"
launched: 2021
status: active | completed | stalled | unknown
parent-strategy: strategy-1
tags: [solar, toolkit]
---
```

Body: what it is, what's happened to it across years (cite which year-report
each fact came from), current status.

Create a new initiative page for any named program mentioned with enough
specificity to track over time (e.g. "Solarize Toolkit," "10,000 Trees
Initiative," "Aging in Place Efficiently program"). Don't create a page for
one-off bullet items with no forward continuity (e.g. a single conference
presentation).

### 3. `commitment` — an explicit forward-looking claim

Path: `wiki/commitments/<slug>.md`

```yaml
---
type: commitment
title: "Launch community solar pilot"
made-in: a2zero-year1
made-in-section: "Next Steps"
target-year: year2
status: unverified | fulfilled | partial | missed | carried-forward
tags: [solar]
---
```

Body: exact framing from the source "Next Steps" section (paraphrased, not
quoted verbatim), and — once later reports are ingested — evidence of
whether it happened, with citation to the report and section where that
evidence appears.

**Every item in a "Next Steps" section gets a commitment page.** This is the
single most important rule in this schema. Do not skip items that seem
minor — minor commitments are often the ones that quietly disappear, and
that disappearance is itself valuable signal.

### 4. `contradiction` — flagged inconsistency between reports

Path: `wiki/contradictions/<slug>.md`

```yaml
---
type: contradiction
title: "Tree planting count discrepancy"
sources: [a2zero-year1, a2zero-year2]
status: unresolved
tags: [resilience, trees]
---
```

Body: the conflicting claims side by side, exact section/year each came
from, and your best-guess explanation if one is plausible (e.g. different
reporting periods, cumulative vs. annual figures).

### 5. `topic` — cross-cutting synthesis not tied to one strategy

Path: `wiki/topics/<slug>.md`

Used for things that cut across strategies, e.g. "Bryant Neighborhood
Decarbonization" (which touches Strategy 3 and equity threads across
multiple years). Same frontmatter pattern as `initiative`.

### 6. Timeline index

Path: `wiki/timeline/index.md` — single file, append-only, one line per
dated event across all years, sorted chronologically. Format:

```
- YYYY-MM: Event description [[link-to-relevant-page]] (source: a2zero-yearN)
```

## Ingest workflow (run once per report, in order)

1. **Read the report fully** before writing anything.
2. **Update each of the 7 strategy pages** with this year's progress.
   Append to the existing synthesis; don't overwrite prior years.
3. **Create or update initiative pages** for every named program mentioned.
   If an initiative already has a page from a prior year, update its
   `status` field and append new evidence — do not duplicate the page.
4. **Extract every "Next Steps" item as a commitment page** (rule above).
5. **Check open commitments from prior years against this year's content.**
   For every existing commitment page with `status: unverified` or
   `carried-forward`, search this report for evidence it was fulfilled,
   partially done, or dropped. Update status accordingly. This is the step
   a plain RAG system cannot do automatically — do not skip it.
6. **Check for contradictions.** Compare any numeric claims (counts, dollar
   amounts, percentages, dates) against existing wiki pages. If two reports
   disagree, create a `contradiction` page rather than silently picking one.
7. **Update the timeline index** with any dated events.
8. **Update `wiki/index.md`** (the top-level directory) if new pages were
   created.

## Rules for relationship language

Never write "related to." Use specific verbs in prose and in links:
`implements`, `funds`, `supersedes`, `is part of`, `was planned in
[year] and `fulfilled-in`/`missed-in` [year].

## Citation rule

When writing any synthesis, cite the source report inline, e.g.
"(a2zero-year1)". Never copy bullet lists verbatim from the source —
synthesize and reword.
