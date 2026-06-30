"""
On-demand post-ingest wiki linter.

Usage:
  python -m pipeline.phase_b_lint --wiki-root wiki --structural
  python -m pipeline.phase_b_lint --wiki-root wiki --semantic
  python -m pipeline.phase_b_lint --wiki-root wiki --backlink [--scope strategies overviews]
  python -m pipeline.phase_b_lint --wiki-root wiki --apply
"""
import re
import json
import argparse
from datetime import date
from pathlib import Path
from pipeline._llm import chat

# Pages exempt from orphan and empty-page checks — hub pages, auto-generated, or top-level containers
ORPHAN_EXEMPT_NAMES = frozenset({"index.md", "log.md", "hot.md"})
ORPHAN_EXEMPT_DIRS = frozenset({"strategies", "sources", "overviews", "topics", "meta"})

FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n?", re.DOTALL)

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")

# Matches the start of any proposal block header — used as a block-boundary detector.
# Specialised header regexes below handle per-type parsing.
PROPOSAL_HEADER_RE = re.compile(
    r"### \[(MERGE_PROPOSED|TEMPORAL_SUCCESSION_PROPOSED|LINK_PROPOSED)\] (.+)"
)

# Per-type proposal header parsers
_MERGE_HEADER_RE = re.compile(
    r"### \[(MERGE_PROPOSED|TEMPORAL_SUCCESSION_PROPOSED)\] (.+?) \+ (.+)"
)
_LINK_HEADER_RE = re.compile(
    r"### \[LINK_PROPOSED\] (.+?) ← (.+)"
)
_DISPLAY_TEXT_RE = re.compile(r'^- Display text: "(.+)"')

# Patterns for approved/resolved actions
_RESOLVED_RE = re.compile(
    r"\[x\]\s+(?:APPROVE_MERGE|APPROVE_TEMPORAL_SUCCESSION|KEEP_SEPARATE|APPROVE_LINK|KEEP_UNLINKED)",
    re.IGNORECASE,
)
_DEFER_RE = re.compile(r"\[x\]\s+DEFER", re.IGNORECASE)

# Section header patterns — each lint run owns exactly one slot in the file
_STRUCTURAL_SECTION_RE = re.compile(
    r"\n## Structural Lint —[^\n]*\n.*?(?=\n## |\Z)", re.DOTALL
)
_SEMANTIC_SECTION_RE = re.compile(
    r"\n## Semantic Lint —[^\n]*\n.*?(?=\n## |\Z)", re.DOTALL
)
_BACKLINK_SECTION_RE = re.compile(
    r"\n## Backlink Lint —[^\n]*\n.*?(?=\n## |\Z)", re.DOTALL
)

# Directories scanned for entity catalogue (all typed entity pages)
_ENTITY_DIRS = frozenset({
    "actors", "initiatives", "locations", "technology",
    "funding-events", "meetings", "political-events",
})

# Default scope for backlink scan — navigation layer first
_BACKLINK_DEFAULT_SCOPE = ["strategies", "overviews"]

