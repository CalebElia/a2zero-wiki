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
import yaml
from datetime import date
from pathlib import Path
from pipeline._llm import chat

# Pages exempt from orphan and empty-page checks — hub pages, auto-generated, or top-level containers
ORPHAN_EXEMPT_NAMES = frozenset({"index.md", "log.md", "hot.md"})
ORPHAN_EXEMPT_DIRS = frozenset({"strategies", "sources", "overviews", "topics"})

FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n?", re.DOTALL)

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")

# Matches the start of any proposal block header — used as a block-boundary detector.
# Specialised header regexes below handle per-type parsing.
PROPOSAL_HEADER_RE = re.compile(
    r"### \[(MERGE_PROPOSED|TEMPORAL_SUCCESSION_PROPOSED|LINK_PROPOSED|CONTRADICTION_PROPOSED)\] (.+)"
)

# Per-type proposal header parsers
_MERGE_HEADER_RE = re.compile(
    r"### \[(MERGE_PROPOSED|TEMPORAL_SUCCESSION_PROPOSED)\] (.+?) \+ (.+)"
)
_LINK_HEADER_RE = re.compile(
    r"### \[LINK_PROPOSED\] (.+?) ← (.+)"
)
_CONTRADICTION_HEADER_RE = re.compile(
    r"### \[CONTRADICTION_PROPOSED\] (.+)"
)
_DISPLAY_TEXT_RE = re.compile(r'^- Display text: "(.+)"')
_CONTEXT_RE = re.compile(r"^- Context: (.+)")

