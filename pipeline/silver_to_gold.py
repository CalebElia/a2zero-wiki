import anthropic
import json
import re
from pathlib import Path
from pipeline.models import validate_quad


QUADS_SYSTEM = """You are a temporal fact extractor for the A2Zero climate wiki.
You receive a section of a Silver-layer Markdown document and extract every atomic
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


def build_quads_prompt(silver_body: str, source_uuid: str) -> str:
    return (
        f"Source UUID: {source_uuid}\n"
        f"Source type: annual-report\n\n"
        f"Document body:\n\n{silver_body}"
    )


def parse_llm_quads_response(raw: str) -> list[dict]:
    # strip markdown code fence if present
    cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        quads = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM response is not valid JSON. Raw response: {raw!r}") from e
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


def extract_quads_from_silver(
    silver_content: str,
    source_uuid: str,
    out_path: str,
) -> list[dict]:
    client = anthropic.Anthropic()
    # strip frontmatter before sending to LLM
    body = re.sub(r"^---\n.*?\n---\n", "", silver_content, flags=re.DOTALL).strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=QUADS_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": build_quads_prompt(body, source_uuid),
            }
        ],
    )
    raw = response.content[0].text
    quads = parse_llm_quads_response(raw)
    append_quads(quads, out_path)
    return quads
