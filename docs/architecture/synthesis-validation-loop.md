# Synthesis Validation Loop

## A Write → Validate → Revise Pipeline for `synthesize_wiki`

*Spec: 2026-06-29. Extends [knowledge-synthesis-architecture.md](./knowledge-synthesis-architecture.md). Pre-implementation.*

---

## The Problem This Solves

`synthesize_wiki` produces L1 (strategy synthesis) and L2 (`digest.md`) outputs that contain Obsidian wikilinks to entity pages. Every wikilink the LLM emits is a structural commitment — Obsidian treats unresolved links as broken edges in the graph view, and downstream pipeline passes that read `digest.md` will be misled by references to entities that don't exist.

In production runs across the Year 1 and Year 2 ingests, every synthesis pass has produced 3–8 ghost entity references per run. The class of failure repeats:

- **Invented subdivisions.** The LLM extrapolates plausible-sounding city departments (`actors/city-of-ann-arbor-systems-planning`, `actors/ann-arbor-recycling-and-solid-waste`) that don't correspond to any real wiki page.
- **Alias drift.** The LLM uses surface forms like `actors/a2zero-office` or `actors/a2zero-ambassadors` where a canonical page exists under a different slug.
- **Type misclassification.** Entities placed in the wrong field (locations in `core-actors`, initiatives in `core-actors`).
- **Generic groupings.** Collective nouns elevated to entity status (`actors/neighborhood-organizations`, `actors/local-landlords-property-owners`).

We have been responding to each instance by tightening the synthesis prompt, adding negative constraints, and growing a suppress list. This approach has two structural problems:

1. **It doesn't generalize.** Each ghost we suppress is one we already encountered. Novel hallucination patterns appear with every new source ingested and only surface during human review.
2. **It over-constrains.** Last iteration's `"only use slugs from the inventory"` rule wiped out `core-actors` for four strategies whose actor inventories were under-populated — a worse failure mode than the one it tried to prevent.

The synthesis prompt is being asked to do two things at once: generate high-quality analytical content, *and* enforce mechanical correctness. These goals trade off against each other. The fix is to separate them.

---

## The Architecture

A Write → Validate → Revise loop, modeled on the Writer → Evaluator → Editor pattern already used in `holistic_synthesizer.py`:

```
┌──────────┐    ┌────────────┐    ┌──────────┐
│  Writer  │──▶│  Validator │──▶│  Reviser  │──▶ output
└──────────┘    └────────────┘    └──────────┘
   LLM         deterministic         LLM
  (creative)    (mechanical)       (surgical)
```

Each stage has a single, well-defined responsibility:

**Writer (LLM).** Generates the synthesis with a permissive prompt optimized for analytical quality. Free to reach for plausible-sounding entities — that reach is where insight comes from. Identical to today's `build_strategy_synthesis()` and `build_digest_narrative()` calls, with the over-constraining language stripped back out.

**Validator (deterministic, no LLM).** Walks every wikilink and structured slug in the Writer's output. For each one, asks a single question: does the corresponding file exist in the wiki? Builds a report of broken references. No interpretation, no judgment — pure filesystem check.

**Reviser (LLM, scoped).** Receives the original Writer output plus the Validator's broken-slug report plus the available entity inventory. Returns a corrected version where each broken reference is either resolved to a real entity, demoted to plain text, or dropped. Never adds new content, never rewrites analysis, never invents.

The Reviser is only called when the Validator finds problems. Clean Writer outputs pass straight through.

### Two validation points, not one

The loop runs **twice per `synthesize_wiki` invocation**, at two distinct serialization boundaries:

1. **After `build_strategy_synthesis()`, before `write_strategy_synthesis()`.** This catches ghosts before they get written to the strategy page's `synthesis:` frontmatter. The frontmatter is the durable artifact — once a ghost lands there, it propagates to `digest.md` *and* survives every future `--digest-only` run that reads from existing frontmatter.

2. **After `build_digest_narrative()`, before `write_digest()`.** This catches ghosts the narrative LLM invents during digest assembly. Empirically, the narrative pass invents *different* ghosts than the synthesis pass — it reaches for plausible state-level actors (`actors/michigan-legislature`, `actors/michigan-public-service-commission`) that the synthesis didn't surface. Validating only at the frontmatter boundary would miss this entire class.

A scan of the current wiki confirms both failure modes coexist: three persisted ghosts live in strategy synthesis frontmatter (`actors/a2zero-ambassadors`, `actors/ann-arbor-greenbelt-advisory-commission`, `actors/nextcycle-michigan`), while a separate set of ghosts appears only in `digest.md` prose. Each validation point catches a class the other misses.

---

## What Each Stage Does and Doesn't Do

### Writer