# Patterns for approved/resolved actions
_RESOLVED_RE = re.compile(
    r"\[x\]\s+(?:APPROVE_MERGE|APPROVE_TEMPORAL_SUCCESSION|KEEP_SEPARATE|APPROVE_LINK|KEEP_UNLINKED"
    r"|APPROVE_CREATE|DISMISS)",
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
_CONTRADICTION_SWEEP_SECTION_RE = re.compile(
    r"\n## Contradiction Sweep —[^\n]*\n.*?(?=\n## |\Z)", re.DOTALL
)
_BACKLINK_SECTION_RE = re.compile(
    r"\n## Backlink Lint —[^\n]*\n.*?(?=\n## |\Z)", re.DOTALL
)
_STALENESS_SECTION_RE = re.compile(
    r"\n## Staleness Lint —[^\n]*\n.*?(?=\n## |\Z)", re.DOTALL
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

    # Topic citation isolation — topics are a citation sink, never a source of
    # evidence. Any non-topics/ page (including digest.md) citing a topic as
    # content is a violation; topic-to-topic citation is allowed (governed by
    # the promotion-time cycle guard). index.md/log.md/hot.md are exempt —
    # they're auto-rebuilt navigation/audit surfaces that must list every page
    # (including topics) for humans to find them, not analytical citations.
    for md_file in all_files:
        rel = str(md_file.relative_to(root))
        if md_file.parent.name == "topics" or md_file.name in ORPHAN_EXEMPT_NAMES:
            continue
        text = md_file.read_text(encoding="utf-8", errors="replace")
        for link in _parse_wikilinks(text):
            target = link.strip()
            if target.startswith("topics/"):
                findings.append({
                    "type": "TOPIC_CITATION_VIOLATION",
                    "page": rel,
                    "detail": f"[[{link}]] — non-topic pages must never cite a topic page",
                })

    # Governance alerts — nothing in meta/ should populate silently. Both are
    # purely informational (no checkbox here); resolution happens at the
    # source (meta/schema-drift.md for drift, meta/query-log.md + topic-promote
    # for candidates) and this just surfaces that something is waiting, in the
    # same review-queue.md the human already checks after every --structural run.
    from pipeline.schema_governance import schema_drift_findings
    findings.extend(schema_drift_findings(wiki_root))

    from pipeline.topic_synthesize import parse_query_log
    query_log_path = root.parent / "meta" / "query-log.md"
    for entry in parse_query_log(str(query_log_path)):
        if not entry["promote"] and not entry["dismiss"]:
            findings.append({
                "type": "QUERY_LOG_PENDING",
                "page": "meta/query-log.md",
                "detail": f"{entry['question']!r} ({entry['date']}) — awaiting Promote/Dismiss",
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


def _resolve_last_ingest_uuid(wiki_root: str) -> str | None:
    """Return the source-uuid of the last line of meta/ingest-stats.jsonl, or None."""
    stats_path = Path(wiki_root).parent / "meta" / "ingest-stats.jsonl"
    if not stats_path.exists():
        return None
    lines = stats_path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        return None
    try:
        return json.loads(lines[-1]).get("source-uuid")
    except json.JSONDecodeError:
        return None


def staleness_lint(wiki_root: str, source_uuid: str | None = None) -> list[dict]:
    """Flag entity pages the given source names (title/alias, word-boundary)
    that gained no citation to that source — the silent-staleness failure.

    Informational findings for human triage: a mention can legitimately go
    uncited when the source merely repeats an already-recorded fact.
    """
    from pipeline.recall_scan import (
        build_entity_name_index, build_ambiguous_scan_index, scan_source_for_known_entities,
    )

    root = Path(wiki_root)
    if source_uuid is None:
        source_uuid = _resolve_last_ingest_uuid(wiki_root)
        if source_uuid is None:
            print("[lint_wiki:staleness] no source-uuid given and no ingest-stats.jsonl — nothing to check")
            return []

    matches = sorted((root / "sources").rglob(f"{source_uuid}.md"))
    if not matches:
        print(f"[lint_wiki:staleness] source {source_uuid!r} not found under wiki/sources/")
        return []
    source_text = matches[0].read_text(encoding="utf-8")

    index = build_entity_name_index(wiki_root)
    ambiguous_index = build_ambiguous_scan_index(wiki_root)
    hits = scan_source_for_known_entities(source_text, index, ambiguous_index)

    # Context-dropped slugs from this ingest's integration plan — the
    # knowingly-deprioritized tail (RETRIEVE_TOKEN_BUDGET overflow). Humans
    # should triage these first. Guard against a missing/malformed plan file;
    # the finding itself is never skipped, only the annotation.
    context_dropped: set[str] = set()
    plan_path = root.parent / "integration-plans" / f"{source_uuid}.json"
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            context_dropped = set(plan.get("context-dropped") or [])
        except (OSError, json.JSONDecodeError):
            pass

    findings = []
    for slug in sorted(hits):
        page_path = root / f"{slug}.md"
        if not page_path.exists():
            continue
        body = page_path.read_text(encoding="utf-8")
        if f"/{source_uuid}" in body or f"{source_uuid}]]" in body:
            continue  # page cites this source somewhere — not stale
        names = ", ".join(hits[slug]["matched-names"][:3])
        detail = (
            f"source {source_uuid} mentions this entity "
            f"({hits[slug]['mentions']}× as: {names}) but the page has no "
            f"{source_uuid} citation — possible missed update"
        )
        if hits[slug].get("ambiguous"):
            siblings = ", ".join(hits[slug].get("ambiguous-with", []))
            detail += f" [ambiguous — verify against source: also matches {siblings}]"
        if slug in context_dropped:
            detail += " [context-dropped at ingest]"
        findings.append({
            "type": "STALE_ENTITY",
            "page": f"{slug}.md",
            "detail": detail,
        })
    return findings


def write_staleness_findings(wiki_root: str, findings: list[dict], source_uuid: str) -> None:
    """Write staleness findings to review-queue.md, replacing any prior staleness section."""
    rq_path = Path(wiki_root).parent / "review-queue.md"
    today = date.today().isoformat()

    if findings:
        lines = [f"\n## Staleness Lint — {today} (source: {source_uuid})\n"]
        for f in findings:
            lines.append(f"- [{f['type']}] `{f['page']}` — {f['detail']}")
        lines.append("")
        new_section = "\n".join(lines)
    else:
        new_section = ""

    if rq_path.exists():
        text = _STALENESS_SECTION_RE.sub("", rq_path.read_text(encoding="utf-8"))
        rq_path.write_text(text.rstrip() + new_section, encoding="utf-8")
    elif new_section:
        rq_path.write_text(new_section.lstrip(), encoding="utf-8")

    print(f"[lint_wiki:staleness] {len(findings)} findings written to review-queue.md"
          if findings else "[lint_wiki:staleness] No stale entities found.")


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


def _read_frontmatter_date(md_path: Path) -> str | None:
    """Return the `date:` frontmatter value, or None if absent/unparseable."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if line.startswith("date:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return None


def _read_frontmatter(md_path: Path) -> dict:
    """Return the full YAML frontmatter as a dict, or {} if missing/invalid."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def _political_event_structural_pairs(
    pages: list[Path], max_days_apart: int = 60
) -> list[tuple[Path, Path]]:
    """Pair political-event pages sharing event-type and an overlapping
    programs-authorized entity, dated within max_days_apart of each other.

    Fuzzy title matching misses the "anticipated announcement vs. reported
    outcome" duplicate pattern because the two pages are often titled very
    differently ("November 2024 SEU Ballot Question" vs "Ann Arbor voter
    authorization of the Sustainable Energy Utility") despite describing the
    same real-world vote. This structural signal catches that pattern
    regardless of title similarity. See docs/action-plan-2026-07-09.md Item 2.4.
    """
    parsed = []
    for page in pages:
        fm = _read_frontmatter(page)
        date_str = fm.get("date")
        try:
            d = date.fromisoformat(str(date_str)) if date_str else None
        except ValueError:
            d = None
        programs = set(fm.get("programs-authorized") or [])
        parsed.append((page, fm.get("event-type"), programs, d))

    pairs: list[tuple[Path, Path]] = []
    for i in range(len(parsed)):
        page_a, type_a, programs_a, date_a = parsed[i]
        if not type_a or not programs_a or not date_a:
            continue
        for j in range(i + 1, len(parsed)):
            page_b, type_b, programs_b, date_b = parsed[j]
            if not type_b or not programs_b or not date_b:
                continue
            if type_a != type_b or not (programs_a & programs_b):
                continue
            if abs((date_a - date_b).days) > max_days_apart:
                continue
            pairs.append((page_a, page_b))
    return pairs


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

        title_map: dict[str, list[Path]] = {}
        for page in pages:
            title, _ = _get_page_title_and_excerpt(page)
            title_map.setdefault(title, []).append(page)

        titles = list(title_map.keys())
        seen_pairs: set[frozenset] = set()

        # Identical titles within the same type directory are an unambiguous
        # duplicate signal — surface them directly without an LLM call. Before
        # this, title_map was title -> single Path, so a second page sharing an
        # exact title silently overwrote the first in the dict and was NEVER
        # compared to anything (the two SEU-vote pages that prompted this fix
        # shared the literal title "Ann Arbor voter authorization of the
        # Sustainable Energy Utility" and were invisible to this lint pass as a
        # result). See docs/action-plan-2026-07-09.md Item 2.4.
        for title, dup_pages in title_map.items():
            if len(dup_pages) < 2:
                continue
            for k in range(len(dup_pages)):
                for l in range(k + 1, len(dup_pages)):
                    page_a, page_b = dup_pages[k], dup_pages[l]
                    if type_dir == "meetings":
                        date_a = _read_frontmatter_date(page_a)
                        date_b = _read_frontmatter_date(page_b)
                        if date_a and date_b and date_a != date_b:
                            continue
                    pair = frozenset({str(page_a), str(page_b)})
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    proposals.append({
                        "type": "MERGE_PROPOSED",
                        "page_a": str(page_a.relative_to(root)),
                        "page_b": str(page_b.relative_to(root)),
                        "confidence": 1.0,
                        "reasoning": "Identical page title within the same type directory.",
                    })

        # political-events: fuzzy title matching misses the "anticipated
        # announcement vs. reported outcome" pattern because the two pages are
        # often titled very differently despite describing the same real-world
        # vote. Add structural candidates (same event-type, overlapping
        # programs-authorized, dates within 60 days) to the title-pair queue so
        # they get the same LLM verdict check as fuzzy-title matches.
        structural_extra: dict[str, set[str]] = {}
        if type_dir == "political-events":
            path_to_title = {p: t for t, ps in title_map.items() for p in ps}
            representative_pages = [ps[0] for ps in title_map.values()]
            for page_a, page_b in _political_event_structural_pairs(representative_pages):
                title_a, title_b = path_to_title[page_a], path_to_title[page_b]
                if title_a == title_b:
                    continue  # already handled by the exact-title pass above
                structural_extra.setdefault(title_a, set()).add(title_b)

        for i, title_a in enumerate(titles):
            candidates = set(fuzzy_candidates(title_a, titles[i + 1:], threshold=0.65))
            candidates |= structural_extra.get(title_a, set())
            for title_b in candidates:
                pair = frozenset({title_a, title_b})
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                path_a = title_map[title_a][0]
                path_b = title_map[title_b][0]

                # Meetings are point-in-time events, not renamable entities — a
                # differing date: frontmatter value conclusively proves two
                # meeting pages are distinct, regardless of how similar their
                # titles or bodies look. Skip before the LLM call entirely so
                # this class of false-positive can never recur (an LLM verdict
                # call previously proposed merging two meetings four months
                # apart, reasoning "different dated events... same entity" —
                # a self-contradiction the model shouldn't be trusted to catch).
                if type_dir == "meetings":
                    date_a = _read_frontmatter_date(path_a)
                    date_b = _read_frontmatter_date(path_b)
                    if date_a and date_b and date_a != date_b:
                        continue

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


# ─────────────────────────────────────────────────────────────────────────
# Contradiction sweep — one-time backward pass over already-ingested content.
#
# The `contradiction` page type has been fully specified in the schema and
# the Pass 2 extraction prompt since early in the project, but zero pages
# existed after 6 ingests — the READ-UNDERSTAND-INTEGRATE instruction that
# governs merging a new source's claims against an existing page body was
# telling the model prior facts were "still valid" with no branch for a
# genuine numeric conflict, so real discrepancies (a project's MW figure
# changing between annual reports) got silently smoothed into one number
# instead of flagged. That prompt is fixed (see WIKI_PAGES_SYSTEM), which
# stops this from recurring on FUTURE ingests. This sweep is the one-time
# backfill mechanism for the 6 sources already ingested before the fix.
# See docs/contradiction-tracking-assessment-2026-07-10.md.
# ─────────────────────────────────────────────────────────────────────────

_NUMERIC_CLAIM_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s?(?:MW|GWh|kWh|%|percent|metric tons?|tons?|households?|homes?"
    r"|installations?|MTCO2e|MTCO₂e|facilities|buildings)\b"
    r"|\$[\d,]+(?:\.\d+)?(?:\s?(?:million|thousand|M|K))?",
    re.IGNORECASE,
)


def _numeric_density_candidates(
    wiki_root: str, min_claims: int = 3, min_sources: int = 2
) -> list[dict]:
    """Deterministically rank initiative pages by how many distinct numeric
    claims they cite across how many distinct sources — the shape most at
    risk from the silent-merge failure mode this sweep exists to catch.
    Every known real contradiction (Wheeler Center MW, Solarize MW scope)
    has this shape: a multi-year quantitative figure cited from 2+ sources.
    """
    root = Path(wiki_root) / "initiatives"
    if not root.exists():
        return []
    candidates = []
    for page in sorted(root.glob("*.md")):
        text = page.read_text(encoding="utf-8", errors="replace")
        fm = _read_frontmatter(page)
        body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
        claims = _NUMERIC_CLAIM_RE.findall(body)
        sources = sorted(set(re.findall(r"\[\[(sources/[^\]|]+)", body)))
        if len(claims) >= min_claims and len(sources) >= min_sources:
            candidates.append({
                "slug": f"initiatives/{page.stem}",
                "title": fm.get("title", page.stem),
                "tags": (fm.get("tags") or [])[:4],
                "claim_count": len(claims),
                "sources": sources,
                "boosted": False,
            })
    candidates.sort(key=lambda c: (c["claim_count"], len(c["sources"])), reverse=True)
    return candidates


def _open_question_boost_slugs(wiki_root: str) -> set[str]:
    """Return initiative slugs whose digest open-questions phrasing suggests
    an unresolved specific (dates, scale, "advances to... at what scale",
    "how much... actually") rather than a purely qualitative gap.

    These are cases where the synthesis layer is already circling something
    concrete without landing on it — e.g. Strategy 1's real open-question
    "Whether the landfill solar concept advances to full development and at
    what scale" is the Wheeler Center MW discrepancy, sensed but unflagged.
    Used to boost candidate priority, not as a standalone detection path.
    """
    digest_path = Path(wiki_root) / "digest.md"
    if not digest_path.exists():
        return set()
    text = digest_path.read_text(encoding="utf-8", errors="replace")

    boost_markers = (
        "at what scale", "how much", "how many", "whether the", "actually",
        "measurable", "quantified", "reconcile",
    )
    boosted: set[str] = set()
    # Each "### [[strategies/...]]" block's core-initiatives + open line share
    # one strategy section; associate any open-question with boost language
    # to every core-initiative slug listed just above it in the same block.
    for block in re.split(r"\n### ", text)[1:]:
        core_m = re.search(r"\*\*core initiatives:\*\*(.+)", block)
        open_m = re.search(r"\*\*open:\*\*(.+)", block)
        if not core_m or not open_m:
            continue
        if not any(marker in open_m.group(1).lower() for marker in boost_markers):
            continue
        boosted.update(re.findall(r"\[\[(initiatives/[^\]|]+)", core_m.group(1)))
    return boosted


_CONTRADICTION_SWEEP_SYSTEM = """You are reviewing one A2Zero wiki initiative page against \
excerpts from the source documents it cites, looking for a genuine unreconciled numeric \
contradiction — a discrepancy that already survived on the page's own timeline, likely because \
an earlier extraction pass silently picked one figure instead of flagging both.

Return ONLY valid JSON with this exact structure:
{
  "contradiction_found": true|false,
  "confidence": 0.0,
  "title": "brief description of the conflict, e.g. 'Wheeler Center Solar Park capacity: 24MW vs 20MW'",
  "cross_source": true|false,
  "claims": [
    {"source": "sources/cap/cap-2020", "quote": "exact or close paraphrase of the conflicting figure and its context"},
    {"source": "sources/annual-reports/a2zero-year2", "quote": "..."}
  ],
  "why_it_matters": "1-2 sentences on the concrete stakes (e.g. affects assessed progress toward a stated target)",
  "best_guess_explanation": "1-2 sentences, or the literal string 'Unknown' if no source-supported explanation exists"
}

Rules:
- Only flag a REAL numeric disagreement about the SAME fact (same project, same metric, same
  scope) — not two different metrics, not a figure that grew because the underlying quantity
  legitimately grew over time (e.g. cumulative solar installed increasing year over year is
  growth, not a contradiction).
- "claims" must cite at least 2 sources with the literal or closely-paraphrased conflicting text.
- Every claims[].source value MUST be EXACTLY one of the slugs shown as a "--- slug ---" header
  in [SOURCE EXCERPTS] below — copy it verbatim, character for character. NEVER invent a source
  value, NEVER use the initiative page itself as a "source" (if the page body misquotes or
  overstates a source excerpt, that IS a valid contradiction — cite the source excerpt as one
  claim and quote the page body's conflicting text as the OTHER claim's "quote" field, but its
  "source" value must still be that same real source slug, describing what the page claims that
  source says vs. what the excerpt actually says).
- If the sources actually agree, or the excerpts don't contain enough to judge, set
  contradiction_found: false and confidence low — do not force a finding.
- Return ONLY the JSON object. No preamble, no code fences, no commentary.
"""


def _gather_source_excerpts(
    wiki_root: str, title: str, sources: list[str], max_lines_per_source: int = 20
) -> dict[str, str]:
    """Grep each cited source for lines relevant to this initiative's title,
    capped per source. Loading full sources (CAP-2020 alone is 4000+ lines)
    would blow the context budget for a bounded sweep; a keyword grep is the
    same technique used to manually verify the two backfilled cases in
    docs/contradiction-tracking-assessment-2026-07-10.md.
    """
    keywords = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", title)]
    excerpts: dict[str, str] = {}
    for source_slug in sources:
        source_path = Path(wiki_root) / f"{source_slug}.md"
        if not source_path.exists():
            continue
        lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [
            line.strip() for line in lines
            if any(kw in line.lower() for kw in keywords) and _NUMERIC_CLAIM_RE.search(line)
        ][:max_lines_per_source]
        if hits:
            excerpts[source_slug] = "\n".join(hits)
    return excerpts


def _slugify_title(title: str) -> str:
    text = re.sub(r"[^a-z0-9\s-]", "", title.strip().lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return "-".join(text.split("-")[:10])


def _build_contradiction_page(candidate: dict, verdict: dict, run_date: str) -> tuple[str, str]:
    """Deterministically assemble the contradiction page markdown from a
    structured LLM verdict. Returns (slug, full_file_content)."""
    slug = "contradictions/" + _slugify_title(verdict["title"])
    claims = verdict.get("claims", [])
    source_slugs = sorted({c["source"] for c in claims if c.get("source")})

    fm_lines = [
        "---",
        "type: contradiction",
        f'title: "{verdict["title"]}"',
        "sources:",
    ]
    fm_lines += [f"- '[[{s}]]'" for s in source_slugs]
    fm_lines += [
        f"cross-source: {'true' if verdict.get('cross_source') else 'false'}",
        "status: unresolved",
        "related-initiatives:",
        f"- '[[{candidate['slug']}]]'",
        "tags:",
    ]
    fm_lines += [f"- {t}" for t in candidate.get("tags") or ["contradiction-sweep"]]
    fm_lines += [
        f"source-first-seen: '[[{source_slugs[0]}]]'" if source_slugs else "source-first-seen: null",
        f"last-updated: '{run_date}'",
        "---",
        "",
        "## Conflicting claims",
        "",
    ]
    for c in claims:
        src = c.get("source", "")
        label = src.split("/")[-1]
        fm_lines.append(f"**{label}:** \"{c.get('quote', '')}\" ([[{src}|{label}]])")
        fm_lines.append("")
    fm_lines += [
        "## Why it matters",
        "",
        verdict.get("why_it_matters", ""),
        "",
        "## Best-guess explanation",
        "",
        verdict.get("best_guess_explanation", "Unknown"),
        "",
        f"_Surfaced by a contradiction sweep against {candidate['slug']} — human review required before this page is considered final; see docs/contradiction-tracking-assessment-2026-07-10.md for the mechanism._",
        "",
    ]
    return slug, "\n".join(fm_lines)


def _existing_contradiction_source_sets(wiki_root: str) -> list[frozenset]:
    """Return the `sources:` set of every existing wiki/contradictions/*.md
    page. Used to dedupe sweep candidates against already-backfilled pages
    by WHAT THEY'RE ABOUT (overlapping source citations), not by slug —
    the same real-world conflict (e.g. Wheeler Center's 24MW-vs-20MW figure)
    gets independently rediscovered once per initiative page that happens to
    cite it, and the LLM picks a different title/slug wording each time, so
    an exact-slug check alone misses the duplication entirely.
    """
    root = Path(wiki_root) / "contradictions"
    if not root.exists():
        return []
    out = []
    for page in root.glob("*.md"):
        fm = _read_frontmatter(page)
        sources = fm.get("sources") or []
        stripped = {re.sub(r"^\[\[|\]\]$", "", s) for s in sources}
        if stripped:
            out.append(frozenset(stripped))
    return out


def contradiction_sweep(
    wiki_root: str,
    max_candidates: int = 20,
    confidence_threshold: float = 0.6,
) -> list[dict]:
    """One-time backward sweep: rank initiative pages by numeric-claim density
    (boosted by digest open-questions that already smell like an unresolved
    specific), re-check the top N against fresh source excerpts via LLM
    verdict, and return proposal dicts ready for write_contradiction_proposals.

    Returns list of {slug, content, confidence, reasoning, related_initiative}.
    """
    candidates = _numeric_density_candidates(wiki_root)
    boosted_slugs = _open_question_boost_slugs(wiki_root)
    for c in candidates:
        c["boosted"] = c["slug"] in boosted_slugs
    candidates.sort(key=lambda c: (c["boosted"], c["claim_count"], len(c["sources"])), reverse=True)

    existing_source_sets = _existing_contradiction_source_sets(wiki_root)
    proposed_source_sets: list[frozenset] = []

    run_date = date.today().isoformat()
    proposals = []
    for candidate in candidates[:max_candidates]:
        excerpts = _gather_source_excerpts(wiki_root, candidate["title"], candidate["sources"])
        if len(excerpts) < 2:
            continue  # need at least 2 sources' worth of excerpts to compare

        page_body = re.sub(
            r"^---\n.*?\n---\n", "",
            (Path(wiki_root) / f"{candidate['slug']}.md").read_text(encoding="utf-8", errors="replace"),
            flags=re.DOTALL,
        )
        excerpt_block = "\n\n".join(f"--- {s} ---\n{t}" for s, t in excerpts.items())
        prompt = (
            f"Initiative: {candidate['title']} ({candidate['slug']})\n\n"
            f"[CURRENT PAGE BODY]\n{page_body}\n[END CURRENT PAGE BODY]\n\n"
            f"[SOURCE EXCERPTS]\n{excerpt_block}\n[END SOURCE EXCERPTS]\n\n"
            "Assess for a genuine unreconciled numeric contradiction now."
        )
        try:
            raw = chat(
                system=_CONTRADICTION_SWEEP_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                model_hint="extraction",
                temperature=0.0,
            )
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw)
            verdict = json.loads(raw)
        except Exception as e:
            print(f"[lint_wiki:contradiction-sweep] WARNING: verdict failed for {candidate['slug']!r}: {e}")
            continue

        if not verdict.get("contradiction_found") or float(verdict.get("confidence", 0)) < confidence_threshold:
            continue
        claims = verdict.get("claims", [])
        if len(claims) < 2:
            continue

        # Deterministic validation: every claim's source must be exactly one
        # of the real source slugs we actually showed the model — never trust
        # an LLM-emitted "source" value verbatim into a wikilink. Without
        # this, a real sweep run produced a claim citing the initiative page
        # itself as a "source" and another with "(page body)" appended
        # straight into what should have been a slug, which would have
        # written a malformed [[...]] link and a schema-violating sources:
        # entry straight into review-queue.md.
        if not all(c.get("source") in excerpts for c in claims):
            print(
                f"[lint_wiki:contradiction-sweep] WARNING: dropped candidate for "
                f"{candidate['slug']!r} — claim cited a source outside the given excerpts"
            )
            continue

        # Dedupe by WHAT this candidate is about (overlapping source
        # citations), not by slug — the same real-world conflict gets
        # independently rediscovered once per initiative page that cites it,
        # and the LLM titles it differently each time.
        claim_sources = frozenset(c["source"] for c in claims if c.get("source"))
        already_covered = any(
            len(claim_sources & existing) >= 2 for existing in existing_source_sets
        ) or any(
            len(claim_sources & proposed) >= 2 for proposed in proposed_source_sets
        )
        if already_covered:
            continue
        proposed_source_sets.append(claim_sources)

        slug, content = _build_contradiction_page(candidate, verdict, run_date)
        page_path = Path(wiki_root) / f"{slug}.md"
        if page_path.exists():
            continue  # already backfilled (slug happened to match too)

        reasoning = verdict.get("why_it_matters", "") or "Numeric conflict detected."
        if candidate["boosted"]:
            reasoning = "[digest open-question match] " + reasoning
        proposals.append({
            "slug": slug,
            "content": content,
            "confidence": float(verdict.get("confidence", 0)),
            "reasoning": reasoning,
            "related_initiative": candidate["slug"],
        })

    return proposals


def write_contradiction_proposals(wiki_root: str, proposals: list[dict]) -> None:
    """Write contradiction-sweep proposals to review-queue.md, replacing any
    unannotated Contradiction Sweep section (same pattern as semantic lint)."""
    if not proposals:
        print("[lint_wiki:contradiction-sweep] No contradiction candidates found.")
        return

    rq_path = Path(wiki_root).parent / "review-queue.md"
    today = date.today().isoformat()

    lines = [f"\n## Contradiction Sweep — {today}\n"]
    for p in proposals:
        lines.append(f"### [CONTRADICTION_PROPOSED] {p['slug']}")
        lines.append(f"- Related initiative: [[{p['related_initiative']}]]")
        lines.append(f"- Confidence: {p['confidence']:.2f}")
        lines.append(f"- Reasoning: {p['reasoning']}")
        lines.append("- Action: [ ] APPROVE_CREATE  [ ] DISMISS  [ ] DEFER")
        lines.append("- Notes: _Add any notes before approving_")
        lines.append("")
        lines.append("```markdown")
        lines.append(p["content"].rstrip())
        lines.append("```")
        lines.append("")
    new_section = "\n".join(lines)

    if rq_path.exists():
        text = rq_path.read_text(encoding="utf-8")
        m = _CONTRADICTION_SWEEP_SECTION_RE.search(text)
        if m:
            existing_block = m.group(0)
            if re.search(r"\[x\]", existing_block, re.IGNORECASE):
                print("[lint_wiki:contradiction-sweep] WARNING: existing section has annotations — appending new proposals.")
                text = text.rstrip() + new_section
            else:
                text = _CONTRADICTION_SWEEP_SECTION_RE.sub("", text)
                text = text.rstrip() + new_section
        else:
            text = text.rstrip() + new_section
        rq_path.write_text(text, encoding="utf-8")
    else:
        rq_path.write_text(new_section.lstrip(), encoding="utf-8")

    print(f"[lint_wiki:contradiction-sweep] {len(proposals)} proposals written to review-queue.md")


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
            # Collect the entire proposal block (until next proposal header, section
            # header, or EOF). A CONTRADICTION_PROPOSED block embeds the proposed
            # page's own markdown inside a ```markdown fence — that page body has
            # its own "## Conflicting claims" headers, which must NOT be mistaken
            # for a review-queue.md section boundary while inside the fence.
            block: list[str] = [line]
            i += 1
            in_fence = False
            while i < len(lines):
                stripped = lines[i].strip()
                if stripped.startswith("```"):
                    in_fence = not in_fence
                    block.append(lines[i])
                    i += 1
                    continue
                if not in_fence and (PROPOSAL_HEADER_RE.match(stripped) or lines[i].startswith("## ")):
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
    # Remove empty section headers left behind when all proposals in that
    # section were cleared.
    for header in ("Semantic Lint", "Contradiction Sweep"):
        output = re.sub(
            rf"\n## {re.escape(header)} — [^\n]+\n\s*(?=\n## |\Z)",
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

    Handles four proposal types:
      MERGE / TEMPORAL_SUCCESSION — header: ### [TYPE] page_a + page_b
      LINK                        — header: ### [LINK_PROPOSED] page ← slug
      CONTRADICTION               — header: ### [CONTRADICTION_PROPOSED] slug,
                                     body is a fenced ```markdown block (the
                                     full proposed page content) rather than
                                     an existing file reference — the target
                                     page doesn't exist yet.
    """
    text = Path(review_queue_path).read_text(encoding="utf-8", errors="replace")
    proposals = []
    current: dict | None = None

    for line in text.splitlines():
        stripped = line.strip()

        # --- CONTRADICTION_PROPOSED: fenced content spans multiple lines and
        # must be consumed before any other pattern below gets a chance to
        # match text inside the fence (e.g. the fenced page's own "## ..."
        # headers or "- " bullets must never be mistaken for queue metadata). ---
        if current is not None and current.get("type") == "CONTRADICTION_PROPOSED":
            if stripped == "```markdown":
                current["_in_fence"] = True
                continue
            if stripped == "```" and current.get("_in_fence"):
                current["_in_fence"] = False
                current["content"] = "\n".join(current.pop("_fence_lines", []))
                if current.get("approved_action"):
                    proposals.append({k: v for k, v in current.items() if not k.startswith("_")})
                current = None
                continue
            if current.get("_in_fence"):
                current.setdefault("_fence_lines", []).append(line)
                continue
            if re.search(r"\[x\]\s+APPROVE_CREATE", line, re.IGNORECASE):
                current["approved_action"] = "CREATE_CONTRADICTION"
            continue

        # --- detect proposal header ---
        merge_m = _MERGE_HEADER_RE.match(stripped)
        link_m = _LINK_HEADER_RE.match(stripped)
        contradiction_m = _CONTRADICTION_HEADER_RE.match(stripped)

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
                "context": "",  # filled below
            }
            continue

        if contradiction_m:
            current = {
                "type": "CONTRADICTION_PROPOSED",
                "slug": contradiction_m.group(1).strip(),
                "content": "",
                "approved_action": None,
                "_in_fence": False,
            }
            continue

        if current is None:
            continue

        # --- capture display text for LINK proposals ---
        dt_m = _DISPLAY_TEXT_RE.match(stripped)
        if dt_m and current.get("type") == "LINK_PROPOSED":
            current["display_text"] = dt_m.group(1)
            continue

        # --- capture context for LINK proposals, used to anchor --apply ---
        ctx_m = _CONTEXT_RE.match(stripped)
        if ctx_m and current.get("type") == "LINK_PROPOSED":
            current["context"] = ctx_m.group(1)
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
    """Execute approved proposals from review-queue.md and meta/schema-drift.md."""
    from pipeline.pass2c_merge import merge_pages as _merge_pages
    from pipeline._aliases import add_alias

    # Runs unconditionally, independent of review-queue.md's presence — a human
    # may have only schema-drift entries checked, no lint findings at all. Same
    # command resolves both: "process what I just checked boxes on."
    from pipeline.schema_governance import apply_schema_drift
    drift_result = apply_schema_drift(wiki_root)
    if drift_result["approved"] or drift_result["kept"]:
        print(
            f"[lint_wiki:apply] schema-drift: {len(drift_result['approved'])} type(s) approved, "
            f"{len(drift_result['kept'])} kept as fallback"
        )

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
            # Body-only search: a match inside YAML frontmatter (e.g. the same
            # word appearing incidentally in an auto-generated synthesis field)
            # must never be linked — only the markdown body is fair game.
            fm_m = FRONTMATTER_RE.match(content)
            body_start = fm_m.end() if fm_m else 0
            # Existing wikilink spans — a candidate match anywhere inside one of
            # these (not just immediately after "[[") must be skipped. A naive
            # boundary-only lookbehind/lookahead can match display_text as a
            # substring of an existing link's slug (e.g. display_text
            # "vegmichigan" matching inside "[[actors/vegmichigan|VegMichigan]]"),
            # producing nested/corrupted brackets like "[[actors/[[actors/...".
            existing_link_spans = [m.span() for m in WIKILINK_RE.finditer(content)]
            plain_pattern = re.compile(re.escape(display_text), re.IGNORECASE)
            body_candidates = [
                candidate
                for candidate in plain_pattern.finditer(content)
                if candidate.start() >= body_start
                and not any(start <= candidate.start() < end for start, end in existing_link_spans)
            ]

            # Anchor to the exact occurrence the original proposal quoted, when
            # available, rather than always taking the first body match — this
            # keeps re-applied proposals (and pages with a repeated display
            # string) pointed at the location the human actually reviewed.
            match = None
            context = p.get("context", "")
            context_core = context.strip().strip("…").strip()
            if context_core:
                context_pattern = re.compile(
                    r"\s+".join(re.escape(tok) for tok in context_core.split()),
                    re.IGNORECASE,
                )
                ctx_m = context_pattern.search(content, body_start)
                if ctx_m:
                    for candidate in body_candidates:
                        if ctx_m.start() <= candidate.start() < ctx_m.end():
                            match = candidate
                            break
            if match is None and body_candidates:
                match = body_candidates[0]
            if match:
                actual_text = match.group(0)
                wikilink = f"[[{entity_slug}|{actual_text}]]"
                new_content = content[:match.start()] + wikilink + content[match.end():]
                page_path.write_text(new_content, encoding="utf-8")
                print(f"[lint_wiki:apply] LINK: '{actual_text}' → [[{entity_slug}]] in {page_rel}")
            else:
                print(f"[lint_wiki:apply] WARNING: display text not found in {page_rel}: '{display_text}'")
            continue

        if p["approved_action"] == "CREATE_CONTRADICTION":
            slug = p["slug"]
            page_path = root / f"{slug}.md"
            if page_path.exists():
                print(f"[lint_wiki:apply] WARNING: contradiction page already exists, skipping: {slug}")
                continue
            if not p.get("content", "").strip():
                print(f"[lint_wiki:apply] WARNING: empty content for approved contradiction: {slug}")
                continue
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(p["content"].strip() + "\n", encoding="utf-8")
            print(f"[lint_wiki:apply] CREATED contradiction page: {slug}")
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
    parser.add_argument("--staleness", action="store_true",
                        help="Flag entity pages a given source names but never cites (STALE_ENTITY)")
    parser.add_argument("--source-uuid", default=None,
                        help="Source UUID for --staleness (default: last entry in meta/ingest-stats.jsonl)")
    parser.add_argument("--contradiction-sweep", action="store_true",
                        help="One-time backward sweep for unreconciled numeric conflicts in "
                             "already-ingested content — see docs/contradiction-tracking-assessment-2026-07-10.md")
    parser.add_argument("--max-candidates", type=int, default=20,
                        help="Cap on candidate pages re-checked per --contradiction-sweep run")
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

    if args.staleness:
        resolved_uuid = args.source_uuid or _resolve_last_ingest_uuid(args.wiki_root) or "unknown"
        st_findings = staleness_lint(args.wiki_root, source_uuid=args.source_uuid)
        write_staleness_findings(args.wiki_root, st_findings, resolved_uuid)

    if args.contradiction_sweep:
        cs_proposals = contradiction_sweep(args.wiki_root, max_candidates=args.max_candidates)
        write_contradiction_proposals(args.wiki_root, cs_proposals)

    if args.apply:
        apply_proposals(args.wiki_root, args.aliases_path, args.merge_log)

    if not any([args.structural, args.semantic, args.backlink, args.staleness,
                args.contradiction_sweep, args.apply]):
        print("Specify at least one mode: --structural, --semantic, --backlink, --staleness, "
              "--contradiction-sweep, --apply")
