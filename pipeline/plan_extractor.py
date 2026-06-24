import anthropic
import json
import re
from pathlib import Path
from pipeline.silver_to_gold import build_wiki_page, write_wiki_page

PLAN_EXTRACTION_SYSTEM = """You are a wiki page generator for the A2Zero climate wiki.
You receive the introductory section of a strategic planning document and generate
a single "plan" wiki page spec as a JSON object.

WIKILINK FORMAT — use everywhere:
- Source citation in body: ([[{silver_path}|{source_uuid}]])  ← use values from user message
- Entity refs in frontmatter: "[[actors/osi]]", "[[strategies/strategy-1-renewable-grid]]"
- Source field: "[[{silver_path}]]"  ← just the path, no display text

A2ZERO STRATEGY SLUGS (use exactly these in the strategies list):
  [[strategies/strategy-1-renewable-grid]]
  [[strategies/strategy-2-electrification]]
  [[strategies/strategy-3-building-efficiency]]
  [[strategies/strategy-4-vmt-reduction]]
  [[strategies/strategy-5-materials-waste]]
  [[strategies/strategy-6-resilience]]
  [[strategies/strategy-7-engagement]]

OUTPUT: Return a single JSON object with exactly these four keys:
{
  "page_type": "plan",
  "slug": "plans/{source_uuid}",
  "frontmatter": {
    "type": "plan",
    "title": "(exact document title)",
    "published": "(YYYY-MM or YYYY)",
    "jurisdiction": "(city slug, e.g. 'ann-arbor')",
    "source": "[[{silver_path}]]",
    "overarching-goal": "(1-sentence goal statement from the document)",
    "party-responsible": "[[actors/{slug}]]",
    "strategies": ["[[strategies/strategy-1-renewable-grid]]", ... all 7 if present],
    "tags": [3-6 keywords],
    "last-updated": "(today's date YYYY-MM-DD)"
  },
  "body": "4-6 sentences covering: what this plan is and its goal, how it was created, who is responsible, and its core structure. Every factual sentence ends with ([[{silver_path}|{source_uuid}]])."
}
Return ONLY the JSON object. No prose, no markdown fence, no explanation."""

# Number of body lines to send — enough to cover the intro/overview section.
_PLAN_INTRO_LINES = 200


def extract_plan_page(
    silver_content: str,
    source_uuid: str,
    source_rel_path: str,
    wiki_root: str,
    run_date: str,
) -> dict | None:
    """Extract a plan page from the intro section of a silver document.

    Idempotent: returns None without calling the API if the plan page already exists.
    Returns the page spec dict on success, None on failure or skip.
    """
    plan_slug = f"plans/{source_uuid}"
    plan_path = Path(wiki_root) / (plan_slug + ".md")
    if plan_path.exists():
        print(f"[plan_extractor] Plan page already exists: {plan_path} — skipping")
        return None

    body = re.sub(r"^---\n.*?\n---\n", "", silver_content, flags=re.DOTALL).strip()
    intro = "\n".join(body.splitlines()[:_PLAN_INTRO_LINES])

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            temperature=0,
            system=PLAN_EXTRACTION_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Source UUID: {source_uuid}\n"
                    f"Source path: {source_rel_path}\n"
                    f"Today's date: {run_date}\n\n"
                    f"[DOCUMENT INTRO]\n{intro}\n[END INTRO]"
                ),
            }],
        )
    except Exception as e:
        print(f"[plan_extractor] WARNING: plan extraction failed for {source_uuid}: {e}")
        return None

    raw = response.content[0].text
    cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        spec = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[plan_extractor] WARNING: invalid JSON from LLM for {source_uuid}: {e}")
        return None

    if spec.get("page_type") != "plan":
        print(
            f"[plan_extractor] WARNING: expected page_type 'plan', "
            f"got {spec.get('page_type')!r} — skipping"
        )
        return None

    try:
        page = build_wiki_page(
            page_type="plan",
            slug=plan_slug,
            frontmatter=spec["frontmatter"],
            body=spec["body"],
        )
        write_wiki_page(page, wiki_root=wiki_root, exist_ok=False)
        print(f"[plan_extractor] Plan page written: {plan_path}")
    except Exception as e:
        print(f"[plan_extractor] WARNING: failed to write plan page: {e}")
        return None

    return spec
