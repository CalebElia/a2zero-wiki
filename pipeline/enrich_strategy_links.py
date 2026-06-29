"""
One-time enrichment pass: inject entity wikilinks into existing strategy body text.

Usage:
  python -m pipeline.enrich_strategy_links --wiki-root wiki [--dry-run]

For each of the 7 strategy pages, the LLM receives the current body text and the
full entity slug/title catalogue, then rewrites the body inserting [[slug|Name]]
wikilinks on the first mention of each named entity.

Idempotent: already-linked text is preserved as-is.
"""
import re
import json
import argparse
from pipeline.llm import chat
from pathlib import Path

STRATEGY_SLUGS = [
    "strategy-1-renewable-grid",
    "strategy-2-electrification",
    "strategy-3-building-efficiency",
    "strategy-4-vmt-reduction",
    "strategy-5-materials-waste",
    "strategy-6-resilience",
    "strategy-7-engagement",
]

ENTITY_DIRS = [
    "actors", "initiatives", "locations", "technology",
    "funding-events", "meetings", "political-events",
]

FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)

ENRICHER_SYSTEM = """You are editing a wiki strategy page. Your ONLY job is to insert wikilinks
for named entities — you must NOT change, add, remove, or reorder any prose.

You will receive:
1. The current strategy body text
2. A catalogue of known entities: display name → [[slug]]

Rules:
- Link the FIRST mention of each entity. Subsequent mentions stay as plain text.
- Use format: [[slug|Display Name]] — keep the display name exactly as it appears in the text.
- If an entity is already wikilinked (text contains [[), leave it untouched.
- Do not invent links for entities not in the catalogue.
- Do not alter source citations like ([[sources/cap/cap-2020|cap-2020]]).
- Return ONLY the rewritten body text — no JSON, no commentary, no markdown fence."""


def _build_entity_catalogue(wiki_root: Path) -> dict[str, str]:
    """Return {display_title: slug} for all entity pages in the vault."""
    catalogue: dict[str, str] = {}
    for type_dir in ENTITY_DIRS:
        dir_path = wiki_root / type_dir
        if not dir_path.exists():
            continue
        for page in dir_path.glob("*.md"):
            text = page.read_text(encoding="utf-8", errors="replace")
            m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
            title = page.stem.replace("-", " ").title()
            if m:
                for line in m.group(1).splitlines():
                    if line.startswith("title:"):
                        title = line.split(":", 1)[1].strip().strip("'\"")
                        break
            slug = str(page.relative_to(wiki_root)).removesuffix(".md")
            catalogue[title] = slug
    return catalogue


def _enrich_body(body: str, catalogue: dict[str, str]) -> str:
    catalogue_text = "\n".join(
        f'  "{title}" → [[{slug}]]'
        for title, slug in sorted(catalogue.items())
    )
    user_msg = f"ENTITY CATALOGUE:\n{catalogue_text}\n\nSTRATEGY BODY:\n{body}"
    return chat(
        system=ENRICHER_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=8192,
        model_hint="extraction",
        temperature=0.0,
    ).strip()


def enrich_strategy_links(wiki_root: str, dry_run: bool = False) -> None:
    root = Path(wiki_root)
    catalogue = _build_entity_catalogue(root)
    print(f"[enrich] Built catalogue: {len(catalogue)} entities")

    for slug in STRATEGY_SLUGS:
        page_path = root / "strategies" / f"{slug}.md"
        if not page_path.exists():
            print(f"[enrich] SKIP (not found): {page_path}")
            continue

        raw = page_path.read_text(encoding="utf-8")
        fm_match = re.match(r"^(---\n.*?\n---\n)", raw, re.DOTALL)
        frontmatter = fm_match.group(1) if fm_match else ""
        body = FRONTMATTER_RE.sub("", raw).strip()

        print(f"[enrich] Processing {slug}...")
        enriched_body = _enrich_body(body, catalogue)

        if enriched_body == body:
            print(f"[enrich]   No changes.")
            continue

        if dry_run:
            print(f"[enrich]   DRY RUN — would rewrite {page_path}")
        else:
            page_path.write_text(frontmatter + "\n" + enriched_body + "\n", encoding="utf-8")
            print(f"[enrich]   Rewritten.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject entity wikilinks into strategy pages")
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()
    enrich_strategy_links(args.wiki_root, dry_run=args.dry_run)