# Expected type value for each directory — used for type/directory mismatch detection
_EXPECTED_TYPE_BY_DIR = {
    "strategies": "strategy",
    "actors": "actor",
    "initiatives": "initiative",
    "locations": "location",
    "technology": "technology",
    "funding-events": "funding-event",
    "meetings": "meeting",
    "political-events": "political-event",
    "overviews": "overview",
    "topics": "topic",
}
# Reverse map: type value → canonical directory
_CANONICAL_DIR_BY_TYPE = {v: k for k, v in _EXPECTED_TYPE_BY_DIR.items()}


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

    # Type/directory mismatch check — catches misrouted pages (e.g. type:initiative in topics/)
    for md_file in all_files:
        dir_name = md_file.parent.name
        expected_type = _EXPECTED_TYPE_BY_DIR.get(dir_name)
        if expected_type is None:
            continue
        rel = str(md_file.relative_to(root))
        raw = md_file.read_text(encoding="utf-8", errors="replace")
        m = re.match(r"^---\n(.*?)\n---\n", raw, re.DOTALL)
        if not m:
            continue
        page_type = None
        for line in m.group(1).splitlines():
            if line.startswith("type:"):
                page_type = line.split(":", 1)[1].strip().strip("'\"")
                break
        if page_type and page_type != expected_type:
            canonical_dir = _CANONICAL_DIR_BY_TYPE.get(page_type, f"{page_type}s")
            findings.append({
                "type": "TYPE_MISMATCH",
                "page": rel,
                "detail": (
                    f"type: {page_type!r} but lives in {dir_name!r} "
                    f"(should be in {canonical_dir!r})"
                ),
            })

    # Empty / stub-only page check
    for md_file in all_files:
        rel = str(md_file.relative_to(root))
        if md_file.name in ORPHAN_EXEMPT_NAMES:
            continue
        if md_file.parent.name in ORPHAN_EXEMPT_DIRS:
            continue
        raw = md_file.read_text(encoding="utf-8", errors="replace")
        if not raw.strip():
            findings.append({
                "type": "EMPTY_PAGE",
                "page": rel,
                "detail": "File is empty (0 bytes or whitespace only)",
            })
            continue
        body = FRONTMATTER_RE.sub("", raw).strip()
        if not re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip():
            findings.append({
                "type": "STUB_PAGE",
                "page": rel,
                "detail": "Body has no real content (stub comment only)",
            })

    return findings


BACKLINK_FILTER_SYSTEM = """You are a wiki curator for Ann Arbor's A2Zero carbon neutrality plan.

You will receive a wiki page body and a list of candidate entity mentions found by string matching.
For each candidate decide: is this mention a specific, deliberate reference to that named entity
where a wikilink would help a reader navigate to learn more about it?

Return ONLY valid JSON — no prose, no markdown fence:
{"confirmed": [{"title": "...", "slug": "...", "display_text": "..."}, ...]}

Include a candidate when:
- The text is specifically referring to this entity in the A2Zero context
- A wikilink would meaningfully help navigation or research

Exclude a candidate when:
- The match is incidental or generic (e.g. "solar" matching a long initiative name)
- The entity name is used as a common adjective rather than a proper reference
- The page is already about this entity (no need for a self-link)
- The mention is inside a source citation like ([[sources/...]])
"""


def _build_entity_catalogue(wiki_root: Path) -> dict[str, str]:
    """Return {display_title: vault-relative-slug} for all typed entity pages."""
    catalogue: dict[str, str] = {}
    for type_dir in _ENTITY_DIRS:
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


def _find_unlinked_candidates(body: str, catalogue: dict[str, str]) -> list[dict]:
    """Stage 1: string-match entity titles against page body, skipping already-linked text.

    Strips existing [[...]] wikilink markup before matching so we never re-propose
    an entity that is already linked.  Returns candidates sorted longest-title-first
    to prevent short names masking longer ones.
    """
    # Remove all wikilink markup so already-linked text is invisible to matching
    body_stripped = re.sub(r"\[\[[^\]]*\]\]", "", body)

    candidates = []
    for title, slug in sorted(catalogue.items(), key=lambda kv: -len(kv[0])):
        if len(title) < 5:
            # Very short titles (< 5 chars) produce too many false positives
            continue
        pattern = re.compile(
            r"(?<![A-Za-z0-9\[\]])" + re.escape(title) + r"(?![A-Za-z0-9\[\]])",
            re.IGNORECASE,
        )
        m = pattern.search(body_stripped)
        if not m:
            continue
        # Find match position in original body for context extraction
        orig_m = re.search(re.escape(m.group(0)), body, re.IGNORECASE)
        if not orig_m:
            continue
        start = max(0, orig_m.start() - 70)
        end = min(len(body), orig_m.end() + 70)
        context = "…" + body[start:end].replace("\n", " ") + "…"
        candidates.append({
            "title": title,
            "slug": slug,
            "display_text": orig_m.group(0),  # exact case as it appears
            "context": context,
        })
    return candidates


