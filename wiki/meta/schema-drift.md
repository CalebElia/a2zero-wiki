# Schema Drift Log

Append-only record of LLM-proposed page types or relationship verbs that had no
approved match. The pipeline writes the page using the closest approved fallback
type and adds `proposed-type: <new-type>` to the page's frontmatter, then logs the
proposal here for human review.

To approve a proposed type: add it to `VALID_PAGE_TYPES` in `pipeline/wiki_pages.py`
and remove the `proposed-type:` line from affected pages.
To reject: leave the fallback in place; optionally add a tag to the affected pages.

## Format

```
## YYYY-MM-DD | Proposed type: "<new-type>" | Written as: "<fallback>" | Page: "<slug>"
Title: <page title>
Resolution: [ ] Approve new type  [ ] Keep as fallback + tag [<tag>]
```

---
