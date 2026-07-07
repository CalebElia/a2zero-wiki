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
        if len(name) >= _MIN_NAME_LEN:
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
    for entry in aliases.values():
        canonical = entry.get("canonical", "")
        if not canonical or not (root / f"{canonical}.md").exists():
            continue
        for alias in entry.get("aliases", []):
            _add(alias, canonical)

    return index


def scan_source_for_known_entities(source_text: str, index: dict[str, str]) -> dict[str, dict]:
    """Return {slug: {"matched-names": [...], "mentions": int}} for every
    indexed name that appears (word-boundary, case-insensitive) in the source."""
    text = re.sub(r"\s+", " ", source_text)
    hits: dict[str, dict] = {}
    for name, slug in index.items():
        pattern = r"\b" + re.escape(name) + r"\b"
        count = len(re.findall(pattern, text, re.IGNORECASE))
        if count:
            entry = hits.setdefault(slug, {"matched-names": [], "mentions": 0})
            entry["matched-names"].append(name)
            entry["mentions"] += count
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
        {"slug": slug,
         "matched-names": missing[slug]["matched-names"],
         "mentions": missing[slug]["mentions"]}
        for slug in ordered
    ]
    plan["retrieve-for-context"] = list(plan.get("retrieve-for-context") or []) + ordered
    return plan