def _llm_filter_candidates(
    page_rel: str,
    body: str,
    candidates: list[dict],
) -> list[dict]:
    """Stage 2: ask the LLM which string-matched candidates are genuine entity references."""
    catalogue_lines = "\n".join(
        f'  "{c["title"]}" → [[{c["slug"]}]]  |  context: {c["context"]}'
        for c in candidates
    )
    # Omit full body — context snippets in CANDIDATES are sufficient and
    # sending large bodies causes empty responses on long strategy/overview pages.
    user_msg = f"PAGE: {page_rel}\n\nCANDIDATES:\n{catalogue_lines}"
    try:
        raw = chat(
            system=BACKLINK_FILTER_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=1024,
            model_hint="extraction",
            temperature=0.0,
        )
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        if not raw:
            print(f"[lint_wiki:backlink] WARNING: empty LLM response for {page_rel} — skipping")
            return []
        result = json.loads(raw)
        return result.get("confirmed", [])
    except Exception as e:
        print(f"[lint_wiki:backlink] WARNING: LLM filter failed for {page_rel}: {e}")
        return []


def backlink_lint(wiki_root: str, scope: list[str] | None = None) -> list[dict]:
    """Librarian lint: find entity mentions in page bodies that lack wikilinks.

    Stage 1 (fast): string-match entity catalogue against each page body.
    Stage 2 (LLM): filter out incidental / false-positive matches.

    Returns proposal dicts with keys: page, entity_title, entity_slug, display_text, context.
    """
    root = Path(wiki_root)
    catalogue = _build_entity_catalogue(root)
    scan_dirs = scope or _BACKLINK_DEFAULT_SCOPE
    proposals = []

    for type_dir in scan_dirs:
        dir_path = root / type_dir
        if not dir_path.exists():
            continue
        for page in sorted(dir_path.glob("*.md")):
            raw = page.read_text(encoding="utf-8", errors="replace")
            body = FRONTMATTER_RE.sub("", raw).strip()
            if not body:
                continue

            candidates = _find_unlinked_candidates(body, catalogue)
            if not candidates:
                continue

            page_rel = str(page.relative_to(root))
            print(f"[lint_wiki:backlink] {page_rel}: {len(candidates)} candidates → LLM filter…")
            confirmed = _llm_filter_candidates(page_rel, body, candidates)

            for c in confirmed:
                proposals.append({
                    "page": page_rel,
                    "entity_title": c.get("title", ""),
                    "entity_slug": c.get("slug", ""),
                    "display_text": c.get("display_text", c.get("title", "")),
                    "context": next(
                        (x["context"] for x in candidates if x["title"] == c.get("title")), ""
                    ),
                })

    return proposals


def write_backlink_proposals(wiki_root: str, proposals: list[dict]) -> None:
    """Write backlink lint proposals to review-queue.md, replacing any unannotated backlink section."""
    if not proposals:
        print("[lint_wiki:backlink] No unlinked entity mentions found.")
        return

    rq_path = Path(wiki_root).parent / "review-queue.md"
    today = date.today().isoformat()

    lines = [f"\n## Backlink Lint — {today}\n"]
    for p in proposals:
        lines.append(
            f"### [LINK_PROPOSED] {p['page']} ← {p['entity_slug']}"
        )
        lines.append(f'- Display text: "{p["display_text"]}"')
        lines.append(f"- Context: {p['context']}")
        lines.append("- Action: [ ] APPROVE_LINK  [ ] KEEP_UNLINKED  [ ] DEFER")
        lines.append("- Notes: _Add any notes_\n")
    new_section = "\n".join(lines)

    if rq_path.exists():
        text = rq_path.read_text(encoding="utf-8")
        m = _BACKLINK_SECTION_RE.search(text)
        if m and re.search(r"\[x\]", m.group(0), re.IGNORECASE):
            print("[lint_wiki:backlink] WARNING: existing backlink section has annotations — appending.")
            text = text.rstrip() + new_section
        else:
            text = _BACKLINK_SECTION_RE.sub("", text)
            text = text.rstrip() + new_section
        rq_path.write_text(text, encoding="utf-8")
    else:
        rq_path.write_text(new_section.lstrip(), encoding="utf-8")

    print(f"[lint_wiki:backlink] {len(proposals)} proposals written to review-queue.md")


