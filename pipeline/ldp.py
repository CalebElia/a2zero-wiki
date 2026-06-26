import anthropic
import json
import re
from pathlib import Path
from pipeline.silver_to_gold import (
    parse_llm_quads_response,
    append_quads,
)

# CAP-specific override: source_type is "cap", actions are unverified commitments
CAP_QUADS_SYSTEM = """You are a temporal fact extractor for the A2Zero climate wiki.
You receive one section of the A2Zero Climate Action Plan (CAP, 2020) and extract
every atomic temporal fact as a JSON array of quads.

The CAP is a planning document written in 2020. It describes what the City of Ann Arbor
PLANS or COMMITS to do. Most facts are future-oriented commitments, not past events.

Each quad has this exact schema:
{
  "id": "<sha256-hex-16>",
  "date": "<YYYY or YYYY-MM or YYYY-MM-DD>",
  "date_precision": "<year|month|day>",
  "subject": "<canonical-slug>",
  "relation": "<verb phrase>",
  "object": "<value or canonical-slug>",
  "sources": ["cap-2020"],
  "source_types": ["cap"],
  "confidence": 2,
  "status": "confirmed",
  "dark_matter": false,
  "topics": [],
  "locations": [],
  "strategies": [],
  "actors": [],
  "keywords": [],
  "fund_type": null,
  "commitment_status": null,
  "last_updated": "<YYYY-MM-DD>"
}

Rules:
- Extract ALL facts — do not filter by perceived importance
- One fact per quad; do not bundle multiple facts into one object field
- For CAP "Actions" (numbered program actions), set commitment_status: "unverified"
  and use relation: "committed to" or "planned to implement"
- For cost estimates and GHG figures, extract as separate quads
- For co-benefits tables, extract key facts (GHG reduction %, cost $/ton)
- For actors, slugify: "Office of Sustainability and Innovations" → "osi"
- For strategies, use "strategy-1" through "strategy-7" exactly
- date: use "2020" with date_precision: "year" for plan-level commitments
  unless a specific year is stated (e.g. "by 2021" → date: "2021")
- Return ONLY the JSON array, no prose, no markdown fence"""


def _strip_frontmatter(content: str) -> tuple[str, int]:
    """Return (body_without_frontmatter, body_start_line_1indexed)."""
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                return "\n".join(lines[i + 1:]), i + 2
    return content, 1


def parse_section_map(source_content: str, document_uuid: str) -> dict:
    """Parse heading structure into a section map using regex (no LLM needed)."""
    lines = source_content.splitlines()
    total_lines = len(lines)

    # find body start (skip frontmatter)
    body_start_idx = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                body_start_idx = i + 1
                break

    sections = []
    # stack entries: {"id", "title", "depth", "line_start", "line_end": None}
    stack = []

    for idx in range(body_start_idx, total_lines):
        line = lines[idx]
        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if not m:
            continue
        depth = len(m.group(1))
        title = m.group(2).strip()
        # remove inline source annotations like [Source: Page 5]
        title = re.sub(r"\s*\[Source:.*?\]", "", title).strip()
        section_id = re.sub(r"[^\w\s-]", "", title.lower())
        section_id = re.sub(r"[\s_]+", "-", section_id).strip("-")

        current_line = idx + 1  # 1-indexed

        # close sections at same or deeper depth
        while stack and stack[-1]["depth"] >= depth:
            closed = stack.pop()
            closed["line_end"] = current_line - 1
            sections.append(closed)

        stack.append({
            "id": section_id,
            "title": title,
            "depth": depth,
            "line_start": current_line,
            "line_end": None,
        })

    # close remaining open sections
    while stack:
        closed = stack.pop()
        closed["line_end"] = total_lines
        sections.append(closed)

    sections.sort(key=lambda s: s["line_start"])

    return {
        "document_uuid": document_uuid,
        "total_lines": total_lines,
        "ldp_version": "1.0",
        "sections": sections,
    }


def save_section_map(section_map: dict, maps_dir: str) -> str:
    uuid = section_map["document_uuid"]
    path = Path(maps_dir) / f"{uuid}_structure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(section_map, indent=2, ensure_ascii=False))
    return str(path)


def get_chunks(section_map: dict) -> list[dict]:
    """Return chunks for LLM extraction at depth 1 and depth 2.

    Depth-2 sections are included as-is (they contain the action-level detail).
    Depth-1 sections are clipped to end just before their first depth-2 child,
    so the LLM only sees the intro prose for that section — not a re-send of all
    descendant content that the depth-2 chunks already cover. If clipping leaves
    no content (heading immediately followed by a child), the depth-1 chunk is
    dropped entirely.
    """
    all_sections = section_map["sections"]
    chunks = []

    for s in all_sections:
        if s["depth"] == 2:
            chunks.append(s)
        elif s["depth"] == 1:
            # Find the first depth-2 child that falls inside this section.
            first_child = next(
                (c for c in all_sections
                 if c["depth"] == 2
                 and s["line_start"] < c["line_start"] <= s["line_end"]),
                None,
            )
            if first_child is None:
                # No depth-2 children — use the full range unchanged.
                chunks.append(s)
            else:
                clipped_end = first_child["line_start"] - 1
                if clipped_end > s["line_start"]:
                    # There is at least one line of prose between the heading
                    # and the first child — worth sending to the LLM.
                    chunks.append({**s, "line_end": clipped_end})
                # else: heading is immediately followed by a child; skip.

    chunks.sort(key=lambda c: c["line_start"])
    return chunks


