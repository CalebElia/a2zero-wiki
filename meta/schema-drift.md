# Schema Drift Log

Append-only record of LLM-proposed page types or relationship verbs that had no
approved match. The pipeline writes the page using the closest approved fallback
type and adds `proposed-type: <new-type>` to the page's frontmatter, then logs the
proposal here for human review.

To approve a proposed type: check `[x] Approve new type` below and run
`python -m pipeline.phase_b_lint --wiki-root wiki --apply` — this adds the type to
`registry/valid_page_types.json` (loaded into `VALID_PAGE_TYPES` in `pipeline/_pages.py`)
and strips `proposed-type:` from affected pages.
To keep the fallback: check `[x] Keep as fallback + tag [<tag>]` and run the same
`--apply` command — this tags the affected page instead.
Either way, the entry stays here with a `**Resolved ...**` marker appended (this file
is append-only, entries are never deleted).

## Format

```
## YYYY-MM-DD | Proposed type: "<new-type>" | Written as: "<fallback>" | Page: "<slug>"
Title: <page title>
Resolution: [ ] Approve new type  [ ] Keep as fallback + tag [<tag>]
```

---

## 2026-07-02 | Proposed type: "startup-funding-award" | Written as: "funding-event" | Page: "funding-events/ann-arbor-seu-startup-funding-2025"
Title: Ann Arbor SEU Startup Funding 2025
Resolution: [ ] Approve new type  [x] Keep as fallback + tag [<tag>]
**Resolved 2026-07-02: kept as fallback, tagged "<tag>"**
**Correction 2026-07-02: the "<tag>" placeholder was left unfilled and used literally — a human data-entry mistake, not a pipeline bug at write time (the parser now guards against this going forward). Manually corrected the page's tag to "startup-funding-award" instead.**


## 2026-07-02 | Proposed type: "project-award" | Written as: "funding-event" | Page: "funding-events/bryant-neighborhood-networked-geothermal-award-2025"
Title: Bryant Neighborhood Networked Geothermal Award 2025
Resolution: [ ] Approve new type  [x] Keep as fallback + tag [<tag>]
**Resolved 2026-07-02: kept as fallback, tagged "<tag>"**
**Correction 2026-07-02: the "<tag>" placeholder was left unfilled and used literally — a human data-entry mistake, not a pipeline bug at write time (the parser now guards against this going forward). Manually corrected the page's tag to "project-award" instead.**

