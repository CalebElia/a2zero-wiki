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
import anthropic
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


SEMANTIC_VERDICT_SYSTEM = """You are comparing two wiki page entries to determine if they refer to the same real-world entity.

Return ONLY valid JSON with this exact structure:
{"relationship": "same|successor|distinct", "confidence": 0.0, "reasoning": "one sentence"}

Definitions:
- "same": both entries describe the same entity with different names (merge appropriate)
- "successor": entry A is a historical predecessor of entity B (keep both, add temporal link)
- "distinct": different real-world entities that happen to have similar names (do nothing)
"""


def _get_page_title_and_excerpt(md_path: Path) -> tuple[str, str]:
    """Return (title, first 300 chars of body) from a wiki page."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    title = md_path.stem.replace("-", " ").title()  # fallback
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip("'\"")
                break
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL).strip()
    excerpt = body[:300]
    return title, excerpt


def semantic_lint(wiki_root: str, confidence_threshold: float = 0.75) -> list[dict]:
    """Stage 1 fuzzy + Stage 2 LLM near-duplicate detection.

    Returns list of proposal dicts with keys:
      type, page_a, page_b, confidence, reasoning
    """
    from pipeline.alias_registry import fuzzy_candidates

    root = Path(wiki_root)
    proposals = []
    client = anthropic.Anthropic()

    for type_dir in ["actors", "initiatives", "locations", "political-events"]:
        dir_path = root / type_dir
        if not dir_path.exists():
            continue
        pages = list(dir_path.glob("*.md"))
        if len(pages) < 2:
            continue

        title_map: dict[str, Path] = {}
        for page in pages:
            title, _ = _get_page_title_and_excerpt(page)
            title_map[title] = page

        titles = list(title_map.keys())
        seen_pairs: set[frozenset] = set()

        for i, title_a in enumerate(titles):
            candidates = fuzzy_candidates(title_a, titles[i + 1:], threshold=0.65)
            for title_b in candidates:
                pair = frozenset({title_a, title_b})
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                path_a = title_map[title_a]
                path_b = title_map[title_b]
                _, excerpt_a = _get_page_title_and_excerpt(path_a)
                _, excerpt_b = _get_page_title_and_excerpt(path_b)

                prompt = (
                    f"Entry A: {title_a}\n{excerpt_a}\n\n"
                    f"Entry B: {title_b}\n{excerpt_b}"
                )
                try:
                    response = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=256,
                        temperature=0,
                        system=SEMANTIC_VERDICT_SYSTEM,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    verdict = json.loads(response.content[0].text)
                except Exception as e:
                    print(f"[lint_wiki:semantic] WARNING: verdict failed for {title_a!r} vs {title_b!r}: {e}")
                    continue

                rel = verdict.get("relationship", "distinct")
                conf = float(verdict.get("confidence", 0))
                if rel == "distinct" or conf < confidence_threshold:
                    continue

                proposal_type = "MERGE_PROPOSED" if rel == "same" else "TEMPORAL_SUCCESSION_PROPOSED"
                proposals.append({
                    "type": proposal_type,
                    "page_a": str(path_a.relative_to(root)),
                    "page_b": str(path_b.relative_to(root)),
                    "confidence": conf,
                    "reasoning": verdict.get("reasoning", ""),
                })

    return proposals


def append_semantic_proposals(wiki_root: str, proposals: list[dict]) -> None:
    """Append semantic lint proposals to review-queue.md."""
    if not proposals:
        print("[lint_wiki:semantic] No near-duplicate proposals.")
        return
    rq_path = Path(wiki_root).parent / "review-queue.md"
    today = date.today().isoformat()
    lines = [f"\n## Semantic Lint — {today}\n"]
    for p in proposals:
        lines.append(f"### [{p['type']}] {p['page_a']} + {p['page_b']}")
        lines.append(f"- Confidence: {p['confidence']:.2f}")
        lines.append(f"- Reasoning: {p['reasoning']}")
        lines.append("- Action: [ ] APPROVE_MERGE  [ ] APPROVE_TEMPORAL_SUCCESSION  [ ] KEEP_SEPARATE  [ ] DEFER")
        lines.append("- Notes: _Add any notes before approving_\n")
    with rq_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"[lint_wiki:semantic] {len(proposals)} proposals written to review-queue.md")


APPROVED_MERGE_RE = re.compile(r"\[x\] APPROVE_MERGE", re.IGNORECASE)
APPROVED_SUCCESSION_RE = re.compile(r"\[x\] APPROVE_TEMPORAL_SUCCESSION", re.IGNORECASE)
PROPOSAL_HEADER_RE = re.compile(
    r"### \[(MERGE_PROPOSED|TEMPORAL_SUCCESSION_PROPOSED)\] (.+?) \+ (.+)"
)


def _replace_wiki_page_body(page_path: str, new_body: str) -> None:
    """Replace the body section of a wiki page, preserving frontmatter intact."""
    content = Path(page_path).read_text(encoding="utf-8")
    m = re.match(r"^(---\n.*?\n---\n)", content, re.DOTALL)
    frontmatter = m.group(1) if m else ""
    Path(page_path).write_text(frontmatter + "\n" + new_body.strip() + "\n", encoding="utf-8")


def _parse_approved_proposals(review_queue_path: str) -> list[dict]:
    """Parse review-queue.md for checked (approved) proposals."""
    text = Path(review_queue_path).read_text(encoding="utf-8", errors="replace")
    proposals = []
    current = None
    for line in text.splitlines():
        m = PROPOSAL_HEADER_RE.match(line.strip())
        if m:
            current = {
                "type": m.group(1),
                "page_a": m.group(2).strip(),
                "page_b": m.group(3).strip(),
            }
        elif current and APPROVED_MERGE_RE.search(line):
            proposals.append({**current, "approved_action": "MERGE"})
            current = None
        elif current and APPROVED_SUCCESSION_RE.search(line):
            proposals.append({**current, "approved_action": "TEMPORAL_SUCCESSION"})
            current = None
    return proposals


def _rewrite_inbound_links(wiki_root: str, old_slug: str, new_slug: str) -> int:
    """Rewrite all [[old_slug]] wikilinks to [[new_slug]] across the vault. Returns count."""
    old_bare = old_slug.removesuffix(".md")
    new_bare = new_slug.removesuffix(".md")
    pattern = re.compile(r"\[\[" + re.escape(old_bare) + r"(\|[^\]]+)?\]\]")
    count = 0
    for md_file in Path(wiki_root).rglob("*.md"):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        def _replace(m):
            alias_part = m.group(1) or ""
            return f"[[{new_bare}{alias_part}]]"
        new_text, n = pattern.subn(_replace, text)
        if n > 0:
            md_file.write_text(new_text, encoding="utf-8")
            count += n
    return count


def _append_merge_log(merge_log_path: str, entry: dict) -> None:
    """Append one JSON entry to registry/merge-log.jsonl."""
    with open(merge_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def apply_proposals(wiki_root: str, aliases_path: str, merge_log_path: str) -> None:
    """Execute approved proposals from review-queue.md."""
    from pipeline.merge_pages import merge_pages as _merge_pages
    from pipeline.alias_registry import add_alias

    rq_path = str(Path(wiki_root).parent / "review-queue.md")
    if not Path(rq_path).exists():
        print("[lint_wiki:apply] No review-queue.md found.")
        return

    proposals = _parse_approved_proposals(rq_path)
    if not proposals:
        print("[lint_wiki:apply] No approved proposals found.")
        return

    today = date.today().isoformat()
    root = Path(wiki_root)

    for p in proposals:
        page_a_rel = p["page_a"]
        page_b_rel = p["page_b"]
        path_a = root / page_a_rel
        path_b = root / page_b_rel

        if p["approved_action"] == "MERGE":
            if not path_a.exists() or not path_b.exists():
                print(f"[lint_wiki:apply] WARNING: page not found for merge: {page_a_rel} + {page_b_rel}")
                continue

            body_a = re.sub(r"^---\n.*?\n---\n", "", path_a.read_text(encoding="utf-8"), flags=re.DOTALL).strip()
            body_b = re.sub(r"^---\n.*?\n---\n", "", path_b.read_text(encoding="utf-8"), flags=re.DOTALL).strip()
            merged = _merge_pages(
                canonical_slug=page_a_rel.removesuffix(".md"),
                existing_body=body_a,
                new_body=body_b,
                source_uuid="lint-merge",
            )
            _replace_wiki_page_body(str(path_a), merged)
            path_b.unlink()

            n = _rewrite_inbound_links(wiki_root, page_b_rel, page_a_rel)
            print(f"[lint_wiki:apply] MERGE: {page_b_rel} → {page_a_rel} ({n} links rewritten)")

            slug_b = page_b_rel.removesuffix(".md").split("/")[-1]
            canonical_full = page_a_rel.removesuffix(".md")
            entity_type = page_a_rel.split("/")[0].rstrip("s")
            add_alias(
                slug=slug_b,
                canonical=canonical_full,
                entity_type=entity_type,
                alias_labels=[path_b.stem.replace("-", " ").title()],
                relationship="name-variant",
                aliases_path=aliases_path,
            )
            _append_merge_log(merge_log_path, {
                "date": today,
                "action": "MERGE",
                "from": page_b_rel,
                "into": page_a_rel,
                "approved-by": "manual",
            })

        elif p["approved_action"] == "TEMPORAL_SUCCESSION":
            if not path_b.exists():
                print(f"[lint_wiki:apply] WARNING: predecessor page not found: {page_b_rel}")
                continue

            content = path_b.read_text(encoding="utf-8")
            m = re.match(r"^(---\n)(.*?)(\n---\n)(.*)", content, re.DOTALL)
            if m:
                fm_text = m.group(2)
                canonical_link = page_a_rel.removesuffix(".md")
                fm_text += f"\nsuperseded-by: '[[{canonical_link}]]'"
                fm_text += f"\nsuperseded-date: '{today}'"
                path_b.write_text(m.group(1) + fm_text + m.group(3) + m.group(4), encoding="utf-8")

            slug_b = page_b_rel.removesuffix(".md").split("/")[-1]
            entity_type = page_a_rel.split("/")[0].rstrip("s")
            add_alias(
                slug=slug_b,
                canonical=page_a_rel.removesuffix(".md"),
                entity_type=entity_type,
                alias_labels=[path_b.stem.replace("-", " ").title()],
                relationship="predecessor",
                aliases_path=aliases_path,
                as_of=today,
            )
            _append_merge_log(merge_log_path, {
                "date": today,
                "action": "TEMPORAL_SUCCESSION",
                "predecessor": page_b_rel,
                "successor": page_a_rel,
                "approved-by": "manual",
            })
            print(f"[lint_wiki:apply] TEMPORAL_SUCCESSION: {page_b_rel} → {page_a_rel}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A2Zero wiki linter")
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument("--structural", action="store_true")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--aliases-path", default="registry/entity_aliases.json")
    parser.add_argument("--merge-log", default="registry/merge-log.jsonl")
    args = parser.parse_args()

    if args.structural:
        findings = structural_lint(args.wiki_root)
        append_lint_report(args.wiki_root, findings, "structural")

    if args.semantic:
        proposals = semantic_lint(args.wiki_root)
        append_semantic_proposals(args.wiki_root, proposals)

    if args.apply:
        apply_proposals(args.wiki_root, args.aliases_path, args.merge_log)

    if not any([args.structural, args.semantic, args.apply]):
        print("Specify at least one mode: --structural, --semantic, --apply")
