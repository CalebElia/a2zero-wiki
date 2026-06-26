# pipeline/merge_pages.py
import anthropic

MERGE_SYSTEM = """You are integrating two wiki page bodies into one unified page body.

Rules:
- Preserve ALL factual claims from BOTH versions with their inline wikilink citations
- Do NOT duplicate paragraphs that already make the same point
- Produce a single coherent body a reader would find complete — not two sections stapled together
- Maintain the same wikilink citation format: ([[sources/path|uuid]])
- Output ONLY the merged body text — no frontmatter, no headings above the body, no preamble
"""


def merge_pages(
    canonical_slug: str,
    existing_body: str,
    new_body: str,
    source_uuid: str,
    model: str = "claude-sonnet-4-6",
) -> str:
    """Merge new_body into existing_body for the canonical page.

    Returns the merged body string. On any failure, returns existing_body unchanged
    so content is never silently lost.
    """
    prompt = (
        f"Canonical page: {canonical_slug}\n\n"
        f"[EXISTING BODY]\n{existing_body.strip()}\n[END EXISTING]\n\n"
        f"[NEW CONTENT from {source_uuid}]\n{new_body.strip()}\n[END NEW]\n\n"
        "Produce the unified body."
    )
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            temperature=0,
            system=MERGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "max_tokens":
            print(f"[merge_pages] WARNING: response truncated for {canonical_slug} — keeping existing body")
            return existing_body
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[merge_pages] WARNING: merge failed for {canonical_slug}: {e} — keeping existing body")
        return existing_body
