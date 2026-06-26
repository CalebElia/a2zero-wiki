# Relationship Lexicon

Canonical reference for all relationship vocabulary in the A2Zero wiki.
Three layers: frontmatter fields (machine-readable), prose verbs (body text), and
quad relations (open-vocabulary structured triples). The LLM is instructed to prefer
these and to propose additions to `schema-drift.md` when none fit.

---

## Layer 1 — Frontmatter Relationship Fields

These are typed, machine-readable predicates encoded as YAML fields. They are the
primary relationship mechanism — downstream agents query these directly without
prose parsing.

| Field | Appears on | Points to | Cardinality |
|---|---|---|---|
| `parent-strategy` | initiative | `strategies/<slug>` | single |
| `party-responsible` | initiative | `actors/<slug>` | single |
| `partners` | initiative | `actors/<slug>` list | list |
| `related-strategies` | initiative | `strategies/<slug>` list | list |
| `source-first-seen` | all page types | `sources/<type>/<uuid>` | single |
| `funder` | funding-event | `actors/<slug>` | single |
| `recipient` | funding-event | `actors/<slug>` or `initiatives/<slug>` | single |
| `funds-initiatives` | actor | `initiatives/<slug>` list | list |
| `affiliation` | actor | `actors/<slug>` (parent org) | single |
| `parent-location` | location | `locations/<slug>` | single |
| `actor` | framing | `actors/<slug>` (who carried the framing) | single |
| `related-initiative` | framing | `initiatives/<slug>` | single |
| `related-event` | framing | `political-events/<slug>` | single |
| `sources` | contradiction, overview | `sources/<type>/<uuid>` list | list |
| `agenda-items` | meeting | `initiatives/<slug>` or `political-events/<slug>` list | list |
| `decisions` | meeting | free-text or wikilink list | list |
| `programs-authorized` | political-event | `initiatives/<slug>` list | list |
| `programs-involved` | political-event | `initiatives/<slug>` list | list |
| `wiki-overview` | source file (auto-added) | `overviews/<uuid>` | single |

All wikilinks use vault-relative paths with no leading `wiki/`.
Example: `party-responsible: "[[actors/office-of-sustainability-and-innovations]]"`

---

## Layer 2 — Approved Body-Prose Verbs

Use these in narrative sentences. Never write "related to." Use specific verbs.

| Verb | Example use |
|---|---|
| `implements` | An initiative implements a strategy |
| `funds` | A funding-event funds an initiative |
| `supersedes` | A new program supersedes a retired one |
| `gates` | A political-event gates the launch of an initiative |
| `enables` | A technology enables an initiative |
| `is part of` | A meeting is part of a deliberative process |
| `was planned in` | An initiative was planned in a source document |
| `fulfilled in` | A projection was fulfilled in a later source |
| `missed in` | A projection was missed in an annual report |
| `contradicts` | A claim contradicts another source |
| `targets` | A program targets a population or outcome |
| `partners with` | An actor partners with another actor |
| `is administered by` | An initiative is administered by an actor |

---

## Layer 3 — Quad Relations

`relation:` values in `blackboard/quads.jsonl` are **intentionally open-vocabulary**.
The LLM generates the most precise natural-language predicate for each triple —
there is no approved list here. Quad schema design (controlled vocabulary, granularity,
cardinality rules) is a separate work item pending before `--quads-only` runs at scale.

Current usage in `blackboard/quads.jsonl`: see that file for live examples of
LLM-generated relation phrases across the CAP-2020 and Year-1 ingests.

---

## Proposing a New Verb (Layers 1 or 2)

If none of the approved Layer 1 fields or Layer 2 verbs fit:

1. Use the closest match in your prose or frontmatter
2. Append an entry to `wiki/meta/schema-drift.md` with the proposed verb, an example
   sentence, the entity type it connects, and the rationale
3. Human curators promote the verb to this file on approval

Do not add a new frontmatter field name without human approval — undocumented fields
are invisible to downstream agents that query by field name.
