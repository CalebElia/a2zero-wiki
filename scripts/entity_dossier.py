"""Remediation tool for STALE_ENTITY findings from `phase_b_lint --staleness`.

For a given entity + source, pulls every sentence-ish context window in the
source that mentions the entity (by title or any registered alias — the same
name index the staleness lint itself uses, so results line up with the
finding) and shows it side by side with the entity's current page body. This
is the HITL review artifact: a human reads the dossier, decides what's
actually new, and either integrates it directly or hands the dossier to an
LLM call to draft the integration.

Not part of the ongoing ingest pipeline — a standalone review tool, like
migrate_strategy_foundation.py.

Usage:
  # single entity
  python scripts/entity_dossier.py --slug initiatives/bryant-neighborhood-decarbonization --source a2zero-year5

  # every STALE_ENTITY finding in review-queue.md for a given source
  python scripts/entity_dossier.py --all-stale --source a2zero-year5

  # write to a file instead of stdout
  python scripts/entity_dossier.py --all-stale --source a2zero-year5 --output meta/dossiers/a2zero-year5-remediation.md
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.recall_scan import build_entity_name_index, build_ambiguous_scan_index

CONTEXT_CHARS = 220

_STALE_FINDING_RE = re.compile(r"\[STALE_ENTITY\] `([^`]+)\.md`")


def _find_source_path(wiki_root: Path, source_uuid: str) -> Path | None:
    matches = sorted((wiki_root / "sources").rglob(f"{source_uuid}.md"))
    return matches[0] if matches else None


def _extract_context_windows(text: str, names: list[str]) -> list[str]:
    """Merge overlapping ±CONTEXT_CHARS windows around every boundary-checked
    (case-insensitive) occurrence of any name, so repeated nearby mentions
    collapse into one readable block instead of duplicating it."""
    if not names:
        return []
    text = re.sub(r"\s+", " ", text)
    names_longest_first = sorted(set(names), key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(n) for n in names_longest_first) + r")(?!\w)",
        re.IGNORECASE,
    )
    spans = [(m.start(), m.end()) for m in pattern.finditer(text)]
    if not spans:
        return []
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        wstart, wend = max(0, start - CONTEXT_CHARS), min(len(text), end + CONTEXT_CHARS)
        if merged and wstart <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], wend))
        else:
            merged.append((wstart, wend))
    return [f"…{text[s:e].strip()}…" for s, e in merged]


def _page_title_and_body(page_path: Path) -> tuple[str, str]:
    text = page_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return page_path.stem, text
    title_m = re.search(r"^title:\s*['\"]?(.+?)['\"]?\s*$", m.group(1), re.MULTILINE)
    title = title_m.group(1) if title_m else page_path.stem
    body = re.sub(r"<!--.*?-->", "", m.group(2), flags=re.DOTALL).strip()
    return title, body or "(stub — no body yet)"


def build_entity_dossier(slug: str, source_uuid: str, wiki_root: str = "wiki") -> dict:
    """Return {slug, title, page_body, source_mentions: [...]} for one entity.

    source_mentions is empty if the entity's names don't appear in the source
    (shouldn't happen for a real STALE_ENTITY finding, but the caller should
    treat it as a signal the finding may have been alias-driven noise).
    """
    root = Path(wiki_root)
    page_path = root / f"{slug}.md"
    if not page_path.exists():
        raise FileNotFoundError(f"no such page: {slug}")
    title, body = _page_title_and_body(page_path)

    source_path = _find_source_path(root, source_uuid)
    if source_path is None:
        raise FileNotFoundError(f"source {source_uuid!r} not found under {root}/sources/")
    source_text = source_path.read_text(encoding="utf-8")

    index = build_entity_name_index(wiki_root)
    names = [name for name, s in index.items() if s == slug]
    # Ambiguous-term slugs (e.g. locations/ann-arbor, initiatives/a2zero-carbon-
    # neutrality-plan) are deliberately excluded from the plain index above —
    # scan_source_for_known_entities routes them exclusively through the
    # multi-candidate path to avoid double-counting. Without this, the dossier
    # tool would find zero names to search for these entities and wrongly
    # report "no boundary-checked match found" even when the entity is
    # genuinely, heavily mentioned in the source.
    ambiguous_index = build_ambiguous_scan_index(wiki_root)
    names += [name for name, slugs in ambiguous_index.items() if slug in slugs]
    mentions = _extract_context_windows(source_text, names)

    return {"slug": slug, "title": title, "page_body": body, "source_mentions": mentions}


def _stale_slugs_from_review_queue(review_queue_path: Path, source_uuid: str) -> list[str]:
    if not review_queue_path.exists():
        return []
    text = review_queue_path.read_text(encoding="utf-8")
    section_m = re.search(
        rf"## Staleness Lint —[^\n]*\(source: {re.escape(source_uuid)}\)\n(.*?)(?=\n## |\Z)",
        text, re.DOTALL,
    )
    if not section_m:
        return []
    return _STALE_FINDING_RE.findall(section_m.group(1))


def format_dossier_markdown(dossier: dict) -> str:
    lines = [f"## {dossier['slug']} — {dossier['title']}", "", "### Current page body", "", dossier["page_body"], ""]
    if dossier["source_mentions"]:
        lines += ["### Source mentions", ""]
        for i, mention in enumerate(dossier["source_mentions"], 1):
            lines.append(f"{i}. {mention}")
    else:
        lines.append("### Source mentions\n\n_(no boundary-checked match found — possible alias noise; verify manually)_")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Remediation dossier for STALE_ENTITY findings")
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument("--review-queue", default=None, help="Path to review-queue.md (default: <wiki-root>/../review-queue.md)")
    parser.add_argument("--source", required=True, help="Source UUID (e.g. a2zero-year5)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--slug", help="Single entity slug, e.g. initiatives/bryant-neighborhood-decarbonization")
    group.add_argument("--all-stale", action="store_true", help="Every STALE_ENTITY finding for --source in review-queue.md")
    parser.add_argument("--output", default=None, help="Write to this file instead of stdout")
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root)
    rq_path = Path(args.review_queue) if args.review_queue else wiki_root.parent / "review-queue.md"

    if args.slug:
        slugs = [args.slug]
    else:
        slugs = _stale_slugs_from_review_queue(rq_path, args.source)
        if not slugs:
            print(f"No STALE_ENTITY findings for source {args.source!r} in {rq_path}", file=sys.stderr)
            sys.exit(1)

    sections = [f"# Remediation Dossier — {args.source}", f"*{len(slugs)} entit{'y' if len(slugs) == 1 else 'ies'}*", ""]
    for slug in slugs:
        try:
            dossier = build_entity_dossier(slug, args.source, str(wiki_root))
        except FileNotFoundError as e:
            sections.append(f"## {slug}\n\n_SKIPPED: {e}_\n")
            continue
        sections.append(format_dossier_markdown(dossier))
        sections.append("---\n")

    output = "\n".join(sections)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"[dossier] wrote {len(slugs)} entit{'y' if len(slugs) == 1 else 'ies'} to {out_path}")
    else:
        print(output)


if __name__ == "__main__":
    main()
