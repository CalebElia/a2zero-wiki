import anthropic
import json
import re
import yaml
from pathlib import Path
from pipeline.models import validate_quad, WikiPage


QUADS_SYSTEM = """You are a temporal fact extractor for the A2Zero climate wiki.
You receive a section of a source markdown document and extract every atomic
temporal fact as a JSON array of quads.

Each quad has this exact schema:
{
  "id": "<sha256-hex-16>",           // compute as sha256(subject|relation|object|date)[:16] prefixed with "sha256-"
  "date": "<YYYY or YYYY-MM or YYYY-MM-DD>",
  "date_precision": "<year|month|day>",
  "subject": "<canonical-slug>",     // kebab-case, no spaces
  "relation": "<verb phrase>",       // e.g. "received grant", "leads", "established"
  "object": "<value or canonical-slug>",
  "sources": ["<source_uuid>"],
  "source_types": ["annual-report"],
  "confidence": 2,                   // always 2 for annual-report (Tier 1 source)
  "status": "confirmed",
  "dark_matter": false,
  "topics": [],
  "locations": [],
  "strategies": [],                  // e.g. ["strategy-1"] if mentioned
  "actors": [],                      // canonical slugs of actors involved
  "keywords": [],                    // 3-8 descriptive keywords
  "fund_type": null,                 // "federal-grant" | "municipal" | "millage" | "private" | null
  "commitment_status": null,         // null unless this quad IS a commitment
  "last_updated": "<YYYY-MM-DD>"
}

Rules:
- Extract ALL facts — do not filter by perceived importance
- One fact per quad; do not bundle multiple facts into one object field
- Slugify all entity names: "Missy Stults" → "missy-stults", "OSI" → "osi"
- For strategies, use "strategy-1" through "strategy-7" exactly
- If a date is approximate or a range, use the start year with precision "year"
- dark_matter: set to true only if the document states an outcome with NO mechanism described
- Return ONLY the JSON array, no prose, no markdown fence"""


def build_quads_prompt(source_body: str, source_uuid: str) -> str:
    return (
        f"Source UUID: {source_uuid}\n"
        f"Source type: annual-report\n\n"
        f"Document body:\n\n{source_body}"
    )


def _recover_partial_quad_array(text: str) -> list[dict]:
    """Walk chars tracking brace depth to find all complete top-level objects."""
    start = text.find("[")
    if start == -1:
        return []
    last_complete = -1
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_complete = i
    if last_complete == -1:
        return []
    return json.loads(text[start : last_complete + 1] + "]")


def parse_llm_quads_response(raw: str) -> list[dict]:
    # strip markdown code fence if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        quads = json.loads(cleaned)
    except json.JSONDecodeError:
        quads = _recover_partial_quad_array(cleaned)
        if quads:
            print(f"[quads] WARNING: response was truncated — recovered {len(quads)} complete quads")
        else:
            raise ValueError(f"LLM response is not valid JSON and no quads could be recovered. Raw response: {raw!r}")
    if not isinstance(quads, list):
        raise ValueError(f"LLM response must be a JSON array, got {type(quads).__name__}. Raw: {raw!r}")
    for q in quads:
        errors = validate_quad(q)
        if errors:
            raise ValueError(f"invalid quad: {q}\nerrors: {errors}")
    return quads


def append_quads(quads: list[dict], out_path: str):
    path = Path(out_path)
    existing_ids: set[str] = set()
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    existing_ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    # skip corrupt or incomplete lines (e.g. from interrupted write)
                    pass

    # not safe for concurrent writers — no file lock
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for q in quads:
            if q["id"] not in existing_ids:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")
                existing_ids.add(q["id"])


def extract_quads_from_source(
    source_content: str,
    source_uuid: str,
    out_path: str,
) -> list[dict]:
    client = anthropic.Anthropic()
    # strip frontmatter before sending to LLM
    body = re.sub(r"^---\n.*?\n---\n", "", source_content, flags=re.DOTALL).strip()

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=16384,
        system=QUADS_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": build_quads_prompt(body, source_uuid),
            }
        ],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "max_tokens":
        print(f"[quads] WARNING: response truncated for {source_uuid} — partial recovery will be attempted")

    raw = response.content[0].text
    quads = parse_llm_quads_response(raw)
    append_quads(quads, out_path)
    return quads


VALID_PAGE_TYPES = frozenset({
    # LLM-writable via wiki_writer.py (Pass 2) — chunked leaf-node extraction:
    "initiative", "actor", "funding-event", "technology",
    "location", "meeting", "framing", "political-event", "contradiction",
    # Written by holistic_synthesizer.py (Pass 1) — never by chunked extraction:
    "overview",
    "strategy",
    # Human-curated / post-ingest synthesis only:
    "topic", "synthesis", "mechanism",
})


def build_wiki_page(
    page_type: str,
    slug: str,
    frontmatter: dict,
    body: str,
) -> WikiPage:
    if page_type not in VALID_PAGE_TYPES:
        raise ValueError(f"Invalid page_type {page_type!r}. Must be one of {sorted(VALID_PAGE_TYPES)}")
    return WikiPage(page_type=page_type, slug=slug, frontmatter=frontmatter, body=body)


def write_wiki_page(page: WikiPage, wiki_root: str, exist_ok: bool = False):
    # slug format: "actors/missy-stults" → wiki_root/actors/missy-stults.md
    out_path = Path(wiki_root) / (page.slug + ".md")
    # guard against path traversal
    resolved = out_path.resolve()
    wiki_root_resolved = Path(wiki_root).resolve()
    if not str(resolved).startswith(str(wiki_root_resolved)):
        raise ValueError(f"Slug escapes wiki_root: {page.slug!r}")
    if not exist_ok and out_path.exists():
        raise FileExistsError(f"Wiki page already exists: {out_path}. Use exist_ok=True to overwrite.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.dump(page.frontmatter, allow_unicode=True, default_flow_style=False)
    content = f"---\n{fm_yaml}---\n\n{page.body}\n"
    out_path.write_text(content, encoding="utf-8")


def load_existing_body(page_path: str) -> str:
    content = Path(page_path).read_text(encoding="utf-8")
    m = re.match(r"^---\n.*?\n---\n\n?(.*)", content, re.DOTALL)
    if m:
        return m.group(1)
    return content


def append_to_wiki_page(page_path: str, new_content: str, source_uuid: str):
    path = Path(page_path)
    if not path.exists():
        raise FileNotFoundError(f"Wiki page not found for append: {page_path}")
    content = path.read_text(encoding="utf-8")
    updated = content.rstrip("\n") + "\n" + new_content
    path.write_text(updated, encoding="utf-8")


def verify_existing_body_unchanged(page_path: str, expected_original_body: str):
    if not expected_original_body:
        raise ValueError("expected_original_body must not be empty; call load_existing_body before any LLM append")
    current_body = load_existing_body(page_path)
    if not current_body.startswith(expected_original_body):
        raise ValueError(
            f"existing body was modified in {page_path}.\n"
            f"Expected start:\n{expected_original_body[:200]}\n"
            f"Got start:\n{current_body[:200]}"
        )
