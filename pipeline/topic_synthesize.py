"""Topic Synthesis: capture cross-entity Q&A from agentic sessions, promote
approved entries to durable wiki/topics/ pages, and keep them compounding.

See docs/architecture/topic-synthesis-architecture.md for design rationale.
"""
import re
import yaml
from pathlib import Path
from pipeline._llm import chat


_ENTRY_HEADER_RE = re.compile(r"^## (.+?) \| (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
_RESOLUTION_RE = re.compile(
    r"Resolution:\s*\[([ xX])\]\s*Promote to wiki/topics/<slug>\.md\s*\[([ xX])\]\s*Dismiss"
)

# Entity page types that a topic may legitimately cite as evidence.
_ENTITY_TYPE_PREFIXES = frozenset({
    "actors", "initiatives", "locations", "technology",
    "funding-events", "meetings", "political-events",
})


def append_query_log_entry(
    question: str,
    answer_text: str,
    wiki_root: str,
    query_log_path: str,
    run_date: str,
) -> None:
    """Format and append one Q&A entry to query-log.md.

    Idempotent: does nothing if an entry with the identical question+date
    already exists, so re-running log-query after an interrupted session
    doesn't create a duplicate.
    """
    path = Path(query_log_path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    for match in _ENTRY_HEADER_RE.finditer(existing):
        if match.group(1) == question.strip() and match.group(2) == run_date:
            return

    entry = (
        f"\n## {question.strip()} | {run_date}\n"
        f"{answer_text.strip()}\n"
        f"Resolution: [ ] Promote to wiki/topics/<slug>.md  [ ] Dismiss\n"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def parse_query_log(log_path: str) -> list[dict]:
    """Parse query-log.md into a list of entry dicts.

    Each dict: {question, date, answer, promote, dismiss, block}. `block` is the
    entry's raw text (header + answer + resolution line), used by
    promote_query_log_entries to remove exactly this entry after promotion.
    """
    path = Path(log_path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")

    headers = list(_ENTRY_HEADER_RE.finditer(text))
    entries: list[dict] = []
    for i, m in enumerate(headers):
        block_start = m.start()
        block_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[block_start:block_end].rstrip("\n")

        after_header = text[m.end():block_end]
        res_match = _RESOLUTION_RE.search(after_header)
        answer = after_header[: res_match.start()].strip() if res_match else after_header.strip()
        promote = bool(res_match) and res_match.group(1).lower() == "x"
        dismiss = bool(res_match) and res_match.group(2).lower() == "x"

        entries.append({
            "question": m.group(1),
            "date": m.group(2),
            "answer": answer,
            "promote": promote,
            "dismiss": dismiss,
            "block": block,
        })
    return entries


def extract_cited_slugs(answer_text: str) -> list[str]:
    """Return every unique [[slug]]/[[slug|Display]] wikilink target, in order."""
    seen: set[str] = set()
    out: list[str] = []
    for slug in _WIKILINK_RE.findall(answer_text):
        slug = slug.strip()
        if slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def validate_cited_entities(slugs: list[str], wiki_root: str) -> tuple[list[str], list[str]]:
    """Split cited slugs into (valid, missing) based on filesystem existence.

    Missing slugs must be surfaced to the caller — never silently dropped.
    """
    root = Path(wiki_root)
    valid: list[str] = []
    missing: list[str] = []
    for slug in slugs:
        if (root / f"{slug}.md").exists():
            valid.append(slug)
        else:
            missing.append(slug)
    return valid, missing


def _read_cited_topics(wiki_root: str, topic_slug: str) -> list[str]:
    """Read the cited-topics frontmatter list for an existing topic page."""
    page = Path(wiki_root) / f"{topic_slug}.md"
    if not page.exists():
        return []
    text = page.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return []
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return []
    return fm.get("cited-topics") or []


def detect_citation_cycle(
    topic_slug: str,
    cited_topic_slugs: list[str],
    wiki_root: str,
) -> list[str]:
    """DFS over cited-topics frontmatter to detect a cycle back to topic_slug.

    Returns the cycle path (e.g. [topic_slug, ..., topic_slug]) if one would be
    created by topic_slug citing cited_topic_slugs, or [] if acyclic.
    """
    def _dfs(current: str, path: list[str], visited: set[str]) -> list[str]:
        if current == topic_slug and path:
            return path + [current]
        if current in visited:
            return []
        visited.add(current)
        for nxt in _read_cited_topics(wiki_root, current):
            result = _dfs(nxt, path + [current], visited)
            if result:
                return result
        return []

    for cited in cited_topic_slugs:
        cycle = _dfs(cited, [], set())
        if cycle:
            return [topic_slug] + cycle
    return []


def slugify_question(question: str) -> str:
    """Convert a question string into a kebab-case topic slug (no type prefix)."""
    text = question.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    words = text.split("-")
    return "-".join(words[:12])


def build_topic_page(
    question: str,
    answer_text: str,
    cited_entities: list[str],
    cited_topics: list[str],
    run_date: str,
    promoted_by: str = "caleb",
):
    """Build a WikiPage for a newly-promoted topic. Does not write to disk."""
    from pipeline._pages import build_wiki_page

    slug = f"topics/{slugify_question(question)}"
    frontmatter = {
        "type": "topic",
        "title": question.strip(),
        "declared": run_date,
        "declared-by": promoted_by,
        "promoted-from-query": question.strip(),
        "cited-entities": cited_entities,
        "cited-topics": cited_topics,
        "last-rebuilt": run_date,
        "governance": "synthesized",
    }
    return build_wiki_page(
        page_type="topic",
        slug=slug,
        frontmatter=frontmatter,
        body=answer_text.strip(),
    )


def promote_query_log_entries(
    wiki_root: str,
    query_log_path: str,
    run_date: str,
    promoted_by: str = "caleb",
) -> dict:
    """Promote every Promote-marked entry in query-log.md to a wiki/topics/ page.

    Dismiss-marked entries are dropped without writing a page. Unmarked entries
    are left untouched for further review. Hard-fails (raises) on the first
    Promote-marked entry that cites a hallucinated entity slug or would create a
    topic citation cycle — better to stop and surface the problem than silently
    drop a citation the human hasn't reviewed.

    Returns {"promoted": [slug, ...], "dismissed": [question, ...]}.
    """
    from pipeline._pages import write_wiki_page

    entries = parse_query_log(query_log_path)
    promoted: list[str] = []
    dismissed: list[str] = []
    resolved_blocks: list[str] = []

    for entry in entries:
        if entry["promote"]:
            cited = extract_cited_slugs(entry["answer"])
            valid, missing = validate_cited_entities(cited, wiki_root)
            if missing:
                raise ValueError(
                    f"promote_query_log_entries: entry {entry['question']!r} cites "
                    f"nonexistent slug(s) {missing!r} — fix the answer or the wiki "
                    f"before promoting."
                )
            cited_topics = [s for s in valid if s.startswith("topics/")]
            cited_entities = [s for s in valid if not s.startswith("topics/")]

            topic_slug = f"topics/{slugify_question(entry['question'])}"
            cycle = detect_citation_cycle(topic_slug, cited_topics, wiki_root)
            if cycle:
                raise ValueError(
                    f"promote_query_log_entries: entry {entry['question']!r} would "
                    f"create a topic citation cycle: {' -> '.join(cycle)}"
                )

            page = build_topic_page(
                question=entry["question"],
                answer_text=entry["answer"],
                cited_entities=cited_entities,
                cited_topics=cited_topics,
                run_date=run_date,
                promoted_by=promoted_by,
            )
            write_wiki_page(page, wiki_root)
            promoted.append(page.slug)
            resolved_blocks.append(entry["block"])
        elif entry["dismiss"]:
            dismissed.append(entry["question"])
            resolved_blocks.append(entry["block"])

    if resolved_blocks:
        _clear_resolved_entries(query_log_path, resolved_blocks)

    return {"promoted": promoted, "dismissed": dismissed}


def _clear_resolved_entries(query_log_path: str, resolved_blocks: list[str]) -> None:
    """Remove the given entry blocks from query-log.md, leaving everything else intact."""
    path = Path(query_log_path)
    text = path.read_text(encoding="utf-8")
    for block in resolved_blocks:
        text = text.replace(block, "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    path.write_text(text, encoding="utf-8")


# ── Regeneration path ────────────────────────────────────────────────────────
#
# Topic pages are ONE cohesive holistic narrative — never split into a frozen
# "original" section plus a dynamic update section, unlike strategy pages.
# Strategies get that split because CAP-2020 is a one-time locked planning
# document; topics have no equivalent, so every regeneration re-weaves the
# full prior narrative with the full current body of every cited entity into
# a single coherent whole (generalizing pipeline.pass2c_merge's two-source
# merge pattern to N sources).
#
# Anti-drift discipline: pull_full_entity_bodies() re-reads every cited page
# fresh from disk on every call — never cached, never summarized. This is the
# exact discipline that fixed a real content-loss bug in pass1b_synthesize.py
# (commit 6049b00): a regeneration that sees only a compressed digest instead
# of the full prior text silently drops facts.

_TOPIC_REGEN_SYSTEM = """You are regenerating a topic page for Ann Arbor's A2Zero \
wiki. A topic page is ONE cohesive holistic narrative answering a cross-entity \
question — never split into a frozen "original" section and a dynamic update \
section.

You will receive:
1. The full existing topic narrative (not a summary)
2. The full current body of every entity and topic this page cites (not summaries)

Rules:
- Preserve every fact from the existing narrative that is still true
- Integrate new material from the cited pages' current bodies where it adds to \
or updates the narrative
- Maintain inline wikilink citations to entities/topics: [[actors/foo|Display]]
- Never invent a citation to a page that wasn't provided in the cited bodies
- Produce a single coherent narrative a reader would find complete — not the \
old text with new paragraphs stapled on
- Output ONLY the narrative body text — no frontmatter, no heading, no preamble
"""


def pull_full_entity_bodies(wiki_root: str, slugs: list[str]) -> dict[str, str]:
    """Re-read the full current body of every slug fresh from disk.

    Never cached — must be called fresh on every regeneration so drift-inducing
    stale content can never leak into the Writer prompt.
    """
    from pipeline._pages import load_existing_body

    root = Path(wiki_root)
    bodies: dict[str, str] = {}
    for slug in slugs:
        page_path = root / f"{slug}.md"
        if page_path.exists():
            bodies[slug] = load_existing_body(str(page_path))
    return bodies


def regenerate_topic(topic_slug: str, wiki_root: str, run_date: str) -> str | None:
    """Holistically reweave a topic page's narrative from its full prior text
    plus the full current body of every cited entity/topic.

    Returns the new body on success. On any failure, returns None and leaves
    the existing page untouched — same never-lose-content contract as
    pass2c_merge.merge_pages.
    """
    page_path = Path(wiki_root) / f"{topic_slug}.md"
    if not page_path.exists():
        print(f"[topic_synthesize] regenerate_topic: page not found: {topic_slug}")
        return None

    text = page_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        print(f"[topic_synthesize] regenerate_topic: no frontmatter in {topic_slug}")
        return None
    fm = yaml.safe_load(m.group(1)) or {}
    prior_narrative = m.group(2).strip()

    cited_slugs = (fm.get("cited-entities") or []) + (fm.get("cited-topics") or [])
    cited_bodies = pull_full_entity_bodies(wiki_root, cited_slugs)

    cited_block = "\n".join(
        f"\n[CITED: {slug}]\n{body}\n[END CITED]" for slug, body in cited_bodies.items()
    )
    prompt = (
        f"Topic: {fm.get('title', topic_slug)}\n\n"
        f"[EXISTING NARRATIVE]\n{prior_narrative}\n[END EXISTING NARRATIVE]\n"
        f"{cited_block}\n\n"
        "Produce the reweaved narrative now."
    )

    try:
        raw = chat(
            system=_TOPIC_REGEN_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
            model_hint="merge",
            temperature=0.0,
        )
        new_body = raw.strip()
    except Exception as e:
        print(f"[topic_synthesize] regenerate_topic failed for {topic_slug}: {e} — keeping existing body")
        return None

    fm["cited-entities"] = [s for s in extract_cited_slugs(new_body) if not s.startswith("topics/")]
    fm["cited-topics"] = [s for s in extract_cited_slugs(new_body) if s.startswith("topics/")]
    fm["last-rebuilt"] = run_date
    new_fm = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    page_path.write_text(f"---\n{new_fm}\n---\n\n{new_body}\n", encoding="utf-8")
    return new_body


def find_topics_touched(wiki_root: str, touched_entity_slugs: list[str]) -> list[str]:
    """Return topic slugs whose cited-entities/cited-topics intersect the given
    touched entity slugs, including topic-to-topic citation chains.

    Skips any topic page with governance: frozen — those are excluded from
    automated regeneration entirely.
    """
    root = Path(wiki_root)
    topics_dir = root / "topics"
    if not topics_dir.exists():
        return []

    all_topics: dict[str, dict] = {}
    for page in topics_dir.glob("*.md"):
        text = page.read_text(encoding="utf-8", errors="replace")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if fm.get("governance") == "frozen":
            continue
        all_topics[f"topics/{page.stem}"] = fm

    touched: set[str] = set()
    frontier = set(touched_entity_slugs)
    changed = True
    while changed:
        changed = False
        for slug, fm in all_topics.items():
            if slug in touched:
                continue
            cited = set(fm.get("cited-entities") or []) | set(fm.get("cited-topics") or [])
            if cited & frontier:
                touched.add(slug)
                frontier.add(slug)
                changed = True

    return sorted(touched)
