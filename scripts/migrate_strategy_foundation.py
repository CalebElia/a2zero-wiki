"""One-time migration: build Foundation sections directly from cap-2020.md
(the sole source of truth for original design intent), and split each
strategy page into Foundation (new) + Progress Synthesis (current body,
preserved as the Year 1-3 starting point for Pass 1B's next regeneration).

Run once. Not part of the ongoing pipeline. See
docs/architecture/strategy-foundation-progression.md for rationale.
"""
import re
from pathlib import Path

from pipeline._llm import chat

WIKI_ROOT = Path("wiki")
CAP_2020_PATH = WIKI_ROOT / "sources" / "cap" / "cap-2020.md"

# (strategy_slug, cap_2020_start_line, cap_2020_end_line) — 1-indexed, inclusive
SECTIONS = [
    ("strategies/strategy-1-renewable-grid", 407, 744),
    ("strategies/strategy-2-electrification", 745, 1241),
    ("strategies/strategy-3-building-efficiency", 1242, 2039),
    ("strategies/strategy-4-vmt-reduction", 2040, 2637),
    ("strategies/strategy-5-materials-waste", 2638, 3023),
    ("strategies/strategy-6-resilience", 3024, 3471),
    ("strategies/strategy-7-engagement", 3472, 3845),  # "Other Actions" through end
]

_FOUNDATION_SYSTEM = """You extract ONLY explicitly-stated facts from a section of \
Ann Arbor's CAP-2020 carbon neutrality plan, to build a frozen "Foundation" \
reference for one strategy. This will never be regenerated after this run — \
accuracy matters more than completeness.

Return 2-4 sentences of prose covering, if and only if stated in the text:
- The combined GHG emissions reduction target and cost estimate (quote numbers
  and the page citation exactly as written, e.g. "41%" and "$4,100,000 [Source: Page 21]")
- The dominant mechanism or policy tool (e.g. Community Choice Aggregation)
- The named actions/initiatives this strategy comprises

If the section contains NO quantified target (this is expected and correct for
some sections — e.g. cross-cutting "Other Actions" content), do not invent one.
Say so plainly: "This section has no quantified emissions or cost target in
CAP-2020; it covers [describe the actual content]."

Cite the source inline: ([[sources/cap/cap-2020|cap-2020]])
Return ONLY the prose. No preamble, no headers, no bullet points.
"""


def extract_foundation(strategy_slug: str, section_text: str) -> str:
    return chat(
        system=_FOUNDATION_SYSTEM,
        messages=[{"role": "user", "content": section_text}],
        max_tokens=1024,
        model_hint="extraction",
        temperature=0.0,
    ).strip()


def main():
    all_lines = CAP_2020_PATH.read_text(encoding="utf-8").splitlines()

    for slug, start, end in SECTIONS:
        section_text = "\n".join(all_lines[start - 1:end])
        foundation_text = extract_foundation(slug, section_text)

        page_path = WIKI_ROOT / f"{slug}.md"
        current = page_path.read_text(encoding="utf-8")
        fm_match = re.match(r"^(---\n.*?\n---\n)", current, re.DOTALL)
        frontmatter = fm_match.group(1) if fm_match else ""
        current_body = re.sub(r"^---\n.*?\n---\n", "", current, flags=re.DOTALL).strip()

        # Current body becomes the Progress Synthesis starting point — it's
        # real Year-3 narrative, just incomplete. Pass 1B's next ingest
        # (with the always-on Progress Synthesis injection fix already shipped)
        # will extend it properly across all sources.
        new_body = (
            f"## Foundation\n\n{foundation_text}\n\n"
            f"## Progress Synthesis\n\n{current_body}\n"
        )
        page_path.write_text(frontmatter + "\n" + new_body, encoding="utf-8")
        print(f"[migrate] {slug}: Foundation written ({len(foundation_text)} chars)")


if __name__ == "__main__":
    main()
