# Grapevine LLM-Wiki v2 — Design Specification

**Date:** 2026-06-18  
**Tenant:** Ann Arbor, MI — A2Zero Climate Action Plan  
**Status:** Draft — awaiting user review before implementation planning

---

## Table of Contents

1. [System Purpose & Design Principles](#1-system-purpose--design-principles)
2. [Architecture Overview](#2-architecture-overview)
3. [Tenant Configuration](#3-tenant-configuration)
4. [Page Type Schema (14 types)](#4-page-type-schema)
5. [Ingest Protocol — Source Types](#5-ingest-protocol--source-types)
6. [Accuracy & Hallucination Controls](#6-accuracy--hallucination-controls)
7. [Blackboard Specification](#7-blackboard-specification)
8. [Sub-Timeline Filtering](#8-sub-timeline-filtering)
9. [Post-Ingest Pipeline](#9-post-ingest-pipeline)
10. [Synthesis Pages](#10-synthesis-pages)
11. [Provenance Chain](#11-provenance-chain)
12. [Relationship Language](#12-relationship-language)
13. [Research Agenda (External)](#13-research-agenda-external)
14. [Known Trouble Spots](#14-known-trouble-spots)
15. [Open Questions](#15-open-questions)

---

## 1. System Purpose & Design Principles

### Purpose

This wiki is a knowledge base built from public records of Ann Arbor's A2Zero climate action program. Its purpose is to support Grapevine's core mission: reconstructing the anatomy of successful policy implementation — mapping strategic coalitions, funding structures, administrative pathways, persuasive messaging, and political timing — so that the lessons can be transferred to other cities.

The wiki is not a summary of A2Zero. It is a structured, provenance-linked, temporally organized reconstruction of *what actually happened and why it worked*, built from the full diversity of available primary sources.

### Design Principles

**1. Extraction fidelity over analytical focus.**  
The LLM extraction phase captures everything present in source documents regardless of the researcher's current analytical priorities. Research priorities influence source selection and synthesis investment only — never extraction.

**2. No claim without a citation.**  
Every factual claim in every wiki page must be traceable to a specific passage in a specific source document. Synthesis is permitted; invention is not. If a claim cannot be cited, it does not appear in the wiki.

**3. Extraction and synthesis are separate LLM passes.**  
They use different prompts, different temperature settings, and different validation rules. Mixing them in one pass is the primary cause of hallucination in LLM-wiki systems.

**4. The blackboard is the query layer; the wiki is the narrative layer.**  
These serve different consumers. The blackboard (`quads.jsonl`) powers dashboard visualizations and dark matter detection. The wiki powers LLM chat context and human understanding. Both are produced from the same ingest, but they are never interchangeable.

**5. Everything is iterative.**  
No source is the last source. No page is final. The system is designed to incorporate new sources without re-ingesting old ones, and to update confidence scores, staleness flags, and dark matter gaps automatically after every ingest run.

### Relationship to LLM-Wiki Research

This design draws from several established approaches:

- **STORM (Stanford, 2024):** Outline-first generation — extract structure before prose. Applied here as: YAML frontmatter extraction before body prose, always in separate passes.
- **GraphRAG (Microsoft, 2024):** Community reports as pre-computed summaries of entity clusters. Applied here as ingest-triggered synthesis pages.
- **RAPTOR:** Hierarchical summarization at multiple abstraction levels. Applied here as the strategy → initiative → commitment → mechanism hierarchy.
- **HippoRAG:** Knowledge graph as associative memory for multi-hop reasoning. Applied here as the wiki's entity linking enabling multi-hop chat queries.
- **Temporal KG work (TiRex, TimR):** Facts have valid time periods, not just timestamps. Applied here as the `made-in`/`fulfilled-in`/`status` fields on commitment pages, and as the temporal scope of every quad.

**Key failure modes documented in the community** that this spec explicitly guards against:
- Entity drift (same entity, different slugs across ingest runs) → entity alias table
- Temporal hallucination (LLM conflates when something happened) → temperature 0 for extraction, verification pass
- Citation laundering (synthesis cites synthesis, losing original source) → hard rule: synthesis pages never cite other synthesis pages
- Schema creep (LLM invents new page types) → explicit negative examples in SCHEMA.md
- Confidence inflation (synthesized facts presented with same confidence as sourced facts) → `synthesis` type is distinct, never enters quads

---

## 2. Architecture Overview

### Medallion Data Architecture

```
BRONZE (Immutable Raw)
└── /bronze/{uuid}.{ext}
    PDFs, MP4s, HTML, raw JSON
    Assigned UUID on first ingest. Never modified.

SILVER (Cleaned Markdown)
└── /silver/{source-type}/{uuid}.md
    Normalized markdown with strict YAML frontmatter.
    One Silver file per Bronze document.
    YAML required: source_uuid, source_type, date_published, jurisdiction, title

GOLD (Two parallel outputs from one LLM ingest)
├── /wiki/                    ← Narrative layer
│   All 14 page types in structured markdown.
│   Human-readable. LLM context-window friendly.
│   Provenance-linked via inline citations.
│
└── /blackboard/              ← Query layer
    quads.jsonl               ← Temporal fact store
    sources_index.json        ← UUID → file paths + excerpts
    entity_aliases.json       ← Canonical names + known aliases
    dark_matter.md            ← Auto-generated gap dossier
```

### The Two Gold Outputs

The LLM ingest step reads a Silver document and simultaneously produces:

1. **Wiki updates** — creates or updates wiki pages following the page type schema. Narrative synthesis, cited prose, structured frontmatter.

2. **Quad emissions** — emits atomic facts as structured JSON lines to be appended to `quads.jsonl`. One quad per discrete, dated, citable claim.

These are produced in **separate LLM passes** (see Section 6). The extraction pass produces quads. The synthesis pass produces or updates wiki pages. They share source material but use different prompts and temperature settings.

---

## 3. Tenant Configuration

### `wiki/tenant.md`

This file is read by the LLM at the start of every ingest session to establish jurisdiction scope. It is a configuration artifact, not a content page. It does not receive citations and is never updated by ingest.

```yaml
---
type: tenant
city: Ann Arbor
state: Michigan
country: US
program: A2Zero
program-full-name: "Ann Arbor's A2Zero Carbon Neutrality Plan"
program-start: 2020
program-goal: "Carbon neutrality by 2030"
lead-department: "Office of Sustainability and Innovation"
lead-department-slug: actors/office-of-sustainability-and-innovation
strategy-count: 7
strategy-backbone: fixed  # These 7 pages are never recreated, only appended
wiki-version: "2.0"
schema-file: SCHEMA.md
extraction-rule: >
  Extract all entities, initiatives, commitments, funding events, and actor
  relationships present in each source document, regardless of their relationship
  to the current research agenda. Do not filter by topic. Do not prioritize any
  program over others during extraction. Research priorities are set externally
  in research-agenda.md and govern source selection, not extraction.
---
```

### `research-agenda.md` (External — not a wiki page, not ingested)

Lives at the project root, maintained by the research team. Governs source selection and synthesis investment only. The LLM extraction pipeline never reads this file.

```markdown
# A2Zero Research Agenda

## Current Synthesis Priorities
These determine which mechanism pages and deep synthesis get written now.
1. Bryant Neighborhood Decarbonization — active deep study
2. Community Climate Action Millage — planned next
3. Sustainable Energy Utility — planned

## Source Search Status
| Topic           | Climate Action Plan | Annual Reports | Council Transcripts | Press Releases | RFPs/Contracts | Third-Party |
|-----------------|--------------------|-----------------|--------------------|----------------|----------------|-------------|
| Bryant Decarb   | partial            | Y1–Y5 ✓         | 3 planned          | partial        | identified     | —           |
| SEU             | partial            | Y1–Y5 ✓         | —                  | —              | —              | —           |
| Climate Millage | partial            | Y1–Y5 ✓         | —                  | —              | —              | —           |

## Next Source Search (Bryant phase)
- Ann Arbor RFP database — contractor selections for geothermal + resilience hubs
- City Council contract approval resolutions — votes authorizing construction contracts
- DOE grant agreement documents — conditions + reporting requirements
- 3 targeted council meetings: SEU ballot vote (Sep 2024), Bryant hearing (date TBD), millage vote (date TBD)

## Future Source Searches (SEU phase — not yet started)
- SEU ballot measure documents + legal filings
- SEU Board meeting transcripts (post-Nov 2024)
- Rate study commissioned by City
- DTE utility case filings (U-20713 settlement documents)
```

---

## 4. Page Type Schema

Every wiki page has YAML frontmatter. All pages share these base fields:
- `type` (required) — one of the 14 types below
- `title` (required)
- `tags` (required) — minimum 2 tags; used for sub-timeline filtering and staleness detection
- `source-first-seen` — the source_uuid where this entity first appeared
- `last-updated` — date of most recent ingest that modified this page

---

### 4.1 `strategy`

**Path:** `wiki/strategies/strategy-N-slug.md`  
**Count:** Exactly 7. Never created or renamed — only appended to.

```yaml
---
type: strategy
title: "Strategy 1: 100% Renewable Energy Grid"
strategy-number: 1
tags: [renewable-energy, grid, solar, geothermal]
last-updated: 2026-06-18
---
```

**Body rules:**
- Organized chronologically by year, then by source type within each year
- Each year section summarizes progress from all source types ingested for that year
- End of each year section: `**Prior-year commitment check:**` listing resolution of all commitments from the previous year's Next Steps
- Do not concatenate bullet lists. Synthesize: what's the trend, what stalled, what accelerated, what was a turning point
- Every factual claim: `(source: uuid)` inline citation
- Link to initiative pages for every named program

**What NOT to create:** Do not create a strategy page for anything that isn't one of the 7 fixed A2Zero strategies.

---

### 4.2 `initiative`

**Path:** `wiki/initiatives/slug.md`

```yaml
---
type: initiative
title: "District Geothermal"
launched: 2023
status: active  # active | completed | stalled | on-hold | unknown
parent-strategy: strategy-1
related-strategies: [strategy-6]
actors: [actors/osi, actors/groundwork-usa, actors/us-doe]
funding-events: [funding/doe-580k-geothermal-planning, funding/doe-10m-geothermal-installation]
locations: [locations/bryant-neighborhood, locations/veterans-memorial-park]
tags: [geothermal, decarbonization, federal-funding, bryant]
source-first-seen: a2zero-year3
last-updated: 2026-06-18
---
```

**Body rules:**
- What it is (1–2 sentences, no jargon)
- Year-by-year evidence sections, citing source_uuid for each fact
- Status explanation at the end of the most recent year section
- Use `implements`, `funds`, `supersedes` etc. — never "related to" (see Section 12)

**Create an initiative page when:** A named program is mentioned with enough specificity to track over time.  
**Do NOT create an initiative page for:** One-off events, single conference presentations, unnamed policy considerations.

---

### 4.3 `commitment`

**Path:** `wiki/commitments/slug.md`

```yaml
---
type: commitment
title: "Launch community solar pilot by Year 2"
made-in: a2zero-year1
made-in-section: "Next Steps"  # "Next Steps" | "CAP Actions" | "council-debate" | "press-release"
target-year: year2
status: fulfilled  # unverified | fulfilled | partial | missed | carried-forward
confidence: high  # high (official Next Steps or CAP action) | medium (press release) | low (council debate, informal)
fulfilled-in: a2zero-year2
fulfilled-evidence: "U-20713 settlement established first community solar in DTE territory (source: a2zero-year2)"
tags: [solar, community-solar, strategy-1]
source-first-seen: a2zero-year1
last-updated: 2026-06-18
---
```

**Confidence levels for commitments:**
- `high` — commitment appeared in an official Next Steps section of an annual report or as a named CAP action. Reliably tracked.
- `medium` — commitment announced in a press release or city council agenda item but not in a formal Next Steps section.
- `low` — informal commitment made in council debate, a public statement, or an interview. Real but less reliably documented.

**Body rules:**
- Original framing from the source Next Steps section (paraphrased, not copied verbatim), with citation
- Resolution section: evidence of fulfillment, partial completion, or non-fulfillment, with citation to the report/section/date where evidence appears
- If `carried-forward`: note how many years it has been carried, link to the original commitment

**Non-negotiable rule:** Every item in every "Next Steps" section gets a commitment page. No exceptions. Minor-seeming commitments that disappear quietly are the most important signal.

---

### 4.4 `contradiction`

**Path:** `wiki/contradictions/slug.md`

```yaml
---
type: contradiction
title: "Solar MW figures differ within Year 5 report"
sources: [a2zero-year5]
cross-source: false  # false = same source type conflicts; true = official doc vs. transcript/news
status: unresolved  # unresolved | explained | resolved
tags: [solar, metrics, strategy-1]
source-first-seen: a2zero-year5
last-updated: 2026-06-18
---
```

**Body rules:**
- Conflicting claims side by side, each with exact source_uuid and section reference
- Best-guess explanation if one is plausible (different reporting scopes, cumulative vs. annual)
- `cross-source: true` when the conflict is between source types (e.g., what the annual report says vs. what a council member said in a transcript) — these are potentially political stories, not just data quality issues

**Do NOT silently resolve contradictions** by picking the number that seems more authoritative. Create the contradiction page.

---

### 4.5 `topic`

**Path:** `wiki/topics/slug.md`

```yaml
---
type: topic
title: "Bryant Neighborhood Decarbonization"
strategies: [strategy-1, strategy-2, strategy-6]
actors: [actors/osi, actors/groundwork-usa, actors/building-decarbonization-coalition]
locations: [locations/bryant-neighborhood, locations/bryant-community-center, locations/bryant-elementary]
funding-events:
  - funding/doe-10m-geothermal-installation
  - funding/county-oced-31m-weatherization
  - funding/community-climate-action-millage
sub-timeline: true  # signals that this topic has its own filtered timeline view
tags: [bryant, decarbonization, geothermal, equity, community-engagement]
source-first-seen: a2zero-year1
last-updated: 2026-06-18
---
```

**Creation rule — topic pages are human-declared, never LLM-created.**  
The LLM never creates a `topic` page during extraction. Topic pages are written by the research team when a cluster of initiatives in the wiki shares a geographic community, a policy mechanism, or a cross-strategy research question that no single initiative page can capture. The LLM may *add citations and links to an existing topic page* but may not create a new one. If the LLM encounters content that seems to warrant a new topic during extraction, it adds a `review-queue.md` note suggesting one — it does not create the page.

A topic page is appropriate when: (a) two or more strategy pages cite the same community or location as a primary focus, (b) the research team has declared it a unit of analysis in `research-agenda.md`, or (c) a funding waterfall spans more than two initiative pages.

**Topic vs. initiative:** An initiative is a named, bounded program that a city runs (District Geothermal, Solarize, SEU). A topic is an analytical lens the research team applies to understand how multiple initiatives intersect at a shared community, geography, or policy question. "Bryant Neighborhood Decarbonization" is a topic because it is not a city program — it is a frame for analyzing how geothermal, weatherization, resilience hubs, and community engagement initiatives converge in one neighborhood. If something could be described as "a program the city runs," it is an initiative. If it could be described as "a question the research team is investigating," it is a topic.

**Stub workflow — how to create a topic page and prepare it for ingest**

Topic pages begin as stubs written by the research team. A stub has frontmatter + one `scope` sentence only. The LLM fills in body evidence on the next ingest run.

**Step 1 — Write the stub** (`wiki/topics/slug.md`):

```yaml
---
type: topic
title: "Bryant Neighborhood Decarbonization"
status: stub  # stub | active | complete
declared: 2026-06-18
declared-by: caleb
strategies: [strategy-1, strategy-2, strategy-6]
scope: >
  All A2Zero programs active in the Bryant neighborhood — geothermal,
  weatherization, resilience hubs, and community engagement — with focus
  on how equity-centered process enabled multi-program co-location at a
  single community site.
sub-timeline: true
tags: [bryant, decarbonization, equity, community-engagement]
---

<!-- Body populated by LLM ingest. Do not write prose here manually. -->
```

The `scope` field is the one thing only the research team writes. It defines the analytical boundary that the LLM uses to decide what evidence belongs here. Write it precisely — "all programs in the Bryant neighborhood" will pull in more than "the geothermal initiative at Bryant Community Center."

**Step 2 — Register aliases** in `blackboard/entity_aliases.json`:

```json
"bryant-neighborhood-decarbonization": {
  "canonical": "topics/bryant-neighborhood-decarbonization",
  "type": "topic",
  "aliases": ["Bryant Decarbonization", "Bryant neighborhood project",
               "Bryant decarb", "Bryant community decarbonization",
               "our work in Bryant"]
}
```

Aliases are what let the LLM recognize the topic when sources use informal shorthand. Without them, references to "the Bryant project" in a council transcript won't get tagged to this topic.

**Step 3 — Ingest populates the body.** On the next ingest run, the LLM:
- Reads the stub from `wiki/topics/` and recognizes it as an active topic
- Tags any relevant quads with `topics/bryant-neighborhood-decarbonization`
- Appends cited evidence to the stub body (append-only, never overwrites)
- Adds wikilinks from initiative and strategy pages back to this topic page
- Flips `status: stub` → `status: active` after the first run that adds body content

**Connection to research agenda:** `research-agenda.md` is where you *decide* to study something. The stub is where you *register* it for the wiki. The flow is:

```
research-agenda.md        →    topic stub + alias entry    →    ingest populates body
"Bryant is our focus"          (human writes scope)              (evidence builds over runs)
```

**Initiative vs. topic — the practical test:**  
If you'd describe it as "a program the city runs," it's an `initiative`. If you'd describe it as "a question the research team is investigating," it's a `topic`. The SEU is an initiative (it's a specific city program). "Municipal Utility Creation as a Decarbonization Strategy" is a topic (it's a research frame). You can have both: the initiative tracks what the SEU *is*; the topic tracks what it *means as a replicable model*.

**Body rules:**
- Cross-cutting synthesis that spans multiple strategies — this is where inter-program connections are made explicit
- Includes an embedded actor roster with each actor's role in this specific topic
- Includes funding waterfall: what funded what, in what order, with what matching requirements
- `sub-timeline: true` flags this topic for automatic filtered timeline generation

---

### 4.6 `location`

**Path:** `wiki/locations/slug.md`

```yaml
---
type: location
title: "Bryant Community Center"
location-type: facility  # county | city | neighborhood | park | facility | infrastructure | district | school
parent-location: locations/bryant-neighborhood
owned-by: city  # city | county | nonprofit | university | school-district | private
address: "3 W. Eden Ct, Ann Arbor, MI 48108"
initiatives:
  - initiatives/resilience-hubs
  - topics/bryant-neighborhood-decarbonization
  - initiatives/district-geothermal
tags: [bryant, resilience-hub, geothermal, community-anchor, facility]
source-first-seen: a2zero-year1
last-updated: 2026-06-18
---
```

**Body rules:**
- What this location is and its significance to A2Zero (1–2 sentences)
- List all initiatives active at this location with brief description of that initiative's activity here
- Note any co-location synergies (multiple programs using same facility)
- Geographic hierarchy: link `parent-location` so the hierarchy is navigable

**Location type hierarchy:**
```
county (Washtenaw County)
└── city (Ann Arbor)
    ├── neighborhood (Bryant, Northside, Pittsfield Village)
    │   └── facility / school (Bryant Community Center, Bryant Elementary)
    ├── park (Veterans Memorial Park, Leslie Park Golf Course)
    ├── infrastructure (Wheeler Service Center, Water Resource Recovery Facility)
    └── district (proposed geothermal district)
```

---

### 4.7 `meeting`

**Path:** `wiki/meetings/YYYY-MM-DD-body-slug.md`

```yaml
---
type: meeting
title: "City Council — 2024-09-16 (SEU Ballot Authorization)"
date: 2024-09-16
body: city-council  # city-council | sustainability-commission | planning-commission | other
source-type: council-transcript
source-uuid: council-transcript-2024-09-16
agenda-items:
  - initiatives/sustainable-energy-utility
  - commitments/y5-seu-education-launch
decisions:
  - "Council votes 8-3 to place SEU on November 2024 ballot"
actors: [actors/christopher-taylor, actors/travis-radina, actors/linh-song]
tags: [seu, renewable-energy, ballot-measure, strategy-1, council-vote]
source-first-seen: council-transcript-2024-09-16
last-updated: 2026-06-18
---
```

**Body rules:**
- Organized by agenda item, not by speaker
- For each agenda item: the question before the body, key arguments made (attributed to speaker with `(source: uuid, speaker: Name)`), points of disagreement, outcome
- Vote records: exactly how each member voted if available
- Do NOT summarize the full meeting — only items relevant to A2Zero programs
- Link to affected initiative and commitment pages

**⚠ Trouble spot:** Diarized transcripts may contain speaker attribution errors. If speaker attribution is uncertain, flag with `(attribution: uncertain)` rather than asserting confidently.

---

### 4.8 `actor`

**Path:** `wiki/actors/slug.md`

```yaml
---
type: actor
title: "Dr. Missy Stults"
actor-type: person  # person | government-office | nonprofit | utility | university | funder
role: "Director, Office of Sustainability and Innovation"
affiliation: actors/office-of-sustainability-and-innovation
elected: false
active-years: [2020, 2021, 2022, 2023, 2024, 2025]
programs-involved: [topics/bryant-neighborhood-decarbonization, initiatives/sustainable-energy-utility]
tags: [osi, city-staff, leadership, a2zero]
source-first-seen: a2zero-year1
last-updated: 2026-06-18
---
```

**Actor sub-types and their key fields:**

| actor-type | Examples | Extra fields | Replication note |
|---|---|---|---|
| `person` | Dr. Missy Stults, Mayor Taylor | `elected`, `affiliation` | Persons are local. Track positions, not people. |
| `government-office` | OSI, City Council, Sustainability Commission | `parent-body`, `authority-over` | Transferable as structural role (e.g., "dedicated sustainability office") |
| `nonprofit` | Groundwork USA, Building Decarbonization Coalition | `geographic-scope`: local/national | National orgs may exist in other cities |
| `utility` | DTE Energy | `regulatory-body`: MPSC, `territory` | Tactics transfer only to similar regulatory structures |
| `university` | University of Michigan | `partnership-type`: research/anchor/co-applicant | Anchor institution strategy transfers; specific programs don't |
| `funder` | U.S. DOE, Kresge Foundation | `funder-type`: federal/state/philanthropic/corporate | Federal funders accessible elsewhere; philanthropic is relationship-dependent |

**Body rules:**
- Role in A2Zero (1–2 sentences)
- Positions taken on key decisions, with citations
- How stance evolved over time (for multi-year actors)
- For `government-office`: what programs fall under its authority

---

### 4.9 `funding-event`

**Path:** `wiki/funding/slug.md`

```yaml
---
type: funding-event
title: "DOE $10M Grant — Bryant Geothermal Installation (2024)"
date: 2024-09
amount: 10000000
currency: USD
fund-type: federal-grant  # see sub-types below
source-org: actors/us-doe
recipient: actors/osi
co-recipient: actors/groundwork-usa
programs: [topics/bryant-neighborhood-decarbonization, initiatives/district-geothermal]
locations: [locations/bryant-neighborhood]
status: on-hold  # announced | awarded | disbursed | completed | terminated | on-hold
matching-required: false
conditions: "Federal terms; subject to federal policy action"
political-risk: high  # low | medium | high
transferable: true  # can another city pursue the same funding pathway?
tags: [federal-grant, geothermal, bryant, doe, decarbonization]
source-first-seen: a2zero-year5
last-updated: 2026-06-18
---
```

**Funding sub-types:**

| fund-type | A2Zero Example | Transferability | Key fields to capture |
|---|---|---|---|
| `federal-grant` | DOE $10M Bryant geothermal, EPA $1M resilience | Transferable if program active. Flag if terminated. | Program office, NOFO #, matching req., political risk |
| `state-grant` | Michigan EGLE programs | State-specific. Note enabling legislation. | State agency, legislative authority, eligibility |
| `local-millage` | Community Climate Action Millage | Strategy transfers; requires political viability analysis | Vote date, margin, levy rate, duration, ballot language |
| `philanthropic-grant` | Kresge Foundation | Relationship-dependent. Less transferable. | Funder priorities, grant term, renewal likelihood |
| `utility-program` | DTE MIGreenPower rate savings | Utility + regulatory structure specific | Utility case number, rate schedule, eligibility |
| `federal-incentive` | IRA tax credits, direct pay | Broadly transferable while IRA intact | IRC section, direct pay eligible, bonus adder |
| `budget-allocation` | Council-approved capital budget line | Strategy transfers; requires political will | Council vote date, resolution #, fiscal year |

---

### 4.10 `mechanism`

**Path:** `wiki/mechanisms/slug.md`

This is the primary Grapevine product artifact. Mechanism pages answer: "Why did this work, and what transfers to another city?"

```yaml
---
type: mechanism
title: "Community ownership framing unlocked the SEU ballot victory"
programs: [initiatives/sustainable-energy-utility]
actors: [actors/osi, actors/christopher-taylor]
period: 2022-2024
confidence: high  # high (multiple independent sources) | medium (single source) | low (inferred)
transferable: true
replication-notes: >
  Requires: a city with home-rule authority to create a utility, a well-organized
  community engagement infrastructure, and a political window after a contested
  utility intervention. The framing shift from "municipalization" to "community
  ownership" is likely transferable to cities with similar utility skepticism.
  Not transferable: the specific DTE regulatory context (MPSC intervention history)
  is Michigan-specific.
tags: [seu, political-strategy, messaging, community-engagement, strategy-1]
source-first-seen: a2zero-year5
last-updated: 2026-06-18
---
```

**Body rules:**
- State the causal claim plainly in the first sentence
- Describe the evidence: what sources show this mechanism operating
- Every claim must cite at minimum 2 independent sources
- Explicitly state the counterfactual: what would likely have happened without this mechanism
- Transferability section: what transfers, what is Ann Arbor-specific
- `confidence: low` if the mechanism is inferred rather than directly evidenced — do not present inferences as established facts

**Do NOT write mechanism pages from a single source.** Mechanisms require corroboration.

---

### 4.11 `synthesis`

**Path:** `wiki/synthesis/slug.md`

See Section 10 for full synthesis page specification.

```yaml
---
type: synthesis
title: "Ann Arbor Geothermal Pursuits — Comparative Overview"
query: "Tell me about all the places where Ann Arbor is pursuing geothermal projects"
trigger: query  # query | ingest
generated: 2026-06-18
generated-by: claude-sonnet-4-6
status: current  # draft | current | needs-review
last-reviewed: 2026-06-18
retrieval-count: 0
sources-cited:
  - initiatives/district-geothermal
  - topics/bryant-neighborhood-decarbonization
  - commitments/y5-geothermal-citywide-study
  - strategies/strategy-1-renewable-grid
invalidation-triggers:
  - entity: district-geothermal
  - entity: bryant-neighborhood-decarbonization
  - tag: geothermal
tags: [geothermal, synthesis, strategy-1, comparative]
---
```

**Hard rules — enforced by linter:**
1. `sources-cited` must never contain a `wiki/synthesis/` path. No synthesis-to-synthesis citations.
2. `sources-cited` must contain at least 2 entries.
3. Synthesis pages are never ingested into `quads.jsonl`.
4. `status: current` requires a human to have set `last-reviewed`.

---

### 4.12 `framing`

**Path:** `wiki/framing/slug.md`

Captures how a program, initiative, or issue is talked about publicly by stakeholders — the rhetorical layer of policy implementation. Political framing is itself a mechanism: "community ownership" vs. "municipalization" for the SEU is a case where word choice was a strategic decision with measurable political effects. Framing pages document that layer so it can be analyzed and transferred to other cities.

**Scope rule:** Framing pages are not generic communications analysis. They capture how *Ann Arbor stakeholders specifically* framed *specific A2Zero issues*, to *specific audiences*, and how that framing evolved. They are the evidentiary input to mechanism pages about political strategy.

```yaml
---
type: framing
title: "'Community Ownership' vs. 'Municipalization' — SEU Messaging Evolution"
initiative: initiatives/sustainable-energy-utility
period: 2022-2024
actors: [actors/osi, actors/christopher-taylor, actors/missy-stults]
audiences: [public, city-council, utility-ratepayers, environmental-advocates]
evolution: true  # framing shifted deliberately over time
related-mechanism: mechanisms/community-ownership-framing-unlocked-seu-ballot
tags: [seu, messaging, ballot-measure, community-ownership, political-strategy]
source-first-seen: council-transcript-2024-09-16
last-updated: 2026-06-18
---
```

**Body rules:**
- Document the original framing and when it was used, with citation
- Document the shift (if `evolution: true`): what changed, who drove it, when, in response to what
- Attribute each framing instance to the speaker and audience — how OSI talked to council differs from how they talked to residents
- Note what framing was *not* used (what language was deliberately avoided) if sources document this
- Do NOT editorialize about whether the framing was effective — that is the mechanism page's job
- Every claim must be attributed to a source, including the framing itself: `(source: uuid, speaker: Name)`

---

### 4.13 `political-event`

**Path:** `wiki/political-events/YYYY-MM-DD-slug.md`

Captures discrete political outcomes with lasting legal or political effect: council resolutions, referendums, elections, key appointments, court rulings. These are distinct from `meeting` pages (which document deliberative events) — a political-event page documents the outcome and its legal/political consequences.

**Disambiguation from other types:**
- `meeting` = where the debate happened
- `political-event` = the outcome of the debate, as a durable legal or political fact
- `commitment` = what was promised as a result
- `funding-event` = the financial consequence

When a ballot measure passes, create: a `political-event` page (the vote, the margin, the legal authorization), plus a `funding-event` page for the revenue stream it creates (linked via `authorized-by`). Do not create both as political-events or both as funding-events.

```yaml
---
type: political-event
title: "Community Climate Action Millage — November 2024 Ballot"
date: 2024-11-05
event-type: referendum  # referendum | council-resolution | election | appointment | legal-ruling | regulatory-decision
outcome: passed
margin: "62% yes"
legal-effect: "5-year 0.1 mill levy beginning FY2025; generates approximately $5.5M/year designated for A2Zero programs"
programs-authorized:
  - initiatives/resilience-hubs
  - initiatives/weatherization
  - topics/bryant-neighborhood-decarbonization
authorized-funding: funding/community-climate-action-millage
related-meeting: meetings/2024-09-16-city-council
related-framing: framing/millage-as-community-investment
actors: [actors/christopher-taylor, actors/missy-stults, actors/sustainability-commission]
tags: [millage, ballot-measure, funding-authorization, community-engagement, strategy-2]
source-first-seen: press-release-2024-11-06
last-updated: 2026-06-18
---
```

**Pairing rule:** For any significant vote or decision documented in a transcript, create both a `meeting` page (the deliberative event — who argued what, what the stakes were) and a `political-event` page (the legal outcome — what was authorized, what the margin was, what it unlocked). These are always created as a pair for significant decisions. Minor procedural votes (unanimous consent items, routine approvals) create a `meeting` page only.

**Body rules:**
- State the question before the electorate/body and the outcome in the first sentence
- Campaign or advocacy context: who organized, who opposed, key arguments on each side (cited)
- Exact vote tally if available
- What the outcome legally authorizes or prohibits, with any conditions
- Downstream consequences: which programs were unlocked, which were blocked
- For elections: note what was at stake for A2Zero and how the outcome affected program continuity

---

### 4.14 `technology`

**Path:** `wiki/technology/slug.md`

Documents the technology types that appear in A2Zero programs — not as generic explainers, but as Ann Arbor-specific engagement records: what configuration they used, what it cost in their context, what procurement and permitting challenges they encountered, and what site conditions mattered.

**Hard scope rule:** Technology pages document Ann Arbor's specific experience with a technology. They are not Wikipedia articles. A reader should come away understanding what it took for *this city* to deploy *this technology* — not how the technology works in general.

```yaml
---
type: technology
title: "Closed-Loop Ground Source Heat Pump (Geothermal)"
common-name: geothermal
tech-type: heating-cooling  # heating-cooling | solar | storage | efficiency | grid | ev | building-envelope | other
a2zero-context: "Used for district heating/cooling in Bryant Neighborhood; geothermal loop field planned at Bryant Community Center site; citywide suitability study underway"
initiatives: [initiatives/district-geothermal, initiatives/resilience-hubs]
locations: [locations/bryant-community-center, locations/veterans-memorial-park]
deployment-status: in-progress  # planned | in-progress | operational | completed | abandoned
cost-context: "Planning grant $580K (DOE, 2022); installation grant $10M (DOE, 2024, on hold)"
procurement-approach: "Federal grant co-application with Groundwork USA; prime contractor TBD pending federal funding status"
barriers-encountered:
  - permitting  # subsurface utility mapping required
  - site-geology-assessment
  - federal-funding-conditions  # IRA-adjacent; subject to federal policy changes
  - community-trust  # early community engagement required before site selection
transferability: high  # high | medium | low
transferability-notes: >
  Broadly transferable in climate zones with significant heating load. Key constraints:
  available land for loop field (or building footprint for vertical wells), local
  geology (varies significantly), and access to federal grant programs (currently uncertain).
  Community trust-building process transfers well; Ann Arbor's approach to early
  engagement before site selection is a replicable model.
tags: [geothermal, heating-cooling, district-energy, decarbonization, federal-funding, bryant]
source-first-seen: a2zero-year3
last-updated: 2026-06-18
---
```

**Body rules:**
- What this technology is (1 sentence — enough to orient a non-technical reader)
- Ann Arbor's deployment context: where, in what scale, for what purpose
- Procurement and permitting experience: what was harder than expected, what was smoother
- Cost experience: what it actually cost vs. what was budgeted (if known)
- `barriers-encountered` as narrative, not just tags — what each barrier meant in practice
- Transferability section: what conditions another city would need to replicate this approach

**Do NOT:** Create a technology page for a technology mentioned only once in passing. Create one when a technology has a dedicated initiative page or when barriers/costs are documented in sources.

---

## 5. Ingest Protocol — Source Types

Each source type has a different structure, different contribution pattern, and different accuracy risks.

### 5.0 Long Document Protocol (LDP)

The LDP is a pre-processing layer that activates automatically for any Silver document that is too structurally complex to chunk by arbitrary page breaks. It applies *before* source-type-specific extraction rules. Those rules still govern *what* to extract — the LDP governs *how to divide the document* so that each extraction call has full positional context.

**Automation trigger**

Evaluated immediately after Silver conversion, before any extraction call:

```python
silver_lines  = count_lines(silver_doc)
heading_count = count_regex(silver_doc, r'^#{1,3} ')  # H1–H3 markdown headings

if source_type in KNOWN_CHUNK_RULES:
    trigger = "source-type"       # domain-specific rules always take precedence
elif silver_lines > 1000 and heading_count > 10:
    trigger = "ldp"               # unknown structure, map-driven chunking
else:
    trigger = "single-pass"       # fits in one context window as-is
```

**Priority note:** Known source types (annual reports, council transcripts, etc.) always use their domain-specific chunking rules because those rules are structurally informed — "split by strategy section" is better than a generic section map for a document whose structure is already known. LDP fires only for source types *not* in `KNOWN_CHUNK_RULES` — third-party reports, RFPs, legal documents, or any future source type whose internal structure is not predetermined. The CAP triggers LDP because it is a unique document whose structure must be discovered; annual reports do not because their structure is pre-specified.

Starting LDP thresholds: `1000 lines` and `10 headings`. Tune after the first 3–4 LDP ingest runs — a document with 1,500 lines but only 3 headings is dense prose (a long contract), not a structured report; single-pass is correct for it.

**Step LDP-1 — Structure pre-pass (temperature: 0, one call on the full document)**

Prompt task: *"Return this document's complete outline as JSON — section titles, line ranges, depth level (1 = top, 2 = sub, 3 = sub-sub), and a one-sentence summary of each section. Do not summarize content beyond what headings and opening sentences convey."*

Output saved to `blackboard/section_maps/{uuid}_structure.json`. Saved permanently — if the document is re-processed, the map is reused, not regenerated.

```json
{
  "document_uuid": "cap-2020",
  "total_lines": 2847,
  "ldp_version": "1.0",
  "sections": [
    {
      "id": "intro",
      "title": "Introduction and Vision",
      "line_start": 1,
      "line_end": 245,
      "depth": 1,
      "summary": "Sets carbon neutrality by 2030 goal; establishes 7-strategy framework and governance structure"
    },
    {
      "id": "strategy-1",
      "title": "Strategy 1: 100% Renewable Grid",
      "line_start": 246,
      "line_end": 489,
      "depth": 1,
      "subsections": [
        {
          "id": "strategy-1-context",
          "title": "Context and Goals",
          "line_start": 246,
          "line_end": 309,
          "depth": 2,
          "summary": "Defines renewable grid target and rationale"
        },
        {
          "id": "strategy-1-actions",
          "title": "Actions",
          "line_start": 310,
          "line_end": 489,
          "depth": 2,
          "summary": "Lists 12 specific actions targeting 100% renewable electricity by 2030"
        }
      ]
    }
  ]
}
```

**Step LDP-2 — Map-driven chunking**

Each chunk corresponds to one leaf section from the map (a section with no subsections, or a subsection at the deepest level). A universal context header is prepended to every chunk before the LLM sees it:

```
[DOCUMENT CONTEXT]
Document: Ann Arbor A2Zero Climate Action Plan (2020) [uuid: cap-2020]
You are reading: "Strategy 1: 100% Renewable Grid › Actions" [section-id: strategy-1-actions]
Position in document: Section 2.2 of 9 major sections
Parent section summary: Defines renewable grid target; establishes 100% renewable electricity goal by 2030
[END CONTEXT]

[SECTION CONTENT]
... exact section text from Silver markdown ...
[END SECTION]
```

This header is what prevents temporal and positional hallucination in long documents. The LLM always knows where it is, which section's context governs the claims it is reading, and what the parent section established.

**Step LDP-3 — Cross-section reference scan (post-extraction, one lightweight pass)**

After all chunks are extracted, scan all new quads from this document for object-field text containing cross-section references ("as described in the Buildings Strategy...", "see Appendix B...", "consistent with Action 1.3..."). Flag any such quads in the review queue at low priority — a human confirms the reference resolves correctly. These are rare but can create subtle misattributions if undetected.

**Edge case: documents > ~300 pages**

The structure pre-pass is a single LLM call on the full document. For documents under ~300 pages, outline extraction (not content analysis) typically fits within modern context windows. If a document exceeds this, split it into rough thirds for the pre-pass, extract three partial maps, then merge them before running LDP-2. Flag to the data engineer when this is first encountered — it requires a manual merge review.

**What the LDP does NOT change**

The LDP handles document division. It does not change what gets extracted. Source-type extraction rules (Sections 5.1–5.7) still govern which page types are created, what fields are populated, and what accuracy risks apply. For an LDP-triggered ingest of a third-party evaluation report, the data engineer applies the Section 5.6 extraction rules — just against map-driven chunks instead of arbitrary page breaks.

---

### 5.1 Annual Reports

**Contributes primarily to:** strategies, initiatives, commitments, contradictions, topics, funding-events  
**Chunking:** Split by strategy section. Process each of the 7 strategy sections as a separate LLM call. Process the "Next Steps" section separately. Do not process the entire report in one context window.  
**Key things to extract:** All named programs, all numerical claims (MW, units, dollars, counts), all "Next Steps" items as commitments, year-over-year status changes on previously-created initiatives.  
**Accuracy risks:** Annual reports are PR documents — they emphasize success and elide failure. Contradictions with prior years are meaningful signal, not noise. Do not smooth them over.

### 5.2 Climate Action Plan (original, ~150 pages)

**LDP status:** Will trigger LDP automatically (~2,800 Silver lines, ~70 headings). The CAP was the design case that motivated the Long Document Protocol — it is the canonical example of LDP in use. See Section 5.0 for the full LDP spec. The CAP section map is saved to `blackboard/section_maps/cap-2020_structure.json`.

**Contributes primarily to:** strategies (backbone), initiatives (original program concepts), commitments (CAP "actions" seed every commitment page), actors (named authors and stakeholders), technology (technology types described in each strategy section)

**Key things to extract:**
- The original 7 strategy definitions — exact language, extracted at temperature 0
- Every "action" listed under each strategy — each becomes a `commitment` page with `status: unverified`, `made-in: cap-2020`, `made-in-section: "[strategy name] > Actions"`
- All explicit numerical targets — preserve exact figures and units (e.g., "78MW of solar by 2030", not "approximately 78MW")
- Named stakeholder organizations and partner entities → seed `actor` pages
- Technology types mentioned in strategy actions → seed `technology` pages

**Accuracy risks:** This is the founding document — everything that came later is measured against it. Numerical targets extracted here are the reference values for every contradiction check across all future annual reports. Extract them with temperature 0 and run the verification pass (Section 6.2, Pass 4) on every numerical claim.

**The most important tracking task:** CAP "actions" are what the city promised to do in 2020. Annual reports show what was actually done year by year. The gap between the two is the primary signal the wiki is designed to surface. Every CAP action that never appears in any annual report is a dark matter entry, not a data omission — the city either quietly deprioritized it or it happened without being reported. Both are analytically significant.

**Special handling:** When a later annual report's claim contradicts a CAP numerical target, create a contradiction page — do not silently update the target to match the report.

### 5.3 Council Meeting Transcripts (diarized JSON)

**Contributes primarily to:** meetings, actors, commitments (informal commitments made in debate), contradictions (when council statements conflict with official reports)  
**Chunking:** Split by agenda item. Process each agenda item as a separate LLM call.  
**Key things to extract:** Votes and their exact tallies, named speakers and their positions, arguments made for and against, any dates or figures stated, informal commitments ("the Mayor said they would bring a revised proposal by Q3").  
**Accuracy risks:** Speaker attribution errors from diarization propagate into actor pages. Apply a confidence threshold: if the diarization pipeline confidence for a speaker is below a specified threshold, flag the attribution as uncertain. Do not assert a speaker with low confidence.  
**Special rule:** Informal commitments made in council debate (not in official Next Steps sections) get commitment pages with `made-in-section: "council-debate"` and `confidence: low` — they are real commitments, but less reliably tracked.

### 5.4 Press Releases

**Contributes primarily to:** funding-events (grant announcements), commitments (fulfillment evidence), initiative status updates  
**Chunking:** Usually short enough to process in one pass.  
**Key things to extract:** Dates of announcements, dollar amounts, named partners, specific program scopes.  
**Accuracy risks:** Press releases announce intentions, not outcomes. A grant announcement press release does not confirm the grant was disbursed or the project completed. `status: announced` on the funding-event, not `status: awarded` until confirmed by a later source.

### 5.5 News Articles

**Contributes primarily to:** contradictions (journalistic framing vs. official framing), actor pages (community voices, advocacy organizations), mechanism pages (external validation of why something succeeded)  
**Chunking:** One pass per article.  
**Key things to extract:** External characterization of events (how journalists described outcomes vs. how the city described them), community voices (names and positions of residents and advocates), any investigative findings that conflict with official records.  
**Accuracy risks:** News articles have their own editorial perspective. A fact sourced only from a news article carries `confidence: 1` from a Tier 2 source. Do not upgrade it to Tier 1 confidence without corroboration. If a news article contradicts an official source, create a contradiction page with `cross-source: true`.

### 5.6 Third-Party Reports

**Contributes primarily to:** mechanism pages (external evaluation of what worked), initiative pages (external assessments of program status), funding-events (grant outcomes)  
**Chunking:** Split by section.  
**Key things to extract:** Evaluations of program effectiveness, quantified outcomes (especially if they differ from city-reported figures), methodology descriptions.  
**Accuracy risks:** Third-party reports may have funding relationships with the city — note the funder of any evaluation in the page.

### 5.7 RFPs, Contracts, and Resolutions

**Contributes primarily to:** funding-events (amounts, conditions, timeline), commitment pages (fulfillment evidence — a contract award is evidence a commitment was acted on), dark matter resolution (fills gaps between "decision made" and "project started")  
**Chunking:** Process preamble and terms sections separately.  
**Key things to extract:** Contract amounts, contractor names (→ actor pages), timeline milestones, performance conditions, council vote date and tally.  
**Accuracy risks:** Contracts specify intent, not outcomes. `status: contracted` ≠ `status: completed` on a funding-event.

---

## 6. Accuracy & Hallucination Controls

This section governs how the LLM is configured and constrained during every ingest run. Because this wiki contains real policy data about real places and real people, accuracy is not negotiable.

### 6.1 Temperature Settings

| Task | Temperature | Rationale |
|---|---|---|
| Quad extraction (atomic facts from source) | 0.0 | Deterministic. No creativity. Every output must be sourced. |
| Frontmatter field extraction (YAML fields from source) | 0.0 | Same as above. |
| Commitment status update | 0.0 | Binary determination from evidence. |
| Contradiction detection | 0.0 | Factual comparison. |
| Body prose synthesis (strategy pages, initiative bodies) | 0.2 | Minimal creativity; coherence without hallucination. |
| Mechanism page generation | 0.2 | Causal reasoning from evidence; keeps claims grounded. |
| Ingest-triggered synthesis | 0.3 | Community summaries need coherence; still evidence-bound. |
| Dark matter gap reasoning | 0.2 | Domain inference; must be labeled as inference, not fact. |
| Query-triggered synthesis | 0.3 | Responsive to user; coherence matters; still citation-required. |

### 6.2 Structured Extraction Protocol (Separation of Passes)

Every ingest session follows this sequence. These are separate LLM calls with separate prompts:

**Pass 1 — Structural extraction (temperature: 0)**
Input: Silver markdown chunk  
Task: Extract YAML frontmatter fields only. No prose. Output must be valid YAML.  
Output: Frontmatter blocks for any new or updated pages.  
Validation: YAML must parse correctly. All required fields must be present. No fields may contain claims not directly evidenced in the input chunk.

**Pass 2 — Quad extraction (temperature: 0)**
Input: Silver markdown chunk + entity alias table  
Task: Emit atomic facts as quads. Each quad must be citable to a specific sentence or passage in the input.  
Output: JSON lines for quads.jsonl  
Validation: Every quad must include source_uuid. Subject and object must match known entity slugs or be flagged as new entities for alias table review.

**Pass 3 — Body prose synthesis (temperature: 0.2)**
Input: Silver markdown chunk + existing page body (for updates) + frontmatter from Pass 1  
Task: Write or update body prose. Every factual claim must include `(source: uuid)`.  
Output: Page body markdown  
Validation: Every sentence containing a factual claim must end with `(source: uuid)`. Sentences without citations must be structural (headers, transitions) not factual.

**Update rule (critical for accumulating pages like `strategy` and `initiative`):**  
When updating an existing page, the LLM appends new content only — it does not rewrite, restructure, or delete existing body content. The existing page body is provided as read-only context to ensure stylistic continuity. Pass 4 (verification) confirms that all text present in the pre-ingest version of the page is byte-identical in the post-ingest version. Any diff that touches existing content (not just appends) is flagged as a 🔴 urgent violation in the review queue.

**Pass 4 — Verification (temperature: 0)**
Input: Pass 3 output + original Silver chunk  
Task: Read the generated prose and verify each cited claim against the source. Flag any claim that:
- Cannot be found in the source
- Overstates what the source says
- Assigns a date or figure not in the source

Output: List of flagged claims. Human resolves flags before page is committed.

### 6.3 Entity Locking

Before creating any new entity page (actor, initiative, location, etc.), the LLM must check `entity_aliases.json` for existing entries. If a semantically similar entity already exists, the new information is added to the existing page — a new page is not created.

`entity_aliases.json` structure:
```json
{
  "sustainable-energy-utility": {
    "canonical": "initiatives/sustainable-energy-utility",
    "aliases": ["SEU", "Sustainable Energy Utility", "community energy utility", "Ann Arbor SEU"]
  },
  "office-of-sustainability-and-innovation": {
    "canonical": "actors/office-of-sustainability-and-innovation",
    "aliases": ["OSI", "Office of Sustainability", "A2ZERO office", "city sustainability office"]
  }
}
```

After every ingest run, the deduplication script checks for new entities that are semantically close to existing aliases and flags them for human review. This is the primary defense against entity drift.

### 6.4 Source-Anchored Claims Rule

This rule applies to all page types except `synthesis`:

> **Every sentence in a wiki page body that states a fact must end with `(source: uuid)` referencing the Silver document where that fact appears. If a fact cannot be directly cited to a source, it must not appear in the wiki.**

The only permitted exceptions:
- Transitional sentences ("In Year 2, the city built on this foundation...")
- Headers and section labels
- Cross-references to other wiki pages ("See [[initiatives/resilience-hubs]] for the hub network context")

### 6.5 Negative Examples in SCHEMA.md

The operational SCHEMA.md (used by the LLM during ingest) must include explicit negative examples alongside positive ones. Examples:

- ❌ Do not infer causality. "The millage funded the geothermal project" requires a source saying this. "The millage may have funded..." is not acceptable in the wiki — only what sources directly state.
- ❌ Do not update a commitment status based on indirect evidence. If Year 5 says "we expanded weatherization in Bryant" but doesn't say "we fulfilled the Y4 weatherization expansion commitment," the commitment status stays `partial` not `fulfilled`.
- ❌ Do not create a new initiative page for something mentioned once with no forward continuity.
- ❌ Do not smooth over numerical contradictions. If Year 3 says 4MW and Year 4 says 3.8MW for the same metric, create a contradiction page.
- ❌ Do not assign a speaker to a quote unless the diarization source explicitly attributes it. Use `(speaker: unknown)` if unclear.

### 6.6 Dark Matter Inference Labeling

When the dark matter dossier is generated, the LLM reasons about what *should* be between two known events. This is inference, not fact. The dark_matter.md file must label every domain logic inference explicitly:

> "Domain logic suggests the following intermediate steps would typically occur between these events, but no source evidence has been found for them in the current corpus..."

These are interview questions and search guidance — not facts about Ann Arbor.

---

## 7. Blackboard Specification

### 7.1 `blackboard/quads.jsonl`

One JSON object per line. Append-only during ingest. The deduplication script merges duplicates in a separate pass.

**Schema:**
```json
{
  "id": "sha256-hash-of-subject-relation-object-date",
  "date": "2024-09",
  "date_precision": "month",
  "subject": "district-geothermal",
  "relation": "received federal grant",
  "object": "$10M DOE grant via OSI and Groundwork USA",
  "sources": ["annual-report-y5", "press-release-2024-09-15"],
  "source_types": ["annual-report", "press-release"],
  "confidence": 2,
  "status": "confirmed",
  "dark_matter": false,
  "topics": ["topics/bryant-neighborhood-decarbonization", "initiatives/district-geothermal"],
  "locations": ["locations/bryant-neighborhood", "locations/bryant-community-center"],
  "strategies": ["strategy-1", "strategy-6"],
  "actors": ["actors/osi", "actors/groundwork-usa", "actors/us-doe"],
  "keywords": ["geothermal", "bryant", "federal-grant", "decarbonization"],
  "fund_type": "federal-grant",
  "commitment_status": null,
  "last_updated": "2026-06-18"
}
```

**Source tiers — used for confidence scoring and status assignment:**

- **Tier 1:** Official documents produced by the governing entity — annual reports, the Climate Action Plan, council resolutions, contracts, RFPs, official press releases. A single Tier 1 citation produces `confidence: 1` and `status: confirmed`.
- **Tier 2:** Third-party documents — news articles, advocacy organization reports, academic studies, third-party evaluations. A single Tier 2 citation produces `confidence: 1` and `status: pending`. Two independent Tier 2 citations (published more than 7 days apart, Source B does not cite Source A) produce `confidence: 2` and `status: confirmed`.

**Confidence scoring:**
- `1` = single Tier 1 source, or single Tier 2 source (pending)
- `2` = two independent Tier 1 sources, or one Tier 1 + one Tier 2, or two independent Tier 2 sources
- `3+` = three or more independent sources across any tier; treat as established

**Status values:**
- `confirmed` = confidence ≥ 1 from a Tier 1 source, or ≥ 2 from independent Tier 2 sources
- `pending` = single Tier 2 source, awaiting corroboration
- `dark-matter` = referenced as context by confirmed quads but has no direct evidence of its own
- `disputed` = multiple sources with conflicting claims — links to contradiction page

### 7.2 `blackboard/sources_index.json`

Maps every source_uuid to its file paths and excerpt map for provenance resolution.

```json
{
  "annual-report-y5": {
    "uuid": "annual-report-y5",
    "title": "A2ZERO Annual Report Year 5 (2024-2025)",
    "date_published": "2025-06",
    "source_type": "annual-report",
    "jurisdiction": "ann-arbor",
    "bronze_path": "bronze/a2zero-year5-original.pdf",
    "silver_path": "silver/annual-report/annual-report-y5.md",
    "excerpt_map": {
      "excerpt-001": {
        "text": "Our Solarize program reached 5.4MW of solar installed through the program",
        "location": "Strategy 1 section, paragraph 2"
      }
    }
  }
}
```

### 7.3 `blackboard/entity_aliases.json`

Canonical entity registry. Consulted before every entity creation. Updated by the deduplication script after every ingest run.

See Section 6.3 for schema. The deduplication script flags near-matches for human review — it does not auto-merge without human confirmation, because incorrect merges (deciding two different entities are the same) are harder to unwind than duplicate entries.

### 7.4 `blackboard/dark_matter.md`

Auto-generated after every ingest run. Never manually edited — edits will be overwritten on next run. If a gap is resolved (new quads collapse it), it is removed from the dossier automatically.

**Per-entry format:**
```markdown
### Gap: [brief description] — [duration] — [priority: HIGH|MEDIUM|LOW]

**Period:** YYYY-MM to YYYY-MM  
**Bounding events:**  
- Before: [event description] (source: uuid, date: YYYY-MM)  
- After: [event description] (source: uuid, date: YYYY-MM)  
**Domain logic suggests:** [What intermediate steps would typically occur here. LABELED AS INFERENCE.]  
**Suggested sources:** [Specific databases, document types, or organizations to check]  
**Interview question:** "[Specific question for a community interview]"  
**Related entities:** [entity slugs]  
**Topics:** [topic slugs]
```

Priority scoring: HIGH = gap > 6 months between causally-connected events with high-confidence bounding quads; MEDIUM = 3–6 months or lower-confidence bounds; LOW = < 3 months or loosely connected events.

---

## 8. Sub-Timeline Filtering

Sub-timelines are filtered views of `quads.jsonl`. They are not separate files maintained independently. Three consumers query the blackboard differently:

### 8.1 Filter Dimensions

Every quad must be tagged across all applicable dimensions during ingest:

| Dimension | Field in quad | Values |
|---|---|---|
| Topic/Initiative | `topics` | List of wiki page slugs |
| Location | `locations` | List of location page slugs |
| Strategy | `strategies` | `strategy-1` through `strategy-7` |
| Actor | `actors` | List of actor page slugs |
| Keyword | `keywords` | Free-form strings; minimum 2 |
| Funding type | `fund_type` | See funding sub-types |
| Source type | `source_types` | `annual-report`, `council-transcript`, etc. |
| Commitment status | `commitment_status` | `unverified` \| `fulfilled` \| `partial` \| `missed` \| `carried-forward` \| `null` |

`commitment_status` is populated only on quads derived from commitment pages. `null` for all other quads. This enables blackboard queries like "show me all missed commitments across the full timeline" or "which carried-forward commitments touch the Bryant neighborhood?" without needing to read individual commitment pages.

**The tagging rule:** Tag every relevant dimension, not just the most obvious one. A Bryant geothermal grant quad is tagged with geothermal keywords AND Bryant location AND Strategy 1 AND OSI actor AND DOE actor AND federal-grant fund_type. Conservative tagging creates artificial gaps in sub-timelines.

### 8.2 Consumer Query Patterns

**Dashboard visualization (data engineer):**
```python
# Python / DuckDB — geothermal sub-timeline
import duckdb
conn = duckdb.connect()
result = conn.execute("""
  SELECT date, subject, relation, object, confidence, status
  FROM read_ndjson('blackboard/quads.jsonl')
  WHERE list_contains(keywords, 'geothermal')
     OR list_contains(topics, 'topics/bryant-neighborhood-decarbonization')
  ORDER BY date
""").fetchall()
```

**LLM chat context (rendered markdown):**  
A pre-query script filters quads by topic/keyword and renders them as a dated markdown list. This filtered timeline is injected into the LLM's context window before the chat question is answered. The LLM reasons over the filtered timeline — it does not hallucinate events outside it.

**Dark matter scoped to a topic:**  
Gap detection runs on the filtered quad set. "What are the dark matter gaps in the geothermal story?" applies gap detection only to geothermal-tagged quads, producing targeted interview questions rather than a full-program gap list.

---

## 9. Post-Ingest Pipeline

The following scripts run automatically after every LLM ingest session. Steps 1–6 are fully automated. Human involvement begins after Step 6 completes, when the review-queue.md is ready (Step 7).

**Step 1 — LLM ingest completes**  
New/updated wiki pages written. New quads appended to quads.jsonl (raw, pre-dedup).

**Step 2 — Deduplication script**  
- Normalizes entity names via entity_aliases.json
- Groups quads by normalized (subject, relation, object)
- Merges duplicates: combines `sources` arrays, recalculates `confidence`
- Checks independence: flags source pairs where Source B cites Source A (prevents confidence inflation from circular reporting)
- Appends net-new quads; updates existing quads in place
- Updates entity_aliases.json with any new entities; flags near-matches for human review

**Step 3 — Staleness detection script**  
- Reads all quads added or updated in this run
- For each updated entity: scans all `wiki/synthesis/*.md` files for `invalidation-triggers` matches
- Flips matching synthesis pages from `status: current` → `status: needs-review`
- Does not regenerate — marks for human review

**Step 4 — Dark matter regeneration**  
- Runs gap detection on full quads.jsonl
- Finds pairs of quads where: subjects share entities, bounding events have high confidence, no intermediate quads exist within the temporal gap
- LLM call (temperature: 0.2): for each gap, reasons about what intermediate steps domain logic suggests
- Regenerates dark_matter.md completely — collapsed gaps removed, new gaps added

**Step 5 — Ingest-triggered synthesis check**  
- Checks whether any community-summary thresholds were crossed:
  - New initiative page spanning 4+ years → draft "Evolution of [Initiative]"
  - 3rd funding event of same fund_type → draft "[Fund-Type] Strategy in A2Zero"
  - New meeting page created → draft "Key Decisions: [Date]"
  - New actor page created → draft "Role of [Actor] in A2Zero"
  - 3rd commitment marked missed/carried-forward → draft "Persistent Implementation Challenges"
- If threshold met: LLM generates draft synthesis (temperature: 0.3), saves as `status: draft`

**Step 6 — Linter pass**  
- Checks all synthesis pages for synthesis-to-synthesis citations (hard violation)
- Checks all wiki pages for uncited factual claims (warning)
- Checks all new quads for missing required tags (warning)
- Generates linter report

**Step 7 — `review-queue.md` regenerated**  
Auto-generated at the project root after every ingest run. Replaces the previous version entirely. This is the primary human interface to the post-ingest pipeline — the team opens this file in Obsidian and works through it before the next ingest run.

Format:
```markdown
# Review Queue — [ingest-date] — [source-uuid ingested]

> Generated automatically. Clear items by checking the box.
> Items here do not block the next ingest — they compound if ignored.

## 🔴 Urgent (block synthesis queries until resolved)
- [ ] **Linter violation** — `wiki/synthesis/geothermal-overview.md` cites another synthesis page (`wiki/synthesis/bryant-overview.md`). Fix: replace with the primary page it should cite.
- [ ] **Verification flag** — `wiki/initiatives/district-geothermal.md` body contains claim not found in source: "Installation begins Spring 2025." Source `annual-report-y5` says only "planning underway." Delete or downgrade claim.

## 🟡 Normal (process within 3 days)
- [ ] **Synthesis needs review** — `wiki/synthesis/geothermal-overview.md` (status: needs-review). New quad added: district-geothermal / received federal grant / $10M. Regenerate or approve as-is.
- [ ] **New draft synthesis** — `wiki/synthesis/doe-grants-in-a2zero.md` (status: draft). 3rd federal grant ingested; auto-generated summary. Review for accuracy and promote.
- [ ] **Near-match entity** — New entity "Ann Arbor Sustainability Office" may duplicate "actors/office-of-sustainability-and-innovation". Confirm merge or create new alias.

## 🟢 Low priority (process before next major source type)
- [ ] **Dark matter HIGH** — Gap: 14 months between Bryant site selection (2022-08) and DOE planning grant (2023-10). Suggested source: Ann Arbor RFP database, geothermal planning services 2022–2023.
- [ ] **Missing tags** — 3 quads from `annual-report-y5` have no `locations` tag. Review and retag.
- [ ] **Draft synthesis** — `wiki/synthesis/missy-stults-role.md` (status: draft). New actor page created. Review.

## ✅ Cleared this run
- [x] Synthesis `wiki/synthesis/solarize-overview.md` — approved as-is (2026-06-18)
```

Human picks up here. The policy expert processes 🔴 items. The project coordinator processes 🟡. 🟢 items can be batched into the next research agenda sprint.

---

## 10. Synthesis Pages

### 10.1 Two Generation Modes

**Ingest-triggered (community summaries)**  
Generated by threshold conditions during post-ingest pipeline (Step 5). These bootstrap the synthesis layer without waiting for user queries. They summarize the structural state of the knowledge graph at a given point in ingest.

**Query-triggered**  
Generated when a user question in the chat interface doesn't match any existing `status: current` synthesis page. Requires human review (status: draft) before being promoted to current and served from cache.

### 10.2 Retrieval Logic

1. Query arrives → semantic match against synthesis index
2. Match found, `status: current` → serve cached answer + citations. `retrieval-count++`. No new LLM tokens spent.
3. Match found, `status: needs-review` → serve with warning banner: "Updated sources available — this summary may be outdated." Queue for human regeneration.
4. No match → generate new answer from filtered wiki context. Save as `status: draft`. Human reviews before promotion.
5. Low-quality generation (LLM cannot synthesize well) → flag as wiki coverage gap. Generate dark matter dossier entry for the topic.

### 10.3 Lifecycle States

`draft` → human review → `current` → new quads trigger invalidation → `needs-review` → human regenerates → `draft` → ...

The `last-reviewed` field stamps when a human last validated the page, regardless of whether they regenerated it.

### 10.4 Hard Rules

1. `sources-cited` must never contain a `wiki/synthesis/` path.
2. `sources-cited` must contain at least 2 entries.
3. Synthesis pages never enter `quads.jsonl`.
4. `status: current` requires human to have set `last-reviewed`.
5. Low-quality synthesis that cannot be grounded in at least 2 sources is not saved — it becomes a dark matter dossier entry instead.

---

## 11. Provenance Chain

Every claim in the dashboard must be traceable to a specific passage in a specific Bronze document. The chain:

```
Dashboard citation badge
  → source_uuid
    → sources_index.json lookup
      → silver_path (cleaned markdown) + excerpt_map entry (highlighted passage)
        → bronze_path (original raw document, immutable)
```

### 11.1 Inline Citation Format in Wiki Pages

Wiki body prose uses inline citations at the sentence level:

```markdown
The Solarize program reached 5.4MW of total residential solar installed through the program,
just short of the Year 5 target of 5.5MW (source: annual-report-y5, excerpt: excerpt-047).
```

The `excerpt` reference points to a specific entry in `sources_index.json`'s `excerpt_map` — not just the document, but the passage.

### 11.2 Dashboard Resolution

The dashboard's citation component:
1. Receives `source_uuid` + `excerpt_id`
2. Looks up `sources_index.json`
3. Displays: document title, date, source type, highlighted excerpt text
4. Provides link to Bronze file

Decision-makers see the exact passage the claim came from. This is the anti-slop guarantee.

---

## 12. Relationship Language

The following verbs are the only permitted relationship terms in wiki prose and in wikilinks. **"Related to" is banned.** Use the most specific verb available — specificity is what makes the wiki useful for replication.

### Program-to-Program Relationships

| Relationship type | Permitted verbs |
|---|---|
| Implementation | `implements`, `operationalizes`, `executes` |
| Funding | `funds`, `co-funds`, `matches`, `leverages` |
| Temporal | `preceded`, `succeeded`, `superseded`, `carried forward from` |
| Structural | `is part of`, `encompasses`, `authorized by` |
| Evidentiary | `fulfills`, `partially fulfills`, `fails to fulfill`, `contradicts` |
| Causal | `enabled`, `blocked`, `accelerated`, `triggered` |
| Locational | `is sited at`, `serves`, `anchors` |

### Actor-to-Program Relationships

| Relationship type | Permitted verbs | Example |
|---|---|---|
| **Leadership / Authority** | | |
| Formal leadership | `leads`, `directs`, `oversees` | OSI leads the A2Zero implementation |
| Governance | `chairs`, `convenes` | Councilmember Radina chairs the Sustainability Commission |
| Legal authority | `authorized by`, `approved by` | Geothermal contract authorized by City Council |
| Appointment | `appointed by`, `appointed` | OSI Director appointed by the Mayor |
| Accountability | `reports to` | OSI reports to the City Administrator |
| Regulatory | `oversees` (for regulatory actors) | MPSC oversees DTE rate cases |
| **Collaboration / Partnership** | | |
| Joint leadership | `co-leads`, `co-directs` | OSI and Groundwork USA co-lead the Bryant project |
| Partnership | `partners with` | City partners with University of Michigan on EV infrastructure |
| Contracting | `contracted`, `was contracted by` | City contracted DTE Energy Services for the energy audit |
| Advisory | `advises`, `consulted on` | Building Decarbonization Coalition advises OSI on building policy |
| Grant co-applicant | `co-applied for` | OSI and Groundwork USA co-applied for the DOE grant |
| Subcontracting | `subcontracted to` | Prime contractor subcontracted installation to local firm |
| Fiscal sponsorship | `fiscally sponsored` | Groundwork USA fiscally sponsored community outreach |
| **Political / Civic** | | |
| Legislative sponsorship | `sponsored` | Councilmember X sponsored the SEU ordinance |
| Voting | `voted for`, `voted against` | Councilmember Y voted against the resolution |
| Advocacy | `advocated for`, `advocated against` | BDC advocated for stricter building codes |
| Opposition | `opposed` | DTE opposed the SEU ballot measure |
| Public testimony | `testified at` | Dr. Stults testified at the MPSC hearing |
| Community organizing | `organized`, `mobilized` | Local nonprofit organized the millage petition campaign |
| Endorsement | `endorsed` | Mayor endorsed the Climate Action Millage campaign |

**Key principle for actor relationships:** Use the most specific verb available. "Involved in" and "participated in" are banned for the same reason "related to" is — they obscure the actual relationship. "OSI co-applied for the DOE grant alongside Groundwork USA" transfers to another city. "OSI was involved in the DOE grant" does not.

---

## 13. Research Agenda (External)

See Section 3 for the `research-agenda.md` format. Key operating principle:

The LLM extraction pipeline never reads `research-agenda.md`. Research priorities govern:
- Which Bronze documents are sourced and ingested (source selection)
- Which mechanism pages get written first (synthesis investment)
- Which topics get targeted in dark matter dossier follow-up

Research priorities do NOT govern:
- What gets extracted from any given source document
- Which page types get created
- Confidence scoring

---

## 14. Known Trouble Spots

These are specific risks in this design with known mitigation strategies. They should be reviewed before implementation planning.

### TS-0: LDP threshold miscalibration

**Risk:** The LDP trigger thresholds (`1000 lines + 10 headings`) are starting estimates. If the thresholds are too high, a document that needs map-driven chunking falls through to single-pass and produces positional hallucinations (facts attributed to the wrong section, temporal claims from the wrong year). If too low, simple documents get a structure pre-pass that adds latency and cost without benefit.  
**Mitigation:** After the first 3–4 LDP ingest runs, the data engineer reviews the trigger log: which documents triggered LDP, which didn't, and whether the chunking produced well-attributed quads. Adjust thresholds accordingly. The right calibration is: every document where positional context matters for fact attribution should trigger LDP.  
**Still a concern:** Heading count is a proxy for structural complexity, not a perfect measure. A document with many headings but very short sections (a glossary, a FAQ) may trigger LDP unnecessarily. Adding a minimum section length check (e.g., average lines-per-section > 30) can filter these out in a future iteration.

### TS-1: Entity drift at scale

**Risk:** As the wiki grows past ~200 entity pages, the LLM will begin creating slight variations of existing entities (e.g., "Office of Sustainability and Innovations" alongside "Office of Sustainability and Innovation"). Entity drift makes sub-timeline filtering unreliable and confuses the deduplication script.  
**Mitigation:** The entity alias table + linter catches most cases. But the alias table needs periodic human audits — schedule one after every 10 new source files ingested. Flag any entity with only 1 associated quad for review.  
**Still a concern:** Semantic drift (different descriptions of the same program concept) won't be caught by string matching. An LLM-based periodic consolidation pass is eventually needed.

### TS-2: Temporal hallucination in long documents

**Risk:** The 150-page Climate Action Plan, if processed in too few chunks, will cause the LLM to confuse which year a fact is from, or to apply a 2020 target to a 2024 claim. "Needle-in-a-haystack" failures consistently affect content in the middle of long documents.  
**Mitigation:** Chunk by section, not by page count. Each chapter/strategy section is a separate LLM call. The section header is included at the top of each chunk so the LLM always knows what section it's reading.  
**Still a concern:** Some claims span sections. Cross-section facts need a separate consolidation pass.

### TS-3: Diarization errors in council transcripts

**Risk:** Diarized transcripts will contain speaker attribution errors. If Councilmember A's argument is attributed to Councilmember B in the wiki, this creates false actor position records that are hard to detect and can mislead analysis.  
**Mitigation:** Set a diarization confidence threshold before ingest. Flag any speaker attribution with `(attribution: uncertain)` in the meeting page. Never assert a speaker's position based on uncertain attribution.  
**Still a concern:** If the diarization pipeline doesn't output confidence scores, all attributions are uncertain. Requires manual spot-checking of meeting pages against audio/video.

### TS-4: Circular independence in confidence scoring

**Risk:** The confidence score increases when multiple sources confirm a fact. But if Source B (a news article) simply reprints Source A (a press release), that's not independent confirmation — it's one source citing another. The current deduplication script is designed to check for this, but detecting it is an unsolved NLP problem at this scale.  
**Mitigation:** Manual heuristic: two sources published within 48 hours of each other making the same specific claim — flag for human review before auto-incrementing confidence. Require `confidence ≥ 2` from sources published more than 7 days apart before treating as independently confirmed.  
**Still a concern:** This is imperfect. `confidence` scores should be treated as directional signals, not precise measurements.

### TS-5: Synthesis staleness detection with inconsistent tagging

**Risk:** The staleness detection script matches new quads against synthesis `invalidation-triggers`. But if the LLM tagged an event as `geothermal` in one ingest run and `district-heat-pump` in another, a synthesis page about geothermal may not be flagged as stale when it should be.  
**Mitigation:** The entity alias table mitigates this for entity names. For free-form keywords, the linter checks for keyword consistency against a controlled vocabulary list (to be defined during implementation). Adding a new keyword to that list triggers a one-time re-tagging pass for affected quads.  
**Still a concern:** Building and maintaining the controlled vocabulary is ongoing work.

### TS-6: Dark matter gap reasoning hallucination

**Risk:** When the LLM reasons about "what should be between these two events," it may invent plausible-sounding intermediate steps that sound authoritative but are fabrications. If these inferences leak into the wiki as facts, the knowledge base is corrupted.  
**Mitigation:** The dark_matter.md file must be explicitly labeled as inference throughout, never as established fact. The dossier contains research questions, not assertions. The linter checks that dark_matter.md content never appears verbatim in wiki pages.  
**Still a concern:** The boundary between "reasonable inference" and "hallucination" is not always clear. Human judgment is required on all dark matter gap reasoning outputs.

### TS-7: Schema creep over time

**Risk:** As more source types are ingested, the LLM may begin creating page types that aren't in the schema (e.g., a `policy` type, a `vote` type). This fragments the wiki and breaks the sub-timeline filtering.  
**Mitigation:** The linter checks `type:` field in all frontmatter against the list of 14 permitted types. Any unknown type is flagged and the page is quarantined until a human decides whether to merge it into an existing type or update the schema.  
**Still a concern:** Schema evolution is legitimate — at some point you may genuinely need a 15th page type. When that happens, it requires a deliberate schema update + a migration pass over existing pages, not ad-hoc creation.

### TS-8: Synthesis linter enforcement

**Risk:** The hard rule "synthesis pages never cite other synthesis pages" requires a linter to enforce it, because the LLM will violate this rule occasionally. If the linter isn't running, synthesis chains will form and errors will propagate.  
**Mitigation:** The linter in Step 6 of the post-ingest pipeline checks every `sources-cited` list for synthesis slugs. This must run on every ingest — it cannot be optional.  
**Still a concern:** Query-triggered synthesis generated outside the ingest pipeline (directly in the chat interface) bypasses the post-ingest linter. The chat synthesis generation prompt must include the rule explicitly.

### TS-9: `last-reviewed` discipline

**Risk:** If humans approve `needs-review` synthesis pages without actually reviewing them (just stamping `last-reviewed` to clear the queue), the staleness system provides false assurance.  
**Mitigation:** Document review expectations for the team. A `needs-review` page should take < 5 minutes to assess — the reviewer reads the page, notes what changed in the new quads, and decides: approve as-is (minor change), regenerate (significant new information), or add a dated note at the top of the page.  
**Still a concern:** This is a process discipline issue, not a technical one. It requires team alignment.

### TS-10: Version control discipline

**Risk:** Wiki pages are modified across multiple ingest runs. Without disciplined git commits, it becomes impossible to audit what changed, when, and why. Rollback of a bad ingest run requires git.  
**Mitigation:** Every ingest run should be a single git commit with a message: `ingest: [source-uuid] [source-type] — [N pages created/updated] [M quads added]`. The ingest pipeline should auto-generate this commit message.  
**Still a concern:** If ingest runs are done manually (not through an automated script), commit discipline depends on the human operator.

---

## 15. Open Questions

### Resolved

**Q1: Chunk boundaries for the Climate Action Plan** ✓  
**Decision:** Structural pre-pass first — pass the full document at temperature 0 to extract a section map as JSON (`blackboard/section_maps/cap-2020_structure.json`). Use that map to drive all subsequent chunking. The CAP is organized as intro + 7 strategy chapters + appendices; each chapter is a separate extraction call. See Sections 5.0 and 5.2 for full protocol.

**Q3: Review queue tooling** ✓  
**Decision:** `review-queue.md` at the project root, auto-generated after every ingest run. Readable in Obsidian alongside all other wiki content. Zero infrastructure for the prototype phase; can be graduated to a web UI later without changing the pipeline. Policy expert handles 🔴 items; coordinator handles 🟡; 🟢 items batch into research agenda sprints. See Section 9, Step 7 for full format spec.

**Q4: Controlled vocabulary for keywords** ✓  
**Decision:** Organic, bottom-up. First 3 ingest runs use free-form keyword extraction — LLM extracts whatever keywords it sees in sources. After those runs, data engineer runs frequency analysis on `quads.jsonl` keywords; team reviews top 50 and formalizes a controlled list from what emerged. This produces a vocabulary grounded in the actual source material rather than one imposed before ingest begins. The linter enforces the controlled vocabulary after it is established.

---

### Open

**Q2: Diarization confidence threshold**  
What confidence score from the WhisperX pipeline should be required before a speaker attribution is treated as reliable? This needs to be set in consultation with the data engineer based on the quality of available audio files. If the pipeline doesn't output per-utterance confidence scores, all attributions are flagged as uncertain and require spot-checking.

**Q5: Git repository structure**  
Should the wiki, blackboard, bronze, and silver all live in the same git repository? Or separate repos (e.g., bronze/silver in a data repo, wiki in a content repo)? Affects access control and repo size as PDF/MP4 files accumulate. For the prototype, a single repo is simplest. Splitting is a migration task once the scale warrants it.

**Q6: Synthesis review ownership**  
Who on the team reviews and approves synthesis pages — the project coordinator, policy expert, or both? The policy expert has the domain knowledge to catch factual errors; the project coordinator understands the Grapevine use case. Suggest: policy expert reviews for accuracy, coordinator approves for relevance. Needs explicit team agreement before the first synthesis pages are generated.

**Q7: Mechanism page generation trigger**  
When is the first mechanism page written? After all 5 annual reports + CAP ingested? After the first council transcripts? Or only after the research team has identified a specific mechanism they believe is present in the data? This needs a deliberate decision — mechanism pages are the product, and premature generation produces low-confidence claims. Recommendation: write the first mechanism page after annual reports + CAP are ingested and the research team has reviewed the dark matter dossier for patterns.

---

*Spec written collaboratively by Caleb Johnson and Claude Sonnet 4.6, 2026-06-18.*  
*Next step: invoke writing-plans skill to produce implementation plan.*
