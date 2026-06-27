# pipeline/alias_registry.py
import json
import difflib
from pathlib import Path

DEFAULT_ALIASES_PATH = "registry/entity_aliases.json"


def load_aliases(path: str = DEFAULT_ALIASES_PATH) -> dict:
    """Load entity_aliases.json. Returns {} if file missing."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_aliases(aliases: dict, path: str = DEFAULT_ALIASES_PATH) -> None:
    """Write aliases back to disk with stable formatting."""
    Path(path).write_text(
        json.dumps(aliases, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def resolve_slug(slug: str, aliases: dict) -> str | None:
    """Return canonical vault path if slug is a known alias key, else None."""
    entry = aliases.get(slug)
    if entry is not None:
        return entry["canonical"]
    return None


def resolve_slug_for_title(title: str, aliases: dict) -> str | None:
    """Return canonical vault path if title matches any alias label (case-insensitive)."""
    title_lower = title.strip().lower()
    for entry in aliases.values():
        for label in entry.get("aliases", []):
            if label.lower() == title_lower:
                return entry["canonical"]
    return None


def fuzzy_resolve_slug_for_title(title: str, aliases: dict, threshold: float = 0.82) -> str | None:
    """Return canonical vault path if title fuzzy-matches any alias label above threshold.

    Uses a higher default threshold (0.82) than semantic dedup (0.65) because false
    redirects during ingest are more harmful than missed matches — they silently
    collapse distinct entities.  Only fires when exact resolve_slug_for_title fails.
    """
    title_lower = title.strip().lower()
    best_score = 0.0
    best_canonical: str | None = None
    for entry in aliases.values():
        for label in entry.get("aliases", []):
            score = difflib.SequenceMatcher(None, title_lower, label.lower()).ratio()
            if score >= threshold and score > best_score:
                best_score = score
                best_canonical = entry["canonical"]
    return best_canonical


def fuzzy_candidates(query: str, candidates: list[str], threshold: float = 0.65) -> list[str]:
    """Return candidates whose normalized edit similarity to query exceeds threshold.

    Uses difflib.SequenceMatcher (stdlib). Stage 1 of the two-stage dedup detection.
    """
    query_lower = query.lower()
    results = []
    for candidate in candidates:
        score = difflib.SequenceMatcher(None, query_lower, candidate.lower()).ratio()
        if score >= threshold:
            results.append(candidate)
    return results


def add_alias(
    slug: str,
    canonical: str,
    entity_type: str,
    alias_labels: list[str],
    relationship: str = "name-variant",
    aliases_path: str = DEFAULT_ALIASES_PATH,
    as_of: str | None = None,
    notes: str | None = None,
) -> None:
    """Add or update an alias entry and persist to disk."""
    aliases = load_aliases(aliases_path)
    entry: dict = {
        "canonical": canonical,
        "type": entity_type,
        "aliases": alias_labels,
        "relationship": relationship,
    }
    if as_of:
        entry["as-of"] = as_of
    if notes:
        entry["notes"] = notes
    aliases[slug] = entry
    save_aliases(aliases, aliases_path)


def seed_aliases_from_ingest(
    wiki_root: str,
    source_wikilink: str,
    aliases_path: str = DEFAULT_ALIASES_PATH,
) -> int:
    """Register display titles for all entity pages first-seen in this ingest.

    Scans every entity page whose source-first-seen frontmatter matches
    source_wikilink and adds a name-variant alias entry if one doesn't already
    exist.  This ensures that on the next ingest, Pass 1.5 can fuzzy-match
    these titles and redirect to the canonical slug instead of creating duplicates.

    Returns count of new entries added.
    """
    import re
    from pathlib import Path

    _ENTITY_DIRS = [
        "actors", "initiatives", "locations", "technology",
        "funding-events", "meetings", "political-events",
    ]
    _DIR_TO_TYPE = {
        "actors": "actor", "initiatives": "initiative", "locations": "location",
        "technology": "technology", "funding-events": "funding-event",
        "meetings": "meeting", "political-events": "political-event",
    }

    aliases = load_aliases(aliases_path)
    root = Path(wiki_root)
    # Normalise: strip [[...]] wrapper if caller passed a full wikilink
    source_key = source_wikilink.strip("[]")
    added = 0

    for type_dir in _ENTITY_DIRS:
        entity_type = _DIR_TO_TYPE[type_dir]
        for page in (root / type_dir).glob("*.md"):
            raw = page.read_text(encoding="utf-8", errors="replace")
            m = re.match(r"^---\n(.*?)\n---\n", raw, re.DOTALL)
            if not m:
                continue
            first_seen = ""
            title = ""
            for line in m.group(1).splitlines():
                if line.startswith("source-first-seen:"):
                    first_seen = line.split(":", 1)[1].strip().strip("'\"[]")
                elif line.startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip("'\"")
            if source_key not in first_seen:
                continue
            slug_key = page.stem
            if slug_key in aliases or not title:
                continue
            canonical = f"{type_dir}/{slug_key}"
            aliases[slug_key] = {
                "canonical": canonical,
                "type": entity_type,
                "aliases": [title],
                "relationship": "name-variant",
            }
            added += 1

    if added:
        save_aliases(aliases, aliases_path)
    return added
