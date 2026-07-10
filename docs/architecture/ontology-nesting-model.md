# Ontology Nesting Model — Plan → Strategy → Initiative → sub-initiative

## Fixing Two Missing Layers of Containment in the Entity Graph

*Decided and implemented: 2026-07-09. Follows the semantic-lint review-queue session documented in `docs/action-plan-2026-07-09.md` Item 2.*

---

## The problem this solves

The A2Zero wiki's ontology is genuinely nested, several levels deep:

```
Plan (one per city)
  └── Strategy (a pathway for enacting the plan — 7 for A2Zero)
        └── Initiative / Program (contributes to the strategy)
              └── sub-initiative / pilot / project (a specific instantiation the program spins off)
```

A parallel nesting exists on the actor side (a governing body composed of specific
individuals who take specific actions), handled separately by the `affiliation` /
`sub-bodies` / `key-personnel` fields (added 2026-07-07, unaffected by this change).

Before 2026-07-09, only the **Strategy → Initiative** layer had real machine-readable
support (`parent-strategy` / `related-strategies`, confirmed bidirectionally queryable
via `pipeline/phase_c_synthesize.py::gather_strategy_entities`). The two layers above
and below it were unmodeled:

**Plan → Strategy was inverted, not just missing.** The canonical "A2Zero" page
(`initiatives/a2zero-carbon-neutrality-plan.md`, the entity `registry/entity_aliases.json`
resolves "A2Zero"/"A2ZERO" to) was itself typed `initiative` and carried
`parent-strategy: strategies/strategy-7-engagement` — nesting the Plan *underneath*
one of its own seven child strategies. Every "roll up to the Plan" query inherited
this inversion at the root of the tree.

