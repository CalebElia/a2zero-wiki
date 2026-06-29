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
