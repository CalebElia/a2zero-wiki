"""Phase C of the ingest cycle: build the L1 strategy synthesis sections
and the L2 wiki/digest.md from the clean post-lint entity layer.

See docs/architecture/knowledge-synthesis-architecture.md for design rationale.
"""
import json
import re
import yaml
import anthropic
from pathlib import Path


_ENTITY_DIRS = [
    "actors", "initiatives", "locations", "technology",
    "funding-events", "meetings", "political-events",
]

_LOG_ENTRY_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2}) \| (.+?)\]$", re.MULTILINE)


def _parse_frontmatter(text: str) -> dict:
    """Return the YAML frontmatter as a dict, or {} if missing/invalid."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def gather_strategy_entities(wiki_root: str, strategy_slug: str) -> list[dict]:
    """Return entity dicts for every page tagged with this strategy.

    Each dict has: slug, title, type, one-liner.
    Used by build_strategy_synthesis() to feed the LLM the entity inventory.
    """
    root = Path(wiki_root)
    out: list[dict] = []
    for type_dir in _ENTITY_DIRS:
        for page in (root / type_dir).glob("*.md"):
            text = page.read_text(encoding="utf-8", errors="replace")
            fm = _parse_frontmatter(text)
            related = fm.get("related-strategies") or []
            if isinstance(related, str):
                related = [related]
            related = [r.strip("[]") for r in related]
            if strategy_slug not in related:
                continue
            out.append({
                "slug": fm.get("slug") or f"{type_dir}/{page.stem}",
                "title": fm.get("title", page.stem),
                "type": fm.get("type", type_dir.rstrip("s")),
                "one-liner": fm.get("one-liner", ""),
            })
    return out


def extract_recent_delta(log_path: str) -> dict:
    """Return {date, source_uuid} for the most recent ingest in log.md, or {}."""
    try:
        text = Path(log_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    matches = _LOG_ENTRY_RE.findall(text)
    if not matches:
        return {}
    date, source_uuid = matches[-1]
    return {"date": date, "source_uuid": source_uuid.strip()}


_STRATEGY_SYNTHESIS_SYSTEM = """You are synthesizing one strategy of Ann Arbor's A2Zero \
carbon neutrality plan into a compact structured summary that will be injected into \
future LLM ingest passes as prior context.

