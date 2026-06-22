import anthropic
import json
import re
from pathlib import Path
from pipeline.silver_to_gold import (
    VALID_PAGE_TYPES,
    build_wiki_page,
    write_wiki_page,
    load_existing_body,
    append_to_wiki_page,
    verify_existing_body_unchanged,
)


WIKI_PAGES_SYSTEM = """You are a wiki page generator for the A2Zero climate wiki.
You receive one section of an A2Zero document and generate wiki page specs for
entities mentioned in the section.

Extract page specs for these entity types:

1. COMMITMENT — a specific promise or action the city commits to in the CAP.
   Every numbered CAP Action (### heading) MUST become a commitment page.
   Slug: "commitments/{kebab-action-title}"
   Required frontmatter fields:
     type: commitment
     title: (exact action title from heading)
     made-in: (source UUID)
     made-in-section: "CAP Actions"
     target-year: (e.g. "year1", "year2", "year3" — extract from timeline; use "unspecified" if unclear)
     status: unverified  ← always for CAP actions
     confidence: high    ← always for CAP actions
     fulfilled-in: null
     fulfilled-evidence: null
     tags: [list of 3-6 relevant keywords]
     source-first-seen: (source UUID)
     last-updated: (today's date)

2. INITIATIVE — a program or project the city is implementing.
   Slug: "initiatives/{kebab-program-name}"
   Required frontmatter fields:
     type: initiative
     title: (program name)
     strategy: (e.g. "strategy-1")
     status: committed
     lead-actor: (slug of lead org, e.g. "actors/osi")
     first-seen: (source UUID)
     last-updated: (today's date)
     tags: [list of 3-6 keywords]

3. ACTOR — a person or organization with a named role.
   Only extract actors with a clear role described in this section.
   Slug: "actors/{kebab-name}"
   Required frontmatter fields:
     type: actor
     title: (full name)
     role: (their role in A2Zero)
     organization: (their parent org slug, or null)
     first-seen: (source UUID)
     last-updated: (today's date)
     tags: [list of 3-5 keywords]

4. FUNDING — a specific dollar allocation with a named source.
   Only extract if an amount AND source are both stated.
   Slug: "funding/{kebab-fund-name}"
   Required frontmatter fields:
     type: funding
     title: (descriptive fund name)
     fund-type: ("federal-grant" | "municipal" | "millage" | "private" | "bond")
     amount: (dollar amount as string, e.g. "$3,245,000")
     source: (who provides the money)
     recipients: [list of initiative slugs]
     fiscal-year: (year as string)
     first-seen: (source UUID)
     last-updated: (today's date)
     tags: [list of 3-5 keywords]

RULES:
- Extract ONLY what the text explicitly states — never invent details
- Body prose: 2-4 factual sentences drawn entirely from the section text
- Slugify names: lowercase, hyphens for spaces, drop special chars ("Office of Sustainability and Innovations" → "office-of-sustainability-and-innovations", "DTE Energy" → "dte-energy")
- Exception: use standard acronyms for well-known bodies where the acronym IS the canonical name (e.g. "osi" for the Office of Sustainability and Innovations, "dte" for DTE Energy)
- One page spec per entity — do not duplicate the same entity
- Return [] if no qualifying entities are found in this section

OUTPUT SCHEMA — every element of the returned JSON array must have exactly these four keys:
{
  "page_type": "<commitment|initiative|actor|funding>",
  "slug": "<category/kebab-name>",
  "frontmatter": { <required fields per type listed above> },
  "body": "<2-4 sentence factual prose from section text>"
}
Return ONLY the JSON array. No prose, no markdown fence, no explanation."""


def parse_llm_pages_response(raw: str) -> list[dict]:
    cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned)
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")
    return data


def validate_page_spec(spec: dict) -> list[str]:
    errors = []
    for field in ("page_type", "slug", "frontmatter", "body"):
        if field not in spec:
            errors.append(f"missing required field: {field}")
    if "body" in spec and not spec.get("body"):
        errors.append("body must not be empty")
    if "page_type" in spec and spec["page_type"] not in VALID_PAGE_TYPES:
        errors.append(f"invalid page_type: {spec['page_type']!r} — must be one of {sorted(VALID_PAGE_TYPES)}")
    return errors


def write_or_append_page(spec: dict, wiki_root: str, source_uuid: str):
    slug = spec["slug"]
    page_path = Path(wiki_root) / (slug + ".md")

    if page_path.exists():
        existing_body = load_existing_body(str(page_path))
        new_section = f"\n<!-- source: {source_uuid} -->\n{spec['body']}\n"
        append_to_wiki_page(str(page_path), new_section, source_uuid)
        verify_existing_body_unchanged(str(page_path), existing_body)
    else:
        page = build_wiki_page(
            page_type=spec["page_type"],
            slug=slug,
            frontmatter=spec["frontmatter"],
            body=spec["body"],
        )
        write_wiki_page(page, wiki_root, exist_ok=False)


def extract_wiki_pages_from_chunk(
    chunk_text: str,
    source_uuid: str,
    context_header: str,
    source_type: str,
    wiki_root: str,
    run_date: str,
) -> list[dict]:
    try:
        client = anthropic.Anthropic()
        prompt = (
            f"{context_header}\n\n"
            f"[SECTION CONTENT]\n{chunk_text}\n[END SECTION]\n\n"
            f"Source UUID: {source_uuid}\n"
            f"Source type: {source_type}\n"
            f"Today's date: {run_date}"
        )
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            temperature=0.2,
            system=WIKI_PAGES_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "max_tokens":
            print(f"[pass3] WARNING: response truncated for chunk (max_tokens hit). Chunk skipped.")
            return []
        raw = response.content[0].text
        specs = parse_llm_pages_response(raw)
    except Exception as e:
        print(f"[pass3] WARNING: page extraction failed for chunk: {e}")
        return []

    written = []
    for spec in specs:
        errors = validate_page_spec(spec)
        if errors:
            print(f"[pass3] WARNING: invalid page spec skipped: {errors} — {spec.get('slug', '?')}")
            continue
        try:
            write_or_append_page(spec, wiki_root=wiki_root, source_uuid=source_uuid)
            written.append(spec)
        except Exception as e:
            print(f"[pass3] WARNING: failed to write page {spec.get('slug', '?')}: {e}")

    return written
