"""
One-time enrichment pass: backfill reciprocal `funding-events:` links onto
initiative pages that a funding-event page already names via `funds-initiatives:`.

Deterministic — no LLM call. The relationship already exists (the funding-event
page states it); this only makes it visible from the other direction.

Usage:
  python -m pipeline._legacy.backfill_funding_event_links --wiki-root wiki [--dry-run]
"""
import argparse
import re
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"^(---\n)(.*?)(\n---\n)(.*)$", re.DOTALL)


def _slug_from_wikilink(raw: str) -> str:
    return raw.strip().strip("[]").split("|")[0].strip()


def find_reciprocal_gaps(wiki_root: Path) -> dict[str, list[str]]:
    """Return {target_slug: [funding_event_slug, ...]} for every funding-event
    -> initiative relationship missing its reciprocal link."""
    gaps: dict[str, list[str]] = {}
    for fe_path in sorted((wiki_root / "funding-events").glob("*.md")):
        text = fe_path.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        if not m:
            continue
        fm = yaml.safe_load(m.group(2)) or {}
        fe_slug = f"funding-events/{fe_path.stem}"
        for target in fm.get("funds-initiatives") or []:
            target_slug = _slug_from_wikilink(target)
            target_path = wiki_root / f"{target_slug}.md"
            if not target_path.exists():
                continue
            target_text = target_path.read_text(encoding="utf-8")
            tm = FRONTMATTER_RE.match(target_text)
            target_fm = yaml.safe_load(tm.group(2)) or {} if tm else {}
            existing = [_slug_from_wikilink(s) for s in (target_fm.get("funding-events") or [])]
            if fe_slug not in existing:
                gaps.setdefault(target_slug, []).append(fe_slug)
    return gaps


def apply_backfill(wiki_root: Path, gaps: dict[str, list[str]], dry_run: bool) -> None:
    for target_slug, fe_slugs in sorted(gaps.items()):
        target_path = wiki_root / f"{target_slug}.md"
        text = target_path.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        if not m:
            print(f"[backfill] SKIP (no frontmatter): {target_slug}")
            continue
        fm = yaml.safe_load(m.group(2)) or {}
        existing = fm.get("funding-events") or []
        existing_slugs = {_slug_from_wikilink(s) for s in existing}
        added = [fe for fe in fe_slugs if fe not in existing_slugs]
        if not added:
            continue
        new_list = existing + [f"[[{fe}]]" for fe in added]
        fm["funding-events"] = new_list

        if dry_run:
            print(f"[backfill] DRY RUN — would add to {target_slug}: {added}")
            continue

        new_fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
        target_path.write_text(m.group(1) + new_fm_text + m.group(3) + m.group(4), encoding="utf-8")
        print(f"[backfill] {target_slug}: added {added}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill reciprocal funding-events links")
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root)
    gaps = find_reciprocal_gaps(wiki_root)
    print(f"[backfill] {sum(len(v) for v in gaps.values())} gap(s) across {len(gaps)} page(s)")
    apply_backfill(wiki_root, gaps, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
