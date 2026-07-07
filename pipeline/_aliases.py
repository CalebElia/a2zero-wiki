# pipeline/alias_registry.py
import json
import re
import difflib
from pathlib import Path

DEFAULT_ALIASES_PATH = "registry/entity_aliases.json"

# Types that represent curated synthesis of lower-level entities (topic pages,
# strategy pages, overviews) rather than an entity's own identity. An entity
# extraction (actor/initiative/location/funding-event/meeting/political-event/
# technology) must never resolve through the alias registry into one of these —
# that silently absorbs the entity's identity into a rollup page instead of
# giving it its own page. Topics synthesize FROM entity pages, the same way
# strategy pages synthesize from initiatives/actors; they are never a
# substitute for an entity having its own page.
NON_ENTITY_TYPES = frozenset({"topic", "synthesis", "strategy", "overview"})

# Reserved top-level key for names that are genuinely ambiguous between two
# legitimate, different-typed entities depending on sentence intent (e.g.
# "Ann Arbor" the place vs. the municipal government acting as an actor).
# Its value is a LIST, not another slug-keyed entry — every consumer that
# iterates aliases.values()/.items() must skip it explicitly (list.get()
# raises AttributeError otherwise).
AMBIGUOUS_TERMS_KEY = "_ambiguous_terms"


def _normalize_term(text: str) -> str:
    """Collapse whitespace/hyphen variance so a bare slug ('ann-arbor') and a
    natural-language title ('Ann Arbor') compare equal."""
    return re.sub(r"[\s-]+", "-", text.strip().lower())


def _resolve_ambiguous_term(
    term: str,
    aliases: dict,
    proposed_type: str | None,
    fuzzy_threshold: float | None = None,
) -> str | None:
    """Check the reserved _ambiguous_terms list before the normal flat scan.

    Returns the candidate whose type matches proposed_type; if proposed_type
    is falsy, returns the entry's documented default; if proposed_type is
    given but matches no candidate, returns None rather than forcing a
    redirect the LLM's own type judgment contradicts — the caller's normal
    fallback chain (ultimately new-stub creation) decides instead.

    fuzzy_threshold=None (the default, used by resolve_slug/resolve_slug_for_title)
    requires an exact normalized match. fuzzy_resolve_slug_for_title passes a
    real threshold so a typo'd ambiguous term ("Ann Arbour") still resolves,
    matching that function's own typo-tolerance contract for every other entry.
    """
    entries = aliases.get(AMBIGUOUS_TERMS_KEY) or []
    norm_term = _normalize_term(term)
    for entry in entries:
        if fuzzy_threshold is None:
            matched = any(_normalize_term(a) == norm_term for a in entry.get("aliases", []))
        else:
            matched = any(
                difflib.SequenceMatcher(None, norm_term, _normalize_term(a)).ratio() >= fuzzy_threshold
                for a in entry.get("aliases", [])
            )
        if not matched:
            continue
        if proposed_type:
            for cand in entry.get("candidates", []):
                if cand.get("type") == proposed_type:
                    return cand.get("canonical")
            return None
        return entry.get("default")
    return None


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


def _blocked_as_non_entity_redirect(entry: dict, proposed_type: str | None) -> bool:
    """True if resolving to this alias entry would redirect a real entity
    extraction into a topic/synthesis/strategy/overview page — never allowed.
    proposed_type=None (caller didn't pass one) skips the check entirely, so
    existing callers that don't yet pass a type keep their old behavior."""
    if proposed_type is None or proposed_type in NON_ENTITY_TYPES:
        return False
    return entry.get("type") in NON_ENTITY_TYPES


def resolve_slug(slug: str, aliases: dict, proposed_type: str | None = None) -> str | None:
    """Return canonical vault path if slug is a known alias key, else None."""
    hit = _resolve_ambiguous_term(slug, aliases, proposed_type)
    if hit is not None:
        return hit
    entry = aliases.get(slug)
    if entry is not None and not _blocked_as_non_entity_redirect(entry, proposed_type):
        return entry["canonical"]
    return None


def resolve_slug_for_title(title: str, aliases: dict, proposed_type: str | None = None) -> str | None:
    """Return canonical vault path if title matches any alias label (case-insensitive)."""
    hit = _resolve_ambiguous_term(title, aliases, proposed_type)
    if hit is not None:
        return hit
    title_lower = title.strip().lower()
    for key, entry in aliases.items():
        if key == AMBIGUOUS_TERMS_KEY:
            continue
        if _blocked_as_non_entity_redirect(entry, proposed_type):
            continue
        for label in entry.get("aliases", []):
            if label.lower() == title_lower:
                return entry["canonical"]
    return None


def fuzzy_resolve_slug_for_title(
    title: str, aliases: dict, threshold: float = 0.82, proposed_type: str | None = None
) -> str | None:
    """Return canonical vault path if title fuzzy-matches any alias label above threshold.

    Uses a higher default threshold (0.82) than semantic dedup (0.65) because false
    redirects during ingest are more harmful than missed matches — they silently
    collapse distinct entities.  Only fires when exact resolve_slug_for_title fails.
    """
    hit = _resolve_ambiguous_term(title, aliases, proposed_type, fuzzy_threshold=threshold)
    if hit is not None:
        return hit
    title_lower = title.strip().lower()
    best_score = 0.0
    best_canonical: str | None = None
    for key, entry in aliases.items():
        if key == AMBIGUOUS_TERMS_KEY:
            continue
        if _blocked_as_non_entity_redirect(entry, proposed_type):
            continue
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
    if slug == AMBIGUOUS_TERMS_KEY:
        raise ValueError(
            f"{AMBIGUOUS_TERMS_KEY!r} is reserved for ambiguous-term entries; "
            "edit registry/entity_aliases.json directly, not via add_alias()."
        )
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


def build_ambiguous_terms_block(aliases_path: str = DEFAULT_ALIASES_PATH) -> str:
    """Render _ambiguous_terms as a bracketed prompt block so extraction/
    synthesis prompts see the SAME registry-driven ambiguity list the
    resolution layer uses — one source of truth, not a hardcoded prompt list.
    Returns "" if there are no ambiguous-term entries (no-op, matches
    build_lexicon_block's missing-file behavior)."""
    aliases = load_aliases(aliases_path)
    entries = aliases.get(AMBIGUOUS_TERMS_KEY) or []
    if not entries:
        return ""
    lines = ["\n\n[AMBIGUOUS NAMES — choose type by the sentence's real subject]"]
    for entry in entries:
        names = "/".join(entry.get("aliases", [])[:3])
        options = "; ".join(
            f'{c["type"]} -> {c["canonical"]}' for c in entry.get("candidates", [])
        )
        lines.append(f"- {names}: {options} (default if genuinely unclear: {entry.get('default')})")
    lines.append("[END AMBIGUOUS NAMES]")
    return "\n".join(lines)
