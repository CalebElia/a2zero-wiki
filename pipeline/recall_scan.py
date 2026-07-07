"""Deterministic recall floor for the ingest pipeline.

Comprehension is LLM work; recall is mechanical. This module string-scans an
incoming source against every known entity name (page titles + registry
aliases + computed verb-prefix variants) so the integration plan is guaranteed
to surface every existing entity the source names — independent of the
digest's lossy top-N compression and the Comprehend pass's judgment.

See docs/architecture/deterministic-recall-floor.md.
"""
import json
import re
from pathlib import Path

ENTITY_DIRS = [
    "actors", "initiatives", "locations", "technology",
    "funding-events", "meetings", "political-events",
]

# CAP-2020 action items carry a leading verb that later annual reports drop.
_VERB_PREFIXES = (
    "Support ", "Expand ", "Launch ", "Promote ", "Enhance ",
    "Implement ", "Develop ", "Increase ", "Advance ", "Establish ",
    "Transition ", "Improve ", "Foster ", "Invest In ", "Preserve ",
)

_MIN_NAME_LEN = 4

_TITLE_RE = re.compile(r"^title:\s*['\"]?(.+?)['\"]?\s*$", re.MULTILINE)

# Scan-only exclusions: names too generic for mechanical string matching to be
# useful, even though they're legitimate for Pass 1.5's ingest-time entity
# resolution (registry/entity_aliases.json — untouched, loaded separately by
# pipeline/_aliases.py). "the City" alone (unqualified by "of Ann Arbor") is
# too generic for any single candidate; scanning for it produces saturating
# false-positive noise (confirmed empirically: 107 mentions for
# actors/city-of-ann-arbor in the Year 5 source alone) with near-zero recall
# value. Filed as review-queue Task #128, 2026-07-06.
#
# "A2Zero"/"A2Zero Program"/"A2Zero Office"/"A2Zero" (accented) were removed
# from this stoplist: they're one of the registry's _ambiguous_terms
# families (plan/initiative vs. actor) and are now surfaced via
# build_ambiguous_scan_index + scan_source_for_known_entities's
# ambiguous_index parameter, which flags every legitimate candidate instead
# of staying silently blind to the source's most common way of naming them.
_SCAN_STOPLIST = frozenset({
    "the city",
})


def build_entity_name_index(wiki_root: str, aliases_path: str | None = None) -> dict[str, str]:
    """Return {lowercased name: canonical slug} for every entity page.

    Sources, in override order (later wins on collision — aliases are curated,
    titles are generated, so registry aliases take precedence):
      1. computed verb-prefix variants of page titles
      2. page titles
      3. registry aliases (mapped to their canonical slug)
    """
    root = Path(wiki_root)
    if aliases_path is None:
        aliases_path = str(root.parent / "registry" / "entity_aliases.json")

    index: dict[str, str] = {}

    def _add(name: str, slug: str) -> None:
        name = name.strip()
        if len(name) >= _MIN_NAME_LEN and name.lower() not in _SCAN_STOPLIST:
            index[name.lower()] = slug

    for type_dir in ENTITY_DIRS:
        dir_path = root / type_dir
        if not dir_path.exists():
            continue
        for page in sorted(dir_path.glob("*.md")):
            slug = f"{type_dir}/{page.stem}"
            try:
                text = page.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
            title = None
            if m:
                tm = _TITLE_RE.search(m.group(1))
                if tm:
                    title = tm.group(1)
            if not title:
                title = page.stem.replace("-", " ").title()
            for prefix in _VERB_PREFIXES:
                if title.startswith(prefix):
                    _add(title[len(prefix):], slug)
            _add(title, slug)

    try:
        aliases = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        aliases = {}
    for key, entry in aliases.items():
        if key == "_ambiguous_terms":
            continue  # reserved key, value is a list — handled separately by build_ambiguous_scan_index
        canonical = entry.get("canonical", "")
        if not canonical or not (root / f"{canonical}.md").exists():
            continue
        for alias in entry.get("aliases", []):
            _add(alias, canonical)

    return index


def build_ambiguous_scan_index(wiki_root: str, aliases_path: str | None = None) -> dict[str, list[str]]:
    """Return {lowercased name: [candidate slugs]} for every registry
    _ambiguous_terms entry whose candidate pages actually exist on disk
    (same on-disk-existence filtering convention as build_entity_name_index's
    alias step).

    The mechanical scanner has no LLM and cannot judge sentence intent, so for
    these name families it flags every legitimate candidate rather than
    guessing (or, as before this existed, staying silently blind to them).
    An entry contributes no entries here unless at least 2 of its candidates'
    pages exist — with fewer than 2 there's nothing ambiguous to flag.
    """
    root = Path(wiki_root)
    if aliases_path is None:
        aliases_path = str(root.parent / "registry" / "entity_aliases.json")
    try:
        aliases = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        aliases = {}

    index: dict[str, list[str]] = {}
    for entry in aliases.get("_ambiguous_terms") or []:
        slugs = [
            cand["canonical"] for cand in entry.get("candidates", [])
            if cand.get("canonical") and (root / f"{cand['canonical']}.md").exists()
        ]
        if len(slugs) < 2:
            continue
        for name in entry.get("aliases", []):
            name = name.strip()
            if len(name) >= _MIN_NAME_LEN:
                index[name.lower()] = slugs
    return index