def write_structural_findings(wiki_root: str, findings: list[dict]) -> None:
    """Write structural lint findings to review-queue.md, replacing any existing structural section.

    Each run owns exactly one slot — old findings are never left alongside new ones.
    """
    rq_path = Path(wiki_root).parent / "review-queue.md"
    today = date.today().isoformat()

    if findings:
        lines = [f"\n## Structural Lint — {today}\n"]
        for f in findings:
            lines.append(f"- [{f['type']}] `{f['page']}` — {f['detail']}")
        lines.append("")
        new_section = "\n".join(lines)
    else:
        new_section = ""  # empty = erase old section

    if rq_path.exists():
        text = rq_path.read_text(encoding="utf-8")
        text = _STRUCTURAL_SECTION_RE.sub("", text)  # remove all old structural sections
        text = text.rstrip() + new_section
        rq_path.write_text(text, encoding="utf-8")
    elif new_section:
        rq_path.write_text(new_section.lstrip(), encoding="utf-8")

    if findings:
        print(f"[lint_wiki:structural] {len(findings)} findings written to review-queue.md")
    else:
        print("[lint_wiki:structural] No issues found.")


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
    from pipeline._aliases import fuzzy_candidates

    root = Path(wiki_root)
    proposals = []

    # Collect misrouted pages from topics/ that have a non-topic type frontmatter.
    # These are pooled into the comparison group for their declared type so they
    # can be detected as duplicates of correctly-routed pages.
    _misrouted_by_dir: dict[str, list[Path]] = {}
    _topics_dir = root / "topics"
    if _topics_dir.exists():
        for _tp in _topics_dir.glob("*.md"):
            _raw = _tp.read_text(encoding="utf-8", errors="replace")
            _fm = re.match(r"^---\n(.*?)\n---\n", _raw, re.DOTALL)
            if not _fm:
                continue
            for _line in _fm.group(1).splitlines():
                if _line.startswith("type:"):
                    _pt = _line.split(":", 1)[1].strip().strip("'\"")
                    if _pt != "topic":
                        _target = _CANONICAL_DIR_BY_TYPE.get(_pt)
                        if _target:
                            _misrouted_by_dir.setdefault(_target, []).append(_tp)
                    break

    for type_dir in ["actors", "initiatives", "locations", "political-events",
                     "technology", "funding-events", "meetings"]:
        dir_path = root / type_dir
        if not dir_path.exists():
            continue
        pages = list(dir_path.glob("*.md")) + _misrouted_by_dir.get(type_dir, [])
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
                    raw = chat(
                        system=SEMANTIC_VERDICT_SYSTEM,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=256,
                        model_hint="extraction",
                        temperature=0.0,
                    )
                    raw = raw.strip()
                    raw = re.sub(r"^```(?:json)?\s*", "", raw)
                    raw = re.sub(r"\s*```$", "", raw)
                    if not raw:
                        print(f"[lint_wiki:semantic] WARNING: empty LLM response for {title_a!r} vs {title_b!r} — skipping")
                        continue
                    verdict = json.loads(raw)
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


