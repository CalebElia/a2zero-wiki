"""Relationship-lexicon injection and schema-drift review loop.

Makes two previously-write-only HITL governance files actually load-bearing:
- meta/relationship-lexicon.md gets injected into extraction prompts instead
  of sitting unread.
- meta/schema-drift.md gets a real parse -> approve/reject -> apply loop,
  matching the write format it has always documented but never actually used.

See docs/architecture/ for design rationale (topic-candidates.md's retirement
in favor of meta/query-log.md is handled in pipeline/pass1b_synthesize.py and
pipeline/topic_synthesize.py, not here).
"""
import re
import yaml
from datetime import date
from pathlib import Path


_ENTRY_HEADER_RE = re.compile(
    r'^## (\d{4}-\d{2}-\d{2}) \| Proposed type: "(.+?)" \| Written as: "(.+?)" \| Page: "(.+?)"$',
    re.MULTILINE,
)
_TITLE_RE = re.compile(r"^Title: (.*)$", re.MULTILINE)
_RESOLUTION_RE = re.compile(
    r"Resolution:\s*\[([ xX])\]\s*Approve new type\s*\[([ xX])\]\s*Keep as fallback \+ tag \[(.*?)\]"
)
_RESOLVED_MARKER_RE = re.compile(r"^\*\*Resolved ", re.MULTILINE)


def load_relationship_lexicon(wiki_root: str) -> str:
    """Read meta/relationship-lexicon.md. Returns "" if missing."""
    path = Path(wiki_root).parent / "meta" / "relationship-lexicon.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_lexicon_block(wiki_root: str) -> str:
    """Wrap the relationship lexicon in the project's standard bracketed-context
    format for injection into extraction prompts. Returns "" if the lexicon is
    missing, so callers can concatenate it unconditionally with no dangling
    empty brackets."""
    content = load_relationship_lexicon(wiki_root)
    if not content.strip():
        return ""
    return f"\n[RELATIONSHIP LEXICON]\n{content.strip()}\n[END RELATIONSHIP LEXICON]\n"


