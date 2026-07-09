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
| `parent-plan` | strategy | `plans/<slug>` | single |
| `strategies` | plan | `strategies/<slug>` list | list |
| `parent-strategy` | initiative | `strategies/<slug>` | single |
| `part-of` | initiative | `initiatives/<slug>` (parent initiative) | single |
| `sub-initiatives` | initiative | `initiatives/<slug>` list (child initiatives) | list |
| `party-responsible` | initiative | `actors/<slug>` | single |
| `partners` | initiative | `actors/<slug>` list | list |
| `related-strategies` | initiative | `strategies/<slug>` list | list |
| `source-first-seen` | all page types | `sources/<type>/<uuid>` | single |
| `funder` | funding-event | `actors/<slug>` | single |
| `recipient` | funding-event | `actors/<slug>` or `initiatives/<slug>` | single |
| `funds-initiatives` | actor | `initiatives/<slug>` list | list |
| `affiliation` | actor | `actors/<slug>` (parent org) | single |
| `sub-bodies` | actor | `actors/<slug>` list (subordinate orgs) | list |
| `key-personnel` | actor | `actors/<slug>` list (`actor-type: person`) | list |
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

`sub-bodies` is the inverse of `affiliation` — used on a governmental umbrella actor
(e.g. `actors/city-of-ann-arbor`) to list its subordinate elected/appointed bodies,
departments, and commissions, each with its own page. Only list a *direct* subordinate:
a sub-body's own sub-bodies belong on that sub-body's page (via its own `affiliation`
pointing up), not duplicated in the parent's list, to keep the hierarchy a tree, not
a flattened index. Added 2026-07-07 to support governance sub-index pages.

`key-personnel` is also an inverse-of-`affiliation` list, but for named individuals
(`actor-type: person`) rather than institutions — an org's recurring leaders/staff,
not a subordinate body. Bar for inclusion is deliberately high: a person who recurs
across multiple sources in a substantive role (e.g. an office director), not every
staff name a source happens to mention once. A thin, single-citation person page is
not, by itself, grounds for listing someone here. Added 2026-07-07.

**The nesting hierarchy — Plan → Strategy → Initiative → sub-initiative, and Actor → sub-body/person — is expressed by three separate inverse-pair mechanisms, not one generic "part-of" relation.** Each pair below is a strict containment tree ("only list a *direct* subordinate," same rule as `sub-bodies` above) — do not conflate any of them with the many-to-many `related-strategies` tagging field, which lets one initiative legitimately serve multiple strategies and is not a hierarchy at all.

- `parent-plan` / `strategies` — a strategy points up to the plan it belongs to; the plan lists its child strategies. Added 2026-07-09 alongside the new `plan` page type (see `docs/architecture/ontology-nesting-model.md`) specifically so a second city's plan, with its own strategy count, doesn't require any pipeline code change — `pipeline/phase_c_synthesize.py::_load_strategies_from_plan` reads this field as the source of truth, falling back to the hardcoded `ALL_STRATEGIES` constant only when no `plans/` page exists yet.
- `part-of` / `sub-initiatives` — an initiative points up to the ongoing program/effort it is one specific instantiation of; the parent lists its child initiatives. This is the fix for a recurring extraction failure mode: an LLM comparing a longstanding program page (e.g. `initiatives/community-solar-program`) against a specific project spun off from it (e.g. `initiatives/community-solar-pilot`) tends to misread the pair as either a duplicate (propose MERGE) or a retirement (propose `superseded-by`/`TEMPORAL_SUCCESSION`) — when the real relationship is that the parent's ongoing work continues and could spawn further children. Added 2026-07-09 after this exact misread surfaced twice in one semantic-lint review pass (`community-solar-program`/`-pilot`, and implicitly `solarize-ann-arbor`/`commercial-solarize-pilot`, which had the same shape but hadn't yet been flagged).
- `affiliation` / `sub-bodies` / `key-personnel` — documented above. Same tree rule; covers Actor→sub-body and Actor→person specifically, not initiatives.

A body that *produces* a deliverable (e.g. `circular-economy-working-group` producing `circular-economy-strategy`) is a related-but-distinct pattern from `part-of`/`sub-initiatives` — the working group isn't "part of" the strategy it wrote, nor vice versa. That pair is currently modeled with prose cross-links only ("produced by the Circular Economy Working Group" / "tracked as its own initiative"); no frontmatter field has been proposed for produces/produced-by yet.

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
2. Append an entry to `meta/schema-drift.md` with the proposed verb, an example
   sentence, the entity type it connects, and the rationale
3. Human curators promote the verb to this file on approval

Do not add a new frontmatter field name without human approval — undocumented fields
are invisible to downstream agents that query by field name.