**Does:** Produce a synthesis dict or narrative block that reflects the LLM's best analytical understanding of the strategy or cross-strategy patterns. Uses the current prompts with the inventory-bound constraints removed.

**Doesn't:** Worry about whether every slug it emits exists. Doesn't see the suppress list. Doesn't see prior validation failures. Stays naive on purpose — this is the analytical pass.

### Validator

**Does:**
- For structured outputs (strategy synthesis dicts): check that every slug in `core-initiatives`, `core-actors`, and `cross-strategy-links` corresponds to a file under `wiki/<type>/<slug>.md`.
- For narrative outputs (`digest.md` cross-strategy section): regex-match every `[[path/slug|display]]` wikilink and check the file exists.
- For each broken reference: record the slug, the field it appeared in (or "narrative"), and the surrounding context (the display name used, or the JSON field).
- Apply the type-sort and suppress-list logic that lives in `_resolve_synthesis_slugs()` today.
- Resolve any slugs that match the alias registry (this is fast and uncontroversial — keep the current alias resolution).

**Doesn't:**
- Make judgments about content correctness.
- Try to fix problems on its own beyond aliases and type-sorting — that's the Reviser's job.
- Surface bare entity-name mentions in prose ("the Systems Planning Unit is...") that lack a wikilink wrapper. Those are content errors, not link errors, and require a different kind of grounding (out of scope here).

**Output contract:** A `ValidationReport` dataclass:
```python
@dataclass
class BrokenRef:
    slug: str              # the unresolvable slug
    location: str          # "core-actors" | "narrative" | etc.
    display: str           # display name as it appeared
    context: str           # surrounding 80 chars (narrative only)

@dataclass
class ValidationReport:
    broken: list[BrokenRef]
    is_clean: bool         # True if broken is empty
```

### Reviser

**Does:** Receive the Writer output, the ValidationReport, and the strategy's entity inventory. Returns a corrected output. For each broken reference:
- **Try to resolve.** If a sufficiently-similar slug exists in the inventory, substitute it. ("Systems Planning Unit" → look for actors involved in waste/planning → no match → drop.)
- **Try to drop.** In structured fields, remove the slug entirely.
- **Try to demote.** In narrative prose, unwrap the wikilink: `[[actors/foo|Foo Bar]]` → `Foo Bar` (preserving readability, removing the false link).

**Doesn't:**
- See source documents. Its job is correction, not reinterpretation. The Writer made an analytical claim; the Reviser fixes the wikilink machinery around it without revisiting the claim.
- Add new entities or new prose.
- Rewrite year-over-year arc, open questions, or other analytical fields. Those are content; the Reviser only touches the link/slug layer.
- Run if the Validator returned no problems. Skipping when clean is the cost optimization.