def write_semantic_proposals(wiki_root: str, proposals: list[dict]) -> None:
    """Write semantic proposals to review-queue.md, replacing any unannotated semantic section.

    If the existing semantic section already has user annotations ([x] checked), the new
    proposals are appended rather than replacing — preserving work in progress.
    """
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
    new_section = "\n".join(lines)

    if rq_path.exists():
        text = rq_path.read_text(encoding="utf-8")
        m = _SEMANTIC_SECTION_RE.search(text)
        if m:
            existing_block = m.group(0)
            if re.search(r"\[x\]", existing_block, re.IGNORECASE):
                # User has unresolved annotations — append rather than clobber
                print("[lint_wiki:semantic] WARNING: existing semantic section has annotations — appending new proposals.")
                text = text.rstrip() + new_section
            else:
                # No annotations yet — safe to replace
                text = _SEMANTIC_SECTION_RE.sub("", text)
                text = text.rstrip() + new_section
        else:
            text = text.rstrip() + new_section
        rq_path.write_text(text, encoding="utf-8")
    else:
        rq_path.write_text(new_section.lstrip(), encoding="utf-8")

    print(f"[lint_wiki:semantic] {len(proposals)} proposals written to review-queue.md")


def _cleanup_review_queue(rq_path_str: str) -> None:
    """Remove resolved proposal blocks from review-queue.md after apply.

    Drops blocks where the user checked APPROVE_MERGE, APPROVE_TEMPORAL_SUCCESSION,
    or KEEP_SEPARATE. Keeps DEFER'd blocks and any unannotated (still-pending) blocks.
    Also removes empty semantic section headers left behind after all proposals are cleared.
    """
    path = Path(rq_path_str)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if PROPOSAL_HEADER_RE.match(line.strip()):
            # Collect the entire proposal block (until next proposal header, section header, or EOF)
            block: list[str] = [line]
            i += 1
            while i < len(lines):
                if PROPOSAL_HEADER_RE.match(lines[i].strip()) or lines[i].startswith("## "):
                    break
                block.append(lines[i])
                i += 1
            block_text = "".join(block)
            if _DEFER_RE.search(block_text):
                result.extend(block)  # keep: user explicitly deferred
            elif _RESOLVED_RE.search(block_text):
                pass  # drop: resolved (approved or keep-separate)
            else:
                result.extend(block)  # keep: unannotated / still pending
        else:
            result.append(line)
            i += 1

    output = "".join(result)
    # Remove empty semantic lint section headers left behind when all proposals were cleared
    output = re.sub(
        r"\n## Semantic Lint — [^\n]+\n\s*(?=\n## |\Z)",
        "\n",
        output,
        flags=re.DOTALL,
    )
    path.write_text(output, encoding="utf-8")


def _replace_wiki_page_body(page_path: str, new_body: str) -> None:
    """Replace the body section of a wiki page, preserving frontmatter intact."""
    content = Path(page_path).read_text(encoding="utf-8")
    m = re.match(r"^(---\n.*?\n---\n)", content, re.DOTALL)
    frontmatter = m.group(1) if m else ""
    Path(page_path).write_text(frontmatter + "\n" + new_body.strip() + "\n", encoding="utf-8")


