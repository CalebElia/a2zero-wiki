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

_LOG_ENTRY_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+?)$", re.MULTILINE)


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


ALL_STRATEGIES = [
    "strategies/strategy-1-renewable-grid",
    "strategies/strategy-2-electrification",
    "strategies/strategy-3-building-efficiency",
    "strategies/strategy-4-vmt-reduction",
    "strategies/strategy-5-materials-waste",
    "strategies/strategy-6-resilience",
    "strategies/strategy-7-engagement",
]


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
    raise NotImplementedError("Pending tasks 2-9")


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
