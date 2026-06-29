"""Validator + Reviser for synthesize_wiki outputs.

Catches ghost entity references (wikilinks to non-existent pages) before they
get persisted to strategy synthesis frontmatter or digest.md.

See docs/architecture/synthesis-validation-loop.md for design rationale.
"""
from dataclasses import dataclass, field


@dataclass
class BrokenRef:
    """A single broken entity reference found by the Validator."""
    slug: str       # e.g. "actors/foo" — the unresolvable slug
    location: str   # "core-actors" | "core-initiatives" | "cross-strategy-links" | "narrative"
    display: str    # display name as it appeared in source
    context: str    # surrounding 80 chars (narrative only; empty for structured)


@dataclass
class ValidationReport:
    """Report from a single validation pass."""
    broken: list[BrokenRef] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return len(self.broken) == 0


from pathlib import Path


SUPPRESS_SLUGS: frozenset[str] = frozenset({
    "actors/systems-planning-unit",
    "actors/city-of-ann-arbor-systems-planning",
    "actors/ann-arbor-recycling-and-solid-waste",
    "actors/neighborhood-organizations",
})


def _exists(slug: str, wiki_root: str) -> bool:
    return (Path(wiki_root) / f"{slug}.md").exists()


def _resolve_alias(slug: str, aliases: dict) -> str:
    """Substitute alias -> canonical, if known."""
    key = slug.split("/")[-1]
    return aliases.get(key, {}).get("canonical") or slug


def validate_synthesis(
    synthesis: dict,
    wiki_root: str,
    aliases: dict,
) -> tuple[dict, ValidationReport]:
    """Apply alias resolution + type-sort + suppress list, then check
    every remaining slug against the filesystem.

    Returns (partially-corrected synthesis, report of what's still broken).
    """
    corrected = dict(synthesis)

    def _clean(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for slug in items or []:
            resolved = _resolve_alias(slug, aliases)
            if resolved in SUPPRESS_SLUGS or resolved in seen:
                continue
            seen.add(resolved)
            out.append(resolved)
        return out

    for field in ("core-initiatives", "core-actors", "cross-strategy-links"):
        corrected[field] = _clean(corrected.get(field) or [])

    # Type-sort: initiatives misplaced in core-actors → move to core-initiatives;
    # locations in core-actors → drop.
    misplaced_inits = [s for s in corrected["core-actors"] if s.startswith("initiatives/")]
    bad_actors = {s for s in corrected["core-actors"]
                  if s.startswith("initiatives/") or s.startswith("locations/")}
    if bad_actors:
        corrected["core-actors"] = [s for s in corrected["core-actors"] if s not in bad_actors]
        existing = set(corrected["core-initiatives"])
        corrected["core-initiatives"] = corrected["core-initiatives"] + [
            s for s in misplaced_inits if s not in existing
        ]

    # Filesystem check on what's left
    broken: list[BrokenRef] = []
    for field in ("core-initiatives", "core-actors", "cross-strategy-links"):
        for slug in corrected[field]:
            if not _exists(slug, wiki_root):
                broken.append(BrokenRef(
                    slug=slug, location=field, display=slug.split("/")[-1], context=""
                ))

    return corrected, ValidationReport(broken=broken)


import re


# Matches [[path/slug|Display]] or [[path/slug]] — captures slug and optional display
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def validate_narrative(
    narrative: str,
    wiki_root: str,
    aliases: dict,
) -> ValidationReport:
    """Parse wikilinks in narrative prose; report broken ones.

    Does not modify the narrative — narratives are revised in-place by the Reviser.
    """
    broken: list[BrokenRef] = []
    seen: set[str] = set()

    for match in _WIKILINK_RE.finditer(narrative):
        slug = match.group(1).strip()
        display = (match.group(2) or slug.split("/")[-1]).strip()

        # Skip non-entity wikilinks (e.g. sources/, strategies/)
        type_prefix = slug.split("/")[0]
        if type_prefix not in {"actors", "initiatives", "locations", "technology",
                               "funding-events", "meetings", "political-events"}:
            continue

        resolved = _resolve_alias(slug, aliases)
        if resolved in seen or resolved in SUPPRESS_SLUGS:
            continue
        seen.add(resolved)

        if not _exists(resolved, wiki_root):
            # Pull ±40 chars around the wikilink as context
            start = max(0, match.start() - 40)
            end = min(len(narrative), match.end() + 40)
            broken.append(BrokenRef(
                slug=resolved, location="narrative", display=display,
                context=narrative[start:end],
            ))

    return ValidationReport(broken=broken)


def log_dropped_ghosts(
    log_path: str,
    run_date: str,
    context_label: str,
    ghosts: list[BrokenRef],
) -> None:
    """Append dropped-ghost entries to the synthesis-ghosts log for human review.

    Recurring entries in this log signal entities worth either creating as pages
    or adding to SUPPRESS_SLUGS permanently.
    """
    if not ghosts:
        return
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"\n## [{run_date} | {context_label}]"]
    for g in ghosts:
        lines.append(f"- {g.slug} (location={g.location}, display={g.display!r})")
        if g.context:
            lines.append(f"  context: …{g.context.strip()}…")
    with p.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
