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