**Reviser system prompt sketch:**
> You are correcting wikilinks in a synthesis document. You will receive:
> 1. The original synthesis
> 2. A list of broken references (slugs that don't exist as wiki pages)
> 3. The inventory of entities that DO exist
>
> For each broken reference, choose ONE action:
> - SUBSTITUTE with a real slug from the inventory, if and only if there is a clear match
> - DROP the slug entirely (from structured fields) or unwrap the wikilink to plain text (in prose)
>
> Do not invent new slugs. Do not add new content. Do not modify analytical fields beyond the link/slug layer. Return the corrected synthesis in the same JSON or markdown format you received.

---

## What This Catches and What It Misses

### Caught

- Broken `[[actors/foo]]` wikilinks where `wiki/actors/foo.md` does not exist
- Ghost slugs in any structured field
- Type-mismatched slugs (`locations/x` in `core-actors`, `initiatives/y` in `core-actors`)
- Alias drift (handled by existing alias resolution, retained inside the Validator)

### Not Caught

- **Bare entity names in prose with no link attempt.** "The Systems Planning Unit is driving X" with no wikilink reads fine to the Validator. This is a content-grounding problem, not a link problem.
- **Wrong attribution.** Real slug, false claim. ("`[[actors/dte-energy]]` led the GoPass expansion.")
- **Made-up facts about real entities.** Same reason — Validator only checks slugs.
- **Important entities missing from the synthesis.** Out of scope.

These limitations are intentional. They define the seam between *well-formedness* (the Validator's job) and *truthfulness* (a different problem, requiring different mechanisms — likely content grounding against source documents or the digest itself, addressed later in the architecture roadmap).

The honest framing: this loop makes synthesis outputs **structurally trustworthy** but not **factually grounded**. Structural trust is the precondition for the downstream pipeline (digest injection into the Comprehend pass) to work at all. Factual grounding is a follow-on problem.

---

## Cost and Performance

**Per strategy:** today is 1 LLM call. New design is 1 (Writer) + 0 (Validator, deterministic) + 0 or 1 (Reviser, conditional). On a clean run: same as today. On a run with broken refs in N of 7 strategies: 7 + N LLM calls.

**Per digest:** today is 1 narrative LLM call. New design is 1 (Writer) + 0 (Validator) + 0 or 1 (Reviser).

**Total worst case** (broken refs in every strategy and the digest): 7 + 7 + 1 + 1 = **16 calls vs. 8 today.** Two-thirds of those extra calls only fire when validation finds problems. As alias coverage matures and the LLM's vocabulary stabilizes, the conditional Reviser calls will trend toward zero.

`synthesize_wiki` runs roughly once per ingest (weekly at current pace). The cost increase is negligible.

---

## Where the Code Lives

A new module: `pipeline/synthesis_validation.py`. Public surface:

```python
def validate_synthesis(
    synthesis: dict,
    wiki_root: str,
    aliases: dict,
) -> tuple[dict, ValidationReport]:
    """Apply alias resolution + type-sort + suppress list, then check
    every remaining slug against the filesystem. Returns the
    (partially-corrected) synthesis and a report of what's still broken."""

def validate_narrative(
    narrative: str,
    wiki_root: str,
    aliases: dict,
) -> ValidationReport:
    """Parse all wikilinks in the narrative; report broken ones.
    Does not modify the narrative — narratives are revised in-place by the Reviser."""

def revise_synthesis(
    synthesis: dict,
    report: ValidationReport,
    inventory: list[dict],
) -> dict:
    """LLM call: correct the broken slugs in a structured synthesis dict."""

def revise_narrative(
    narrative: str,
    report: ValidationReport,
    inventory: list[dict],
) -> str:
    """LLM call: correct broken wikilinks in narrative prose."""
```

The orchestration in `synthesize_wiki()` becomes:

```python
synthesis = build_strategy_synthesis(...)             # Writer (unchanged)
synthesis, report = validate_synthesis(...)            # Validator
if not report.is_clean:
    synthesis = revise_synthesis(synthesis, report, inventory)  # Reviser
```

The existing `_resolve_synthesis_slugs()`, `_SUPPRESS_SLUGS`, and type-sort logic move into the Validator. The inventory-binding language added to `_STRATEGY_SYNTHESIS_SYSTEM` last iteration gets reverted.

---

## Open Questions

These are decisions worth making explicitly before implementation.

1. **Reviser model selection.** Should the Reviser use the same model as the Writer, or a cheaper one? Argument for same: matching capability avoids losing nuance. Argument for cheaper: this is mechanical work; a smaller model is sufficient and reduces cost. **Recommendation:** start with same model (simplest), add `model_hint="revision"` for future tuning.

2. **Logging unresolved ghosts.** When the Reviser drops a slug entirely (no plausible substitute in inventory), should we log it somewhere for human review? **Recommendation:** append to a `wiki/meta/synthesis-ghosts.log` file. Over time, recurring ghosts in this log signal entities worth either creating or adding to the suppress list permanently.

3. **Validator iteration ceiling.** Should we Validate → Revise → Validate again, and loop until clean (with a max)? **Recommendation:** no. Single Reviser pass. If the Reviser introduces new broken slugs, that's a Reviser bug worth surfacing, not papering over with another round.

4. **Narrative revision granularity.** Should the Reviser correct the entire narrative in one call, or one wikilink at a time? **Recommendation:** whole narrative in one call. Per-link calls multiply cost without quality benefit, and the Reviser benefits from seeing surrounding context.

5. **Failure mode if Reviser itself fails.** If the Reviser LLM call errors out, do we fall back to the original Writer output (with ghosts) or to an empty synthesis? **Recommendation:** fall back to Writer output. A synthesis with ghosts is more useful than no synthesis. Log the failure prominently.

6. **Test coverage.** The Validator is deterministic and trivially testable with fixture wikis. The Reviser is an LLM call — should we mock it (current pattern in `tests/test_synthesize_wiki.py`) or run integration tests with real API calls? **Recommendation:** mock for unit tests (cheap, fast, deterministic), keep one optional integration test gated on `ANTHROPIC_API_KEY` like `test_integration_extract_quads_from_fixture`.

---

## Out of Scope

To keep this change focused:

- **Content grounding against source documents.** The Reviser sees no source material. Wrong-attribution and made-up-facts problems require a separate grounding mechanism.
- **Automatic alias creation.** The synthesis-ghosts log is human-reviewed. We don't auto-add anything to `entity_aliases.json`.
- **Changing the inventory contract.** `gather_strategy_entities()` stays as-is. If actor inventories are sparse for some strategies (as we saw last iteration), that's a tagging-coverage problem to solve elsewhere — not in the synthesis loop.
- **Changes to the holistic_synthesizer's existing Writer → Evaluator → Editor loop.** That pattern is already working at the Pass 1 layer. This spec applies the same pattern to Phase C synthesis, not to Phase A extraction.