def append_schema_drift_entry(
    proposed_type: str,
    fallback_type: str,
    slug: str,
    title: str,
    wiki_root: str,
    run_date: str,
) -> None:
    """Log a schema-drift proposal in the exact format meta/schema-drift.md's
    own header has always documented (previously the write site used a
    different, unparseable dash-bullet format — see docs/architecture note)."""
    path = Path(wiki_root).parent / "meta" / "schema-drift.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f'\n## {run_date} | Proposed type: "{proposed_type}" | Written as: "{fallback_type}" | Page: "{slug}"\n'
        f"Title: {title}\n"
        f"Resolution: [ ] Approve new type  [ ] Keep as fallback + tag [<tag>]\n"
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def parse_schema_drift_entries(drift_path: str) -> list[dict]:
    """Parse meta/schema-drift.md into entry dicts.

    Each dict: {date, proposed_type, fallback_type, slug, title, block,
    approve_checked, keep_checked, keep_tag, resolved}.
    """
    path = Path(drift_path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")

    headers = list(_ENTRY_HEADER_RE.finditer(text))
    entries: list[dict] = []
    for i, m in enumerate(headers):
        block_start = m.start()
        block_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[block_start:block_end].rstrip("\n")

        title_m = _TITLE_RE.search(block)
        res_m = _RESOLUTION_RE.search(block)

        entries.append({
            "date": m.group(1),
            "proposed_type": m.group(2),
            "fallback_type": m.group(3),
            "slug": m.group(4),
            "title": title_m.group(1).strip() if title_m else "",
            "block": block,
            "approve_checked": bool(res_m) and res_m.group(1).lower() == "x",
            "keep_checked": bool(res_m) and res_m.group(2).lower() == "x",
            "keep_tag": (
                res_m.group(3).strip()
                if res_m and res_m.group(3).strip() and res_m.group(3).strip() != "<tag>"
                else None
            ),
            "resolved": bool(_RESOLVED_MARKER_RE.search(block)),
        })
    return entries


def apply_schema_drift(wiki_root: str) -> dict:
    """Process every unresolved, checked entry in meta/schema-drift.md.

    Approve -> adds the proposed type to VALID_PAGE_TYPES (registry/valid_page_types.json)
    and strips proposed-type: from the affected page's frontmatter.
    Keep as fallback -> adds the given tag to the affected page's frontmatter.

    Either way, appends an in-place "**Resolved ...**" marker under the entry
    rather than deleting it -- schema-drift.md is explicitly append-only, unlike
    review-queue.md's clear-on-apply model.

    Returns {"approved": [proposed_type, ...], "kept": [slug, ...]}.
    """
    from pipeline._pages import add_valid_page_type

    root = Path(wiki_root)
    drift_path = root.parent / "meta" / "schema-drift.md"
    entries = parse_schema_drift_entries(str(drift_path))

    approved: list[str] = []
    kept: list[str] = []
    today = date.today().isoformat()
    text = drift_path.read_text(encoding="utf-8") if drift_path.exists() else ""

    for entry in entries:
        if entry["resolved"]:
            continue
        if entry["approve_checked"]:
            add_valid_page_type(entry["proposed_type"])
            _strip_proposed_type(root, entry["slug"])
            marker = (
                f'\n**Resolved {today}: approved — "{entry["proposed_type"]}" '
                f"added to VALID_PAGE_TYPES**\n"
            )
            text = text.replace(entry["block"], entry["block"] + marker)
            approved.append(entry["proposed_type"])
        elif entry["keep_checked"]:
            tag = entry["keep_tag"] or entry["proposed_type"]
            _add_page_tag(root, entry["slug"], tag)
            _strip_proposed_type(root, entry["slug"])
            marker = f'\n**Resolved {today}: kept as fallback, tagged "{tag}"**\n'
            text = text.replace(entry["block"], entry["block"] + marker)
            kept.append(entry["slug"])

    if approved or kept:
        drift_path.write_text(text, encoding="utf-8")

    return {"approved": approved, "kept": kept}


def _strip_proposed_type(wiki_root: Path, slug: str) -> None:
    page_path = wiki_root / f"{slug}.md"
    if not page_path.exists():
        return
    content = page_path.read_text(encoding="utf-8")
    new_content = re.sub(r"\nproposed-type: .*", "", content)
    if new_content != content:
        page_path.write_text(new_content, encoding="utf-8")


def _add_page_tag(wiki_root: Path, slug: str, tag: str) -> None:
    page_path = wiki_root / f"{slug}.md"
    if not page_path.exists():
        return
    text = page_path.read_text(encoding="utf-8")
    m = re.match(r"^(---\n)(.*?)(\n---\n)(.*)$", text, re.DOTALL)
    if not m:
        return
    fm = yaml.safe_load(m.group(2)) or {}
    tags = fm.get("tags") or []
    if tag not in tags:
        tags.append(tag)
    fm["tags"] = tags
    new_fm = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    page_path.write_text(m.group(1) + new_fm + m.group(3) + m.group(4), encoding="utf-8")


def schema_drift_findings(wiki_root: str) -> list[dict]:
    """Return one structural-lint-style finding dict per unresolved schema-drift entry."""
    drift_path = Path(wiki_root).parent / "meta" / "schema-drift.md"
    entries = parse_schema_drift_entries(str(drift_path))
    return [
        {
            "type": "SCHEMA_DRIFT_PENDING",
            "page": "meta/schema-drift.md",
            "detail": (
                f'Proposed type "{e["proposed_type"]}" for {e["slug"]} '
                f"(written as {e['fallback_type']!r}) — {e['date']}, awaiting review"
            ),
        }
        for e in entries
        if not e["resolved"]
    ]