def build_chunk_context_header(
    document_title: str,
    document_uuid: str,
    section: dict,
    section_index: int,
    total_sections: int,
    parent_title: str | None,
) -> str:
    parent_line = f"Parent section: {parent_title}" if parent_title else ""
    lines = [
        "[DOCUMENT CONTEXT]",
        f"Document: {document_title} [uuid: {document_uuid}]",
        f'You are reading: "{section["title"]}" [section-id: {section["id"]}]',
        f"Position in document: Section {section_index + 1} of {total_sections}",
    ]
    if parent_line:
        lines.append(parent_line)
    lines += ["[END CONTEXT]", ""]
    return "\n".join(lines)


def extract_chunk_lines(all_lines: list[str], line_start: int, line_end: int) -> str:
    """Extract lines by 1-indexed range (inclusive)."""
    return "\n".join(all_lines[line_start - 1: line_end])


def _find_parent_title(section: dict, all_sections: list[dict]) -> str | None:
    """Find the nearest ancestor section at depth - 1."""
    if section["depth"] <= 1:
        return None
    for candidate in reversed(all_sections):
        if (candidate["depth"] == section["depth"] - 1
                and candidate["line_start"] < section["line_start"]):
            return candidate["title"]
    return None


def extract_quads_chunked(
    source_content: str,
    section_map: dict,
    source_uuid: str,
    document_title: str,
    source_rel_path: str = "",
    source_type: str = "cap",
    wiki_root: str = "wiki",
    run_date: str | None = None,
    wiki_only: bool = False,
    quads_only: bool = False,
    entity_context: str = "",
) -> tuple[list[dict], int]:
    """Extract quads and/or wiki pages from all depth-1 and depth-2 chunks.

    wiki_only=True  — skip quad extraction, run only wiki page writes.
    quads_only=True — skip wiki page writes, run only quad extraction.
    Returns a tuple of (all_quads, total_pages_written).
    """
    from datetime import date as _date
    # Function-level import to avoid circular-import risk at module load time.
    from pipeline.wiki_writer import extract_wiki_pages_from_chunk
    from pipeline.alias_registry import load_aliases as _load_aliases

    if run_date is None:
        run_date = _date.today().isoformat()

    all_lines = source_content.splitlines()
    chunks = get_chunks(section_map)
    all_quads: list[dict] = []
    total_pages_written = 0
    aliases = _load_aliases(str(Path(wiki_root).parent / "registry" / "entity_aliases.json"))

    # Only instantiate the quads client when we actually need it.
    client = None if wiki_only else anthropic.Anthropic()
    # Skip alias load when quads_only — wiki_writer never runs.
    if quads_only:
        aliases = {}

    for i, chunk in enumerate(chunks):
        parent_title = _find_parent_title(chunk, section_map["sections"])
        context_header = build_chunk_context_header(
            document_title=document_title,
            document_uuid=source_uuid,
            section=chunk,
            section_index=i,
            total_sections=len(chunks),
            parent_title=parent_title,
        )
        chunk_text = extract_chunk_lines(all_lines, chunk["line_start"], chunk["line_end"])

        if not wiki_only:
            prompt = (
                f"{context_header}\n"
                f"[SECTION CONTENT]\n{chunk_text}\n[END SECTION]\n\n"
                f"Source UUID: {source_uuid}\nToday's date: {run_date}"
            )
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                temperature=0,
                system=CAP_QUADS_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text
            try:
                quads = parse_llm_quads_response(raw)
            except Exception as e:
                print(f"[ldp] WARNING: chunk {i} ({chunk['title']!r}) extraction failed: {e}")
                quads = []
            all_quads.extend(quads)

        # Pass 3: wiki pages — skip when quads_only.
        if quads_only:
            continue
        combined_context = entity_context + context_header if entity_context else context_header
        pages_written = extract_wiki_pages_from_chunk(
            chunk_text=chunk_text,
            source_uuid=source_uuid,
            source_rel_path=source_rel_path,
            context_header=combined_context,
            source_type=source_type,
            wiki_root=wiki_root,
            run_date=run_date,
            aliases=aliases,
        )
        total_pages_written += len(pages_written)

    return (all_quads, total_pages_written)


def run_ldp_ingest(
    source_content: str,
    uuid: str,
    title: str,
    quads_path: str,
    source_rel_path: str = "",
    wiki_root: str = "wiki",
    source_type: str = "cap",
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
    wiki_only: bool = False,
    quads_only: bool = False,
    entity_context: str = "",
):
    """Full LDP pipeline: parse section map → chunked extraction → append quads.

    wiki_only=True  — skip quad extraction; quads_path is untouched.
    quads_only=True — skip wiki page writes; entity_context is ignored.
    entity_context: known-entity block from Pass 1 holistic read, prepended to each chunk header.
    """
    section_map = parse_section_map(source_content, uuid)
    save_section_map(section_map, section_maps_dir)
    mode = "wiki-only" if wiki_only else ("quads-only" if quads_only else "quads+wiki")
    print(f"[ldp] {uuid}: {len(section_map['sections'])} sections, "
          f"{len(get_chunks(section_map))} chunks to extract [{mode}]")
    quads, pages_written = extract_quads_chunked(
        source_content=source_content,
        section_map=section_map,
        source_uuid=uuid,
        document_title=title,
        source_rel_path=source_rel_path,
        source_type=source_type,
        wiki_root=wiki_root,
        run_date=run_date,
        wiki_only=wiki_only,
        quads_only=quads_only,
        entity_context=entity_context,
    )
    if not wiki_only:
        append_quads(quads, quads_path)
    print(f"[ldp] {uuid}: {len(quads)} quads, {pages_written} wiki pages written")
    return quads