def _parse_approved_proposals(review_queue_path: str) -> list[dict]:
    """Parse review-queue.md for checked (approved) proposals.

    Handles three proposal types:
      MERGE / TEMPORAL_SUCCESSION — header: ### [TYPE] page_a + page_b
      LINK                        — header: ### [LINK_PROPOSED] page ← slug
    """
    text = Path(review_queue_path).read_text(encoding="utf-8", errors="replace")
    proposals = []
    current: dict | None = None

    for line in text.splitlines():
        stripped = line.strip()

        # --- detect proposal header ---
        merge_m = _MERGE_HEADER_RE.match(stripped)
        link_m = _LINK_HEADER_RE.match(stripped)

        if merge_m:
            current = {
                "type": merge_m.group(1),
                "page_a": merge_m.group(2).strip(),
                "page_b": merge_m.group(3).strip(),
            }
            continue

        if link_m:
            current = {
                "type": "LINK_PROPOSED",
                "page": link_m.group(1).strip(),
                "slug": link_m.group(2).strip(),
                "display_text": "",  # filled below
            }
            continue

        if current is None:
            continue

        # --- capture display text for LINK proposals ---
        dt_m = _DISPLAY_TEXT_RE.match(stripped)
        if dt_m and current.get("type") == "LINK_PROPOSED":
            current["display_text"] = dt_m.group(1)
            continue

        # --- detect approval action ---
        if re.search(r"\[x\] APPROVE_MERGE", line, re.IGNORECASE):
            proposals.append({**current, "approved_action": "MERGE"})
            current = None
        elif re.search(r"\[x\] APPROVE_TEMPORAL_SUCCESSION", line, re.IGNORECASE):
            proposals.append({**current, "approved_action": "TEMPORAL_SUCCESSION"})
            current = None
        elif re.search(r"\[x\] APPROVE_LINK", line, re.IGNORECASE):
            proposals.append({**current, "approved_action": "LINK"})
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
    """Execute approved proposals from review-queue.md, then clean resolved items from the queue."""
    from pipeline.pass2c_merge import merge_pages as _merge_pages
    from pipeline._aliases import add_alias

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
        if p["approved_action"] == "LINK":
            page_rel = p.get("page", "")
            entity_slug = p.get("slug", "")
            display_text = p.get("display_text", "")
            page_path = root / page_rel

            if not page_path.exists():
                print(f"[lint_wiki:apply] WARNING: page not found for LINK: {page_rel}")
                continue
            if not display_text:
                print(f"[lint_wiki:apply] WARNING: no display text for LINK in {page_rel}")
                continue

            content = page_path.read_text(encoding="utf-8")
            plain_pattern = re.compile(
                r"(?<!\[\[)(?<!\|)" + re.escape(display_text) + r"(?!\]\])",
                re.IGNORECASE,
            )
            match = plain_pattern.search(content)
            if match:
                actual_text = match.group(0)
                wikilink = f"[[{entity_slug}|{actual_text}]]"
                new_content, n = plain_pattern.subn(wikilink, content, count=1)
                page_path.write_text(new_content, encoding="utf-8")
                print(f"[lint_wiki:apply] LINK: '{actual_text}' → [[{entity_slug}]] in {page_rel}")
            else:
                print(f"[lint_wiki:apply] WARNING: display text not found in {page_rel}: '{display_text}'")
            continue

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


    # Remove resolved blocks from queue — inbox stays clean
    _cleanup_review_queue(rq_path)
    print("[lint_wiki:apply] review-queue.md updated — resolved proposals removed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A2Zero wiki linter")
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument("--structural", action="store_true")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--backlink", action="store_true",
                        help="Librarian lint: find unlinked entity mentions in page bodies")
    parser.add_argument("--scope", nargs="+", default=None,
                        metavar="DIR",
                        help="Directories to scan for backlink lint (default: strategies overviews)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--aliases-path", default="registry/entity_aliases.json")
    parser.add_argument("--merge-log", default="registry/merge-log.jsonl")
    args = parser.parse_args()

    if args.structural:
        findings = structural_lint(args.wiki_root)
        write_structural_findings(args.wiki_root, findings)

    if args.semantic:
        proposals = semantic_lint(args.wiki_root)
        write_semantic_proposals(args.wiki_root, proposals)

    if args.backlink:
        bl_proposals = backlink_lint(args.wiki_root, scope=args.scope)
        write_backlink_proposals(args.wiki_root, bl_proposals)

    if args.apply:
        apply_proposals(args.wiki_root, args.aliases_path, args.merge_log)

    if not any([args.structural, args.semantic, args.backlink, args.apply]):
        print("Specify at least one mode: --structural, --semantic, --backlink, --apply")
