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