def scan_source_for_known_entities(
    source_text: str,
    index: dict[str, str],
    ambiguous_index: dict[str, list[str]] | None = None,
) -> dict[str, dict]:
    """Return {slug: {"matched-names": [...], "mentions": int}} for every
    indexed name that appears (boundary-checked, case-insensitive) in the source.

    Boundaries use lookarounds, not \\b: ~6% of real indexed names end in a
    non-word char (parenthetical acronyms like "... (MDOT)"), and a trailing
    \\b after ")" requires the NEXT char to be a word char — inverting the
    intent and silently never matching those names in normal prose. (?<!\\w)
    and (?!\\w) express the actual requirement: the name is not embedded
    inside a longer word.

    Single-pass alternation (longest name first) instead of one findall per
    name: a per-name loop measured ~2s against the largest real source and
    scales O(names x text). Overlapping names count each text occurrence once
    for the longest matching name; mentions only drive priority ordering.

    ambiguous_index (optional, from build_ambiguous_scan_index) is scanned in
    a second boundary-safe pass. A match adds a hit entry for EVERY candidate
    slug, tagged "ambiguous": True / "ambiguous-with": [sibling slugs] — the
    scanner has no LLM to pick one, so it flags them all rather than guessing.
    None (the default) is zero behavior change for existing callers.
    """
    if not index and not ambiguous_index:
        return {}
    text = re.sub(r"\s+", " ", source_text)
    hits: dict[str, dict] = {}

    def _pattern_for(names: list[str]) -> re.Pattern:
        return re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(n) for n in names) + r")(?!\w)",
            re.IGNORECASE,
        )

    # Names also present in ambiguous_index route exclusively through the
    # ambiguous pass below — a term flagged as genuinely ambiguous (e.g. a
    # location page whose own title collides with an _ambiguous_terms alias)
    # must not also get a silent, confident single-slug match here, which
    # would double-count mentions and contradict the "flag both, don't guess"
    # principle for exactly the terms that principle exists to cover.
    active_index = (
        {n: s for n, s in index.items() if n not in ambiguous_index}
        if ambiguous_index else index
    )
    if active_index:
        names_longest_first = sorted(active_index, key=len, reverse=True)
        for m in _pattern_for(names_longest_first).finditer(text):
            name = m.group(0).lower()
            slug = active_index.get(name)
            if slug is None:
                continue
            entry = hits.setdefault(slug, {"matched-names": [], "mentions": 0})
            if name not in entry["matched-names"]:
                entry["matched-names"].append(name)
            entry["mentions"] += 1

    if ambiguous_index:
        names_longest_first = sorted(ambiguous_index, key=len, reverse=True)
        for m in _pattern_for(names_longest_first).finditer(text):
            name = m.group(0).lower()
            slugs = ambiguous_index.get(name)
            if not slugs:
                continue
            for slug in slugs:
                entry = hits.setdefault(slug, {"matched-names": [], "mentions": 0})
                if name not in entry["matched-names"]:
                    entry["matched-names"].append(name)
                entry["mentions"] += 1
                entry["ambiguous"] = True
                entry["ambiguous-with"] = [s for s in slugs if s != slug]

    return hits


def augment_integration_plan(plan: dict, scan_hits: dict[str, dict]) -> dict:
    """Fold deterministic scan hits into a Comprehend integration plan.

    Adds a `scan-flagged` list (provenance: mechanical, not LLM judgment) and
    appends missing slugs to `retrieve-for-context` ordered by mention count.
    Slugs the LLM already covered (extends / new-entities / retrieve list) are
    left alone — the scan is a recall floor, not an override.

    Awareness vs. bodies: scan-flagged entries ride the plan JSON into every
    chunk prompt UNCAPPED, so no matched entity is ever invisible to Pass 2.
    Only full page bodies are subject to RETRIEVE_TOKEN_BUDGET (raised to 60k
    tokens in Task 3); LLM-flagged entities keep first claim on that budget,
    scan-added bodies drop first, and drops are recorded loudly in
    `context-dropped` (Task 3) rather than silently.
    """
    known = {e.get("slug", "") for e in plan.get("extends") or []}
    known |= {e.get("slug", "") for e in plan.get("new-entities") or []}
    known |= set(plan.get("retrieve-for-context") or [])

    missing = {slug: hit for slug, hit in scan_hits.items() if slug not in known}
    ordered = sorted(missing, key=lambda s: (-missing[s]["mentions"], s))

    plan = dict(plan)
    plan["scan-flagged"] = [
        {
            "slug": slug,
            "matched-names": missing[slug]["matched-names"],
            "mentions": missing[slug]["mentions"],
            **(
                {"ambiguous": True, "ambiguous-with": missing[slug]["ambiguous-with"]}
                if missing[slug].get("ambiguous") else {}
            ),
        }
        for slug in ordered
    ]
    plan["retrieve-for-context"] = list(plan.get("retrieve-for-context") or []) + ordered
    return plan