**Initiative → sub-initiative had zero frontmatter support**, confirmed by a targeted
research pass: no page among 230 initiatives used any containment-shaped field, and
`partners:` — despite CLAUDE.md's note that initiative slugs "already appear inside
it dozens of times" — was not silently carrying the relationship either (only 2 of
230 `partners:` lists contain any `initiatives/` link at all, and neither is a
parent/child pair). The gap showed up concretely during a semantic-lint review:
`initiatives/community-solar-program.md` (CAP-2020's ongoing effort) and
`initiatives/community-solar-pilot.md` (one specific project under it) had been
merged into a `superseded-by`/`TEMPORAL_SUCCESSION` relationship — treating "the
pilot replaces the program" when the real relationship is "the pilot is one
instantiation of the program's ongoing work; the program continues and could spawn
further pilots." The same review found `solarize-ann-arbor.md` /
`commercial-solarize-pilot.md` had the identical shape, undetected until then.

This is a structural gap, not a one-off mislabel: any LLM extraction or lint pass
comparing a longstanding program against something spun off from it has no field to
express "child instantiation of an ongoing parent," so it defaults to the two
relationship types that *do* exist — same-entity (merge) or retired-entity
(supersession) — both wrong for this shape.

---

## The fix

### 1. New page type: `plan`

`wiki/plans/<slug>.md`, sitting structurally above `strategy` the same way `strategy`
already sits above `initiative` (itself given its own dedicated type/directory rather
than folded into a broader type, for the same reason). `initiatives/a2zero-carbon-neutrality-plan.md`
was migrated to `plans/a2zero-carbon-neutrality-plan.md`: `parent-strategy` and
`related-strategies` stripped (a Plan doesn't belong to one of its own children), a
new `strategies:` list added (the plan's children, inverse of the strategy pages'
new `parent-plan:` field).

**Why a new type instead of just fixing the pointer direction:** Grapevine's stated
premise is multi-city replication. A "plan" type means every future city gets exactly
one `plans/<slug>.md` node, and a cross-city query ("what does City X's plan define,
compared to Ann Arbor's") has a real type to anchor on. Leaving it typed `initiative`
with a corrected pointer would have fixed today's inversion without buying that.

**The `strategies:` field also closes part of the "de-hardcode the 7-strategy
assumption" gap** (`docs/action-plan-2026-07-09.md` Item 8) for the Plan→Strategy
direction specifically: `pipeline/phase_c_synthesize.py::_load_strategies_from_plan()`
reads the Plan page's `strategies:` list as the source of truth for which strategy
pages Phase C rebuilds, falling back to the hardcoded `ALL_STRATEGIES` Python constant
only when no `plans/` page exists yet (e.g. before this migration, or for a wiki that
hasn't adopted the Plan type). A second city's plan with a different strategy count
works without touching `phase_c_synthesize.py`. `ALL_STRATEGIES` itself is untouched
and remains the fallback — several tests assert its literal length is 7, which is
still true for A2Zero specifically.

### 2. New Layer 1 field pair: `part-of` / `sub-initiatives`

Strict containment, modeled directly on the existing `affiliation`/`sub-bodies`
inverse-pair pattern (same "direct subordinate only, keep it a tree" rule). The child
initiative points up via `part-of`; the parent lists its direct children via
`sub-initiatives`. Applied to the two confirmed cases:

- `initiatives/community-solar-pilot.md` → `part-of: '[[initiatives/community-solar-program]]'`
- `initiatives/solarize-ann-arbor.md` → `sub-initiatives: ['[[initiatives/commercial-solarize-pilot]]']`

**Explicitly out of scope for this field:** a governing body that *produces* a
deliverable (`initiatives/circular-economy-working-group.md` writing
`initiatives/circular-economy-strategy.md`) is a related-but-distinct pattern — the
working group isn't "part of" the strategy it wrote, nor is the strategy "part of"
the working group. That pair is intentionally left as prose-only cross-links ("produced
by the Circular Economy Working Group" / "tracked as its own initiative"); no
produces/produced-by field has been proposed. Don't conflate the two when applying
`part-of` to future pairs — see `meta/relationship-lexicon.md` for the full writeup
of both patterns side by side.

A third borderline case surfaced during the same review, `initiatives/sustainable-food-working-group.md`
/ `initiatives/ann-arbor-sustainable-food-framework.md`, where the relationship reads
looser ("complements" rather than "produces" or "instantiates") — left unfielded,
flagged for a human call rather than forced into either pattern.

### 3. Actor-hierarchy backfill (no schema change)

The `sub-bodies`/`key-personnel` fields added 2026-07-07 were confirmed well-designed
but barely populated (2/154 and 1/154 actor pages respectively) — a backfill gap, not
a modeling gap. Two concrete fixes landed alongside the schema work above:

- `actors/ann-arbor-city-council.md` — added `key-personnel:` listing the 9
  councilmembers its own body prose already named as resolution sponsors (all 9
  already had their own actor pages; this was pure connectivity, not new content).
- `actors/missy-stults.md`, `actors/simi-barr.md`, `actors/julie-roth.md` — `affiliation`
  corrected from `actors/city-of-ann-arbor` to `actors/office-of-sustainability-and-innovations`,
  matching OSI's own `key-personnel:` list, which already claimed all three. The
  lexicon's own tree rule ("only list a *direct* subordinate... via its own
  `affiliation` pointing up") had already drifted out of sync within two days of the
  fields being added — worth a periodic consistency check rather than a one-time fix.

---

## What this doesn't solve

- **Deeper actor backfill.** Only the single highest-value case (City Council) and
  one specific inconsistency were fixed. A systematic pass across all 154 actor pages
  — which orgs should have `sub-bodies`, which named individuals recur enough to
  warrant `key-personnel` — is still open.
- **Produces/produced-by.** No field exists yet for the body/deliverable pattern
  (working group → strategy document). If more instances of this shape turn up,
  it's a separate Layer 1 proposal, not an extension of `part-of`.
- **Multi-plan / multi-strategy-set generalization beyond the one field.** `strategies:`
  on the Plan page is read by `_load_strategies_from_plan`, but the rest of the
  pipeline (Pass 1B's stub-creation prompts, `SCHEMA.md`'s "7 A2Zero strategies"
  framing throughout) still assumes exactly 7 in various places. This is the narrow
  slice of Item 8 that this change closes, not the whole item.
