"""
On-demand post-ingest wiki linter.

Usage:
  python -m pipeline.lint_wiki --wiki-root wiki --structural
  python -m pipeline.lint_wiki --wiki-root wiki --semantic
  python -m pipeline.lint_wiki --wiki-root wiki --apply
"""
import re
import json
import argparse
from datetime import date
from pathlib import Path

# Pages exempt from orphan check — hub pages, auto-generated, or top-level containers
ORPHAN_EXEMPT_NAMES = frozenset({"index.md", "log.md", "hot.md"})
ORPHAN_EXEMPT_DIRS = frozenset({"strategies", "sources", "overviews", "topics", "meta"})

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")


def _all_md_files(wiki_root: str) -> list[Path]:
    return list(Path(wiki_root).rglob("*.md"))


def _parse_wikilinks(text: str) -> list[str]:
    """Return all wikilink targets (path portion only, no display alias)."""
    return WIKILINK_RE.findall(text)


def structural_lint(wiki_root: str) -> list[dict]:
    """Return list of finding dicts with keys: type, page, detail.

    Types: BROKEN_LINK, ORPHAN
    """
    root = Path(wiki_root)
    all_files = _all_md_files(wiki_root)
    # Build set of all vault-relative paths with .md extension
    all_slugs = {str(f.relative_to(root)) for f in all_files}

    findings = []
    inbound_links: dict[str, set[str]] = {str(f.relative_to(root)): set() for f in all_files}

    for md_file in all_files:
        rel = str(md_file.relative_to(root))
        text = md_file.read_text(encoding="utf-8", errors="replace")
        for link in _parse_wikilinks(text):
            target = link.strip()
            target_path = target if target.endswith(".md") else target + ".md"
            if target_path not in all_slugs:
                findings.append({
                    "type": "BROKEN_LINK",
                    "page": rel,
                    "detail": f"[[{link}]] → {target_path} not found",
                })
            else:
                inbound_links.setdefault(target_path, set()).add(rel)

    # Orphan check
    for md_file in all_files:
        rel = str(md_file.relative_to(root))
        if md_file.name in ORPHAN_EXEMPT_NAMES:
            continue
        if md_file.parent.name in ORPHAN_EXEMPT_DIRS:
            continue
        if not inbound_links.get(rel):
            findings.append({
                "type": "ORPHAN",
                "page": rel,
                "detail": "No other page links to this page",
            })

    return findings


def append_lint_report(wiki_root: str, findings: list[dict], mode: str) -> None:
    """Append a lint report section to review-queue.md."""
    if not findings:
        print(f"[lint_wiki:{mode}] No issues found.")
        return
    rq_path = Path(wiki_root).parent / "review-queue.md"
    today = date.today().isoformat()
    lines = [f"\n## {mode.title()} Lint — {today}\n"]
    for f in findings:
        lines.append(f"- [{f['type']}] `{f['page']}` — {f['detail']}")
    lines.append("")
    with rq_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"[lint_wiki:{mode}] {len(findings)} findings written to review-queue.md")
