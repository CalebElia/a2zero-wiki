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
    import anthropic
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