Given the strategy and its inventory of entity pages, return JSON with EXACTLY these keys:
- core-initiatives: list of up to 8 slugs of the most important initiatives (most \
central to the strategy's outcomes)
- core-actors: list of up to 6 slugs of the most important actors
- year-over-year-arc: one sentence describing the trajectory across ingested sources \
(e.g. "Residential solar grew 31% Y1→Y2; commercial pilot launched"). If only one \
source is ingested, describe the baseline state.
- open-questions: list of 2–4 short strings flagging what is unresolved or pending
- cross-strategy-links: list of slugs of entities you would expect to also appear in \
other strategies' core-initiatives (initiatives spanning multiple strategies)

Return ONLY the JSON object. Slugs use the form `actors/foo` or `initiatives/bar` — \
the same format as the inputs.
"""


def _strip_code_fence(text: str) -> str:
    """Strip ```json fences if present."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:-1]) if len(lines) > 2 else t
    return t.strip()


def _empty_synthesis() -> dict:
    return {
        "core-initiatives": [],
        "core-actors": [],
        "year-over-year-arc": "—",
        "open-questions": [],
        "cross-strategy-links": [],
    }


def build_strategy_synthesis(
    strategy_slug: str,
    strategy_title: str,
    entities: list[dict],
) -> dict:
    """LLM call: produce the synthesis dict for one strategy."""
    entity_lines = "\n".join(
        f"- [{e['type']}] {e['slug']} — {e['title']}: {e.get('one-liner','')}"
        for e in entities
    )
    user_msg = (
        f"Strategy: {strategy_title} ({strategy_slug})\n\n"
        f"Entity inventory ({len(entities)} pages):\n{entity_lines}\n\n"
        "Produce the synthesis JSON now."
    )
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            system=_STRATEGY_SYNTHESIS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text
        return json.loads(_strip_code_fence(raw))
    except Exception as e:
        print(f"[synthesize_wiki] build_strategy_synthesis failed for {strategy_slug}: {e}")
        return _empty_synthesis()


def write_strategy_synthesis(
    page_path: str,
    synthesis: dict,
    run_date: str,
) -> None:
    """Inject `synthesis:` block into the strategy page frontmatter. Preserve prose body."""
    page = Path(page_path)
    text = page.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError(f"No YAML frontmatter found in {page_path}")
    fm_text, body = m.group(1), m.group(2)
    fm = yaml.safe_load(fm_text) or {}

    # Stamp the rebuild date onto the synthesis block itself
    block = dict(synthesis)
    block["last-rebuilt"] = run_date
    fm["synthesis"] = block

    new_fm = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    page.write_text(f"---\n{new_fm}\n---\n{body}", encoding="utf-8")


_DIGEST_NARRATIVE_SYSTEM = """You write the narrative cross-strategy section of \
Ann Arbor's A2Zero wiki digest. This will be read by future LLM ingest passes as \
prior context, AND by humans skimming the current state of the wiki.

Given a structured summary of each of the 7 A2Zero strategies (the synthesis dicts), \
produce markdown prose. Required structure:

## Cross-strategy synthesis

<One short paragraph per strategy — what it has accomplished, the year-over-year \
arc, key actors. Reference entities as Obsidian wikilinks: [[initiatives/foo]] or \
[[actors/bar]]. Keep each paragraph to 3–5 sentences.>

<Closing paragraph titled "### Connections" describing where strategies intersect \
— which initiatives or actors span multiple strategies, where work in one strategy \
constrains or enables another. 4–6 sentences.>

Return ONLY the markdown — no preamble, no code fences.
"""


def build_digest_narrative(strategies_data: dict) -> str:
    """LLM call: produce the cross-strategy narrative section of digest.md."""
    lines = []
    for slug, info in strategies_data.items():
        s = info["synthesis"]
        lines.append(f"\n### {info['title']} ({slug})")
        lines.append(f"core-initiatives: {', '.join(s.get('core-initiatives', []))}")
        lines.append(f"core-actors: {', '.join(s.get('core-actors', []))}")
        lines.append(f"arc: {s.get('year-over-year-arc', '—')}")
        lines.append(f"open: {'; '.join(s.get('open-questions', []))}")
        lines.append(f"cross-strategy-links: {', '.join(s.get('cross-strategy-links', []))}")

    user_msg = "Strategy summaries:\n" + "\n".join(lines) + "\n\nWrite the narrative now."

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=_DIGEST_NARRATIVE_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[synthesize_wiki] build_digest_narrative failed: {e}")
        return (
            "## Cross-strategy synthesis\n\n"
            "_Narrative generation failed; rerun `synthesize_wiki` to retry._\n"
        )


def assemble_digest(
    narrative: str,
    strategies_data: dict,
    delta: dict,
    run_date: str,
    sources_count: int,
    entity_count: int,
) -> str:
    """Combine narrative + entity map + recent delta into the digest.md body."""
    parts = [
        "---",
        "generated-by: synthesize_wiki",
        f"last-rebuilt: '{run_date}'",
        f"sources-covered: {sources_count}",
        f"entity-count: {entity_count}",
        "---",
        "",
        "# Wiki Digest",
        f"*State of A2Zero knowledge as of {run_date} "
        f"(after {sources_count} ingested sources).*",
        "",
        narrative.strip(),
        "",
        "## Strategy entity map",
        "",
    ]
    for slug, info in strategies_data.items():
        s = info["synthesis"]
        parts.append(f"### [[{slug}|{info['title']}]]")
        if s.get("core-initiatives"):
            inits = ", ".join(f"[[{x}]]" for x in s["core-initiatives"])
            parts.append(f"- **core initiatives:** {inits}")
        if s.get("core-actors"):
            actors = ", ".join(f"[[{x}]]" for x in s["core-actors"])
            parts.append(f"- **core actors:** {actors}")
        parts.append(f"- **arc:** {s.get('year-over-year-arc', '—')}")
        if s.get("open-questions"):
            parts.append(f"- **open:** {'; '.join(s['open-questions'])}")
        if s.get("cross-strategy-links"):
            xs = ", ".join(f"[[{x}]]" for x in s["cross-strategy-links"])
            parts.append(f"- **cross-strategy links:** {xs}")
        parts.append("")

    parts.append("## Recent delta")
    if delta:
        parts.append(f"**Last ingest:** `{delta['source_uuid']}` ({delta['date']}).")
    else:
        parts.append("_No ingest log entries found._")
    parts.append("")

    return "\n".join(parts)


def write_digest(wiki_root: str, content: str) -> str:
    """Write digest.md to vault root. Returns the absolute path."""
    out = Path(wiki_root) / "digest.md"
    out.write_text(content, encoding="utf-8")
    return str(out)


ALL_STRATEGIES = [
    "strategies/strategy-1-renewable-grid",
    "strategies/strategy-2-electrification",
    "strategies/strategy-3-building-efficiency",
    "strategies/strategy-4-vmt-reduction",
    "strategies/strategy-5-materials-waste",
    "strategies/strategy-6-resilience",
    "strategies/strategy-7-engagement",
]


def _read_strategy_title(wiki_root: str, strategy_slug: str) -> str:
    page = Path(wiki_root) / (strategy_slug + ".md")
    if not page.exists():
        return strategy_slug
    fm = _parse_frontmatter(page.read_text(encoding="utf-8"))
    return fm.get("title", strategy_slug)


def _count_entities(wiki_root: str) -> int:
    root = Path(wiki_root)
    return sum(len(list((root / d).glob("*.md"))) for d in _ENTITY_DIRS if (root / d).exists())


def _count_sources(wiki_root: str) -> int:
    sources_dir = Path(wiki_root) / "sources"
    if not sources_dir.exists():
        return 0
    return sum(1 for p in sources_dir.rglob("*.md"))


def synthesize_wiki(
    wiki_root: str,
    strategies: list[str] | None = None,
    digest_only: bool = False,
    aliases_path: str = "registry/entity_aliases.json",
) -> dict:
    """Phase C orchestration: rebuild L1 synthesis sections + write digest.md.

    Args:
        wiki_root: vault root path (typically "wiki").
        strategies: optional list of strategy slugs to rebuild. If None,
            rebuild all 7 strategy pages.
        digest_only: skip L1 rebuild, just regenerate digest.md from existing
            synthesis: blocks.

    Returns:
        dict with keys: `strategies_rebuilt` (list of slugs), `digest_path`.
    """
    import copy
    from datetime import date
    run_date = date.today().isoformat()
    targets = strategies or ALL_STRATEGIES

    strategies_data: dict = {}
    rebuilt: list[str] = []

    for strategy_slug in targets:
        title = _read_strategy_title(wiki_root, strategy_slug)
        entities = gather_strategy_entities(wiki_root, strategy_slug)

        if digest_only:
            # Read existing synthesis from strategy frontmatter rather than rebuilding
            page = Path(wiki_root) / (strategy_slug + ".md")
            if page.exists():
                fm = _parse_frontmatter(page.read_text(encoding="utf-8"))
                synthesis = fm.get("synthesis") or _empty_synthesis()
            else:
                synthesis = _empty_synthesis()
        else:
            synthesis = build_strategy_synthesis(
                strategy_slug=strategy_slug,
                strategy_title=title,
                entities=entities,
            )
            page = Path(wiki_root) / (strategy_slug + ".md")
            if page.exists():
                write_strategy_synthesis(str(page), synthesis, run_date=run_date)
                rebuilt.append(strategy_slug)
            else:
                print(f"[synthesize_wiki] strategy page missing: {page}")

        strategies_data[strategy_slug] = {"title": title, "synthesis": copy.deepcopy(synthesis)}

    narrative = build_digest_narrative(strategies_data=strategies_data)
    delta = extract_recent_delta(str(Path(wiki_root) / "log.md"))

    digest_text = assemble_digest(
        narrative=narrative,
        strategies_data=strategies_data,
        delta=delta,
        run_date=run_date,
        sources_count=_count_sources(wiki_root),
        entity_count=_count_entities(wiki_root),
    )
    digest_path = write_digest(wiki_root=wiki_root, content=digest_text)

    return {
        "strategies_rebuilt": rebuilt,
        "digest_path": digest_path,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="A2Zero wiki synthesis — Phase C of the ingest cycle"
    )
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help="rebuild only this strategy (repeatable). Default: all 7.",
    )
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="skip L1 rebuild; regenerate digest.md from existing synthesis: blocks",
    )
    args = parser.parse_args()

    result = synthesize_wiki(
        wiki_root=args.wiki_root,
        strategies=args.strategies,
        digest_only=args.digest_only,
    )
    print(f"[synthesize_wiki] rebuilt {len(result['strategies_rebuilt'])} strategies")
    print(f"[synthesize_wiki] wrote digest → {result['digest_path']}")
