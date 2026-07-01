from pipeline._llm import stream_chat
import json
import re
from pathlib import Path

from pipeline._pages import build_wiki_page, write_wiki_page, append_to_wiki_page
from pipeline.pass3_finalize import append_index_entry, append_log
from pipeline._aliases import load_aliases, resolve_slug, resolve_slug_for_title, fuzzy_resolve_slug_for_title
from pipeline.pass2c_merge import merge_pages as _merge_pages

# Module-level path — overridable in tests via patch("pipeline.pass1b_synthesize.alias_registry_path", ...)
alias_registry_path = "registry/entity_aliases.json"


# ── Constants ─────────────────────────────────────────────────────────────────

_REQUIRED_STRATEGY_SLUGS = frozenset({
    "strategies/strategy-1-renewable-grid",
    "strategies/strategy-2-electrification",
    "strategies/strategy-3-building-efficiency",
    "strategies/strategy-4-vmt-reduction",
    "strategies/strategy-5-materials-waste",
    "strategies/strategy-6-resilience",
    "strategies/strategy-7-engagement",
})


# ── System prompts ────────────────────────────────────────────────────────────

HOLISTIC_WRITER_SYSTEM = """You are a policy intelligence curator building the A2Zero knowledge wiki for the City of Ann Arbor.

You will read an ENTIRE source document and produce a structured JSON first draft.
This is HOLISTIC EDITORIAL UNDERSTANDING, not chunked extraction.

Your output has three parts:
1. An OVERVIEW page — what this document IS (scope, structure, commitments)
2. STRATEGY BODIES — what this document says about each A2Zero strategy (narrative synthesis)
3. A LOG SUMMARY — one sentence describing the ingest

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A2ZERO STRATEGIES — use these exact slugs in strategy_bodies:
  strategies/strategy-1-renewable-grid
  strategies/strategy-2-electrification
  strategies/strategy-3-building-efficiency
  strategies/strategy-4-vmt-reduction
  strategies/strategy-5-materials-waste
  strategies/strategy-6-resilience
  strategies/strategy-7-engagement

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OVERVIEW PAGE RULES:
- type: "overview" (exactly)
- source-type: one of "strategic-plan", "annual-report", "council-transcript", "news", "research"
- source-ref: MUST be a wikilink string "[[sources/<path>]]" — not a plain path
- body: 3-5 paragraphs answering: what is this document, who produced it, when,
  what does it commit to or report, how is its content structured?

STRATEGY BODY RULES:
- Write 2-4 paragraphs of narrative synthesis per strategy
- Write 2-4 paragraphs of PROGRESS SYNTHESIS narrative per strategy — NOT the
  strategy's original design, target, or cost estimate. That content lives in
  a separate, frozen "Foundation" section you never see and never write.
- SYNTHESIZE, do not list: what is the dominant approach? what programs are proposed?
  what are projected GHG reductions or costs? what dependencies exist?
- If the document says little about a strategy, write one honest sentence
- Cite with inline wikilinks: ([[{source_path}|{source_uuid}]])
- REQUIRED — entity wikilinks: Every initiative, actor, organization, location, and technology
  you name MUST be linked using the slug you assigned it in stub_pages.
  Link on FIRST MENTION of each entity; subsequent mentions may be plain text.
  Example: "the Solarize program ([[initiatives/solarize-ann-arbor]]) installed..."
  Example: "[[actors/office-of-sustainability-and-innovations|OSI]] led outreach..."
  Do NOT name an entity in strategy bodies without linking it.
- Include all 7 strategy slugs in strategy_bodies, even if coverage is thin
- Your response body is PLAIN PROSE ONLY — never emit a markdown heading (a line
  starting with "##") inside strategy_bodies[].body. The pipeline adds section
  headers itself; a heading in your output will be rejected by validation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
READ-UNDERSTAND-INTEGRATE (applies when EXISTING PROGRESS SYNTHESIS is provided):
The section [EXISTING PROGRESS SYNTHESIS] below contains the FULL prior progress
narrative for each strategy, not a summary — preserve every fact in it verbatim
or near-verbatim, add new depth from THIS source, and do not duplicate paragraphs
that already say the same thing. Your output REPLACES the existing Progress
Synthesis, so it must be complete: a reader who has not seen the prior version
should find it fully coherent.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROJECTIONS AND OUTCOMES:
When this source contains quantitative targets or projections for a strategy or
initiative (e.g. "Strategy 1 will contribute 40% of A2Zero reductions by 2030"),
surface them explicitly in the strategy body prose and mark them clearly:
  "Projected: [figure and timeframe] ([[{source_path}|{source_uuid}]])"
When this source contains measured results or reported progress
(e.g. "As of 2022, Strategy 1 has achieved X% of its target"), mark them:
  "Outcome as of [date]: [figure] ([[{source_path}|{source_uuid}]])"
The pipeline will extract these into structured frontmatter. Clear labeling in
prose is required for the Editor to extract them correctly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WIKILINK FORMAT:
  In YAML frontmatter: quoted string   "[[path/slug]]"
  In body prose:       bare wikilink   [[path/slug]] or [[path/slug|display text]]
  Inline citation:     ([[{source_path}|{source_uuid}]])

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT: A single JSON object — no markdown fence, no prose outside the JSON:
{{
  "overview": {{
    "slug": "overviews/{source_uuid}",
    "frontmatter": {{
      "type": "overview",
      "title": "<descriptive title of the document>",
      "source-type": "<strategic-plan|annual-report|council-transcript|news|research>",
      "source-ref": "[[{source_path}]]",
      "date": "<YYYY or YYYY-MM>",
      "scope": "<community-wide|city-only|neighborhood|other>",
      "tags": ["<tag1>", "<tag2>"],
      "source-first-seen": "[[{source_path}]]",
      "last-updated": "{run_date}"
    }},
    "body": "<3-5 paragraphs of synthesis prose>"
  }},
  "strategy_bodies": [
    {{"slug": "strategies/strategy-1-renewable-grid", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-2-electrification", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-3-building-efficiency", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-4-vmt-reduction", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-5-materials-waste", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-6-resilience", "body": "<2-4 paragraphs>"}},
    {{"slug": "strategies/strategy-7-engagement", "body": "<2-4 paragraphs>"}}
  ],
  "stub_pages": [
    {{
      "type": "<initiative|actor|location|meeting|political-event|technology>",
      "title": "<entity name>",
      "slug": "<type-plural>/<kebab-slug>",
      "parent-strategy": "<strategies/slug or null>",
      "one-liner": "<one sentence description>"
    }}
  ],
  "topic_candidates": [
    {{
      "title": "<cross-cutting topic name>",
      "rationale": "<why this topic spans multiple strategies or sources>"
    }}
  ],
  "log_summary": "<one sentence: what was ingested and what it covers>"
}}

STUB PAGES RULES:
- Include 20-50 entities you are confident are worth tracking over time
- Threshold: proper name + (named org OR budget/timeline OR implies future tracking)
- When uncertain, include — a missed entity is worse than a thin stub
- Do NOT include one-off mentions with no forward continuity
- Prefer these types for stubs: initiative, actor (for major orgs only)

TOPIC CANDIDATES RULES:
- Include 2-8 cross-cutting themes that appear across multiple strategies or sections
- Only surface themes a human analyst would find genuinely useful to track
- Do NOT include topics that are simply strategy titles"""


HOLISTIC_EVALUATOR_SYSTEM = """You are a rigorous editorial reviewer for the A2Zero knowledge wiki.

You will receive:
1. A full source document
2. A writer's draft synthesis (JSON) of that document

Your job: evaluate the draft for accuracy, completeness, format correctness, and redundancy.
Be specific — quote the draft text you're critiquing and the source text that contradicts or extends it.

A2ZERO STRATEGIES — the 7 valid strategy slugs:
  strategy-1-renewable-grid, strategy-2-electrification, strategy-3-building-efficiency,
  strategy-4-vmt-reduction, strategy-5-materials-waste, strategy-6-resilience, strategy-7-engagement

WHAT TO CHECK:
1. ACCURACY: Are all claims in the draft supported by the source? Flag hallucinations or misattributions.
2. COMPLETENESS: Did the writer miss significant sections, numbers, programs, or commitments?
3. FORMAT: Is source-ref in "[[sources/...]]" wikilink format? Are strategy slugs from the allowed list?
4. REDUNDANCY: Do strategy bodies repeat each other or duplicate overview content?

OUTPUT: A single JSON object — no markdown fence, no prose outside the JSON:
{{
  "accuracy_issues": ["<draft claim not supported by source — quote both>", ...],
  "completeness_gaps": ["<fact or section from source missing from draft>", ...],
  "format_issues": ["<specific format problem with exact location>", ...],
  "redundancy_issues": ["<specific repeated content — name the strategy bodies>", ...],
  "overall_score": <integer 1-10, where 10 = no issues>,
  "proceed_to_edit": <true if score >= 4 and draft is worth editing; false if too poor to salvage>
}}

If no issues in a category, return an empty array [].
overall_score >= 7: minor cleanup needed. 4-6: significant gaps. < 4: fundamental problems."""


HOLISTIC_EDITOR_SYSTEM = """You are the final editor for the A2Zero knowledge wiki.

You will receive:
1. A full source document
2. A writer's draft synthesis (JSON)
3. An evaluator's critique (JSON listing accuracy issues, gaps, format problems, and redundancies)

Your job: produce a FINAL, REVISED synthesis that addresses every issue the evaluator identified.

RULES:
- Fix every issue listed by the evaluator (accuracy, completeness, format, redundancy)
- Do NOT invent content not present in the source document — fix, don't fabricate
- Do NOT carry forward hallucinations from the draft — check each claim against the source
- Maintain the exact same JSON schema as the writer draft
- source-ref MUST be a wikilink: "[[sources/<path>]]"
- Strategy slugs must match exactly: strategy-1-renewable-grid through strategy-7-engagement
- Inline citations: ([[sources/<path>|<uuid>]])
- Include all 7 strategy slugs in strategy_bodies

OUTPUT: A single JSON object with the SAME SCHEMA as the writer draft — no markdown fence, no prose:
{{
  "overview": {{
    "slug": "overviews/<source-uuid>",
    "frontmatter": {{ ... }},
    "body": "<3-5 paragraphs>"
  }},
  "strategy_bodies": [
    {{"slug": "strategies/strategy-1-renewable-grid", "body": "<revised 2-4 paragraphs>"}},
    ... (all 7 strategies) ...
  ],
  "log_summary": "<one sentence>"
}}"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm_call(
    system: str,
    user_content: "str | list",
    step_name: str,
    source_uuid: str,
    max_tokens: int = 64000,
) -> dict | None:
    """Single LLM call with JSON parsing. Returns parsed dict or None on failure."""
    try:
        raw = stream_chat(
            system=system,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            model_hint="synthesis",
            temperature=0.0,
        )
        if raw is None:
            print(f"[holistic:{step_name}] WARNING: response truncated for {source_uuid}")
            return None
        cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```$", "", cleaned)
        result = json.loads(cleaned)
        return result
    except Exception as e:
        print(f"[holistic:{step_name}] WARNING: call failed for {source_uuid}: {e}")
        return None


def _validate_synthesis_output(
    result: dict,
    source_uuid: str,
    wiki_root: str,
) -> list[str]:
    """Structural validation of synthesis JSON before any disk writes."""
    errors: list[str] = []

    overview = result.get("overview")
    if not overview:
        errors.append("missing 'overview' key in output")
        return errors

    slug = overview.get("slug", "")
    if not slug.startswith("overviews/"):
        errors.append(f"overview.slug must start with 'overviews/', got: {slug!r}")

    fm = overview.get("frontmatter") or {}
    for required in ("type", "title", "source-ref"):
        if not fm.get(required):
            errors.append(f"overview.frontmatter.{required!r} is missing or empty")

    if fm.get("type") != "overview":
        errors.append(f"overview.frontmatter.type must be 'overview', got: {fm.get('type')!r}")

    source_ref = fm.get("source-ref", "")
    if source_ref and not re.match(r"^\[\[sources/.+\]\]$", source_ref):
        errors.append(
            f"overview.frontmatter.source-ref must be a [[sources/...]] wikilink, "
            f"got: {source_ref!r}"
        )

    if not overview.get("body", "").strip():
        errors.append("overview.body is empty")

    existing_slugs = frozenset(
        f"strategies/{p.stem}"
        for p in (Path(wiki_root) / "strategies").glob("*.md")
    )
    for sb in result.get("strategy_bodies", []):
        s = sb.get("slug", "")
        if not s.startswith("strategies/"):
            errors.append(f"strategy_bodies slug must start with 'strategies/', got: {s!r}")
        elif s not in existing_slugs:
            errors.append(
                f"strategy_bodies slug {s!r} has no matching stub in wiki/strategies/ "
                f"— valid slugs: {sorted(existing_slugs)}"
            )
        if not sb.get("body", "").strip():
            errors.append(f"strategy_bodies body is empty for slug: {s!r}")
        if re.search(r"^##\s", sb.get("body", ""), re.MULTILINE):
            errors.append(
                f"strategy_bodies body for {s!r} contains a markdown heading — "
                f"the LLM must return plain prose only; headers are added by the pipeline"
            )

    returned_slugs = {sb.get("slug") for sb in result.get("strategy_bodies", [])}
    for missing in sorted(_REQUIRED_STRATEGY_SLUGS - returned_slugs):
        errors.append(f"strategy_bodies missing required slug: {missing!r}")

    return errors


# ── Main entry point ──────────────────────────────────────────────────────────

def synthesize_source(
    source_content: str,
    source_uuid: str,
    source_rel_path: str,
    source_type: str,
    wiki_root: str,
    run_date: str,
    max_retries: int = 2,
    integration_plan: dict | None = None,
    digest_content: str | None = None,
) -> dict | None:
    """Pass 1 — Writer → Evaluator → Editor holistic synthesis."""
    overview_path = Path(wiki_root) / "overviews" / f"{source_uuid}.md"
    if overview_path.exists():
        print(f"[holistic] Overview already exists: {overview_path} — skipping")
        return None

    doc_body = re.sub(r"^---\n.*?\n---\n", "", source_content, flags=re.DOTALL).strip()

    # Build the integration block from the digest + integration plan (preferred).
    # Falls back to raw strategy bodies if no digest is available (first-ingest path).
    integration_block = ""
    if digest_content or integration_plan:
        lines = [
            "\n\n[INTEGRATION PLAN — read this first]",
            "The Comprehend pass has produced a structured plan for how this source",
            "should be integrated. Use it to guide which strategies to extend, which",
            "entities to update vs. create, and which existing content to preserve.\n",
            json.dumps(integration_plan or {}, indent=2),
            "[END INTEGRATION PLAN]\n",
        ]
        if digest_content:
            lines.extend([
                "\n[WIKI DIGEST — current state of the wiki]",
                "READ-UNDERSTAND-INTEGRATE: this digest reflects what the wiki already",
                "knows. Build on it rather than re-stating known facts.\n",
                digest_content,
                "[END WIKI DIGEST]",
            ])
        integration_block = "\n".join(lines)

    # Always inject full existing Progress Synthesis text — regardless of
    # whether a digest exists. The digest is cross-strategy narrative context;
    # this is the actual full-fidelity source of truth for what NOT to lose.
    # Token-budget note: this grows linearly (not exponentially) with the
    # number of ingested sources — safe through at least Year 5-10 at current
    # per-strategy Progress Synthesis lengths. If the wiki scales well beyond
    # that, revisit (e.g. summarize older years, cap per-strategy injection
    # size). See docs/architecture/2026-06-30-content-quality-audit.md.
    existing_progress: dict[str, str] = {}
    strategies_dir = Path(wiki_root) / "strategies"
    if strategies_dir.exists():
        for strat_file in sorted(strategies_dir.glob("*.md")):
            content = strat_file.read_text(encoding="utf-8")
            body = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL).strip()
            _, progress = _split_strategy_sections(body)
            if progress and re.sub(r"<!--.*?-->", "", progress, flags=re.DOTALL).strip():
                existing_progress[f"strategies/{strat_file.stem}"] = progress

    if existing_progress:
        prog_lines = [
            "\n\n[EXISTING PROGRESS SYNTHESIS — every strategy]",
            "READ-UNDERSTAND-INTEGRATE: this is the FULL prior Progress Synthesis text",
            "for each strategy, not a summary. Preserve every fact in it. Add new depth",
            "from THIS source. Do not discard anything. The Foundation section (not",
            "shown here, and NOT yours to write) already holds each strategy's original",
            "design intent — your job is only to extend the progress narrative.\n",
        ]
        for slug, text in sorted(existing_progress.items()):
            prog_lines.append(f"--- {slug} ---\n{text}\n")
        prog_lines.append("[END EXISTING PROGRESS SYNTHESIS]")
        integration_block += "\n".join(prog_lines)

    document_block_text = (
        f"Source UUID: {source_uuid}\n"
        f"Source path: {source_rel_path}\n"
        f"Source type: {source_type}\n"
        f"Today's date: {run_date}\n\n"
        f"[FULL DOCUMENT]\n{doc_body}\n[END DOCUMENT]"
        + integration_block
    )
    cached_document_block = {
        "type": "text",
        "text": document_block_text,
        "cache_control": {"type": "ephemeral"},
    }

    writer_system = HOLISTIC_WRITER_SYSTEM.format(
        source_uuid=source_uuid,
        source_path=source_rel_path,
        run_date=run_date,
    )

    # ── Step 1: Writer ────────────────────────────────────────────────────────
    print(f"[holistic:writer] {source_uuid}")
    draft = _llm_call(
        writer_system,
        [cached_document_block],
        "writer", source_uuid, max_tokens=64000,
    )
    if draft is None:
        print(f"[holistic] ERROR: writer call failed for {source_uuid}")
        return None

    # ── Step 2: Evaluator ─────────────────────────────────────────────────────
    print(f"[holistic:evaluator] {source_uuid}")
    eval_content = [
        cached_document_block,
        {"type": "text", "text": "\n\n[WRITER DRAFT]\n" + json.dumps(draft, indent=2) + "\n[END DRAFT]"},
    ]
    critique = _llm_call(
        HOLISTIC_EVALUATOR_SYSTEM, eval_content,
        "evaluator", source_uuid, max_tokens=64000,
    )

    if critique is None or not critique.get("proceed_to_edit", True):
        score = (critique or {}).get("overall_score", "?")
        accuracy_issues = (critique or {}).get("accuracy_issues", [])
        print(f"[holistic:evaluator] Low quality score ({score}) — re-running writer with feedback")
        retry_suffix = (
            "\n\nIMPORTANT: A previous draft was rejected for low quality. "
            "Take extra care to be accurate, complete, and correctly formatted."
        )
        if accuracy_issues:
            retry_suffix += "\n\nSpecific accuracy problems to avoid:\n" + "\n".join(
                f"- {i}" for i in accuracy_issues
            )
        retry_content = [
            cached_document_block,
            {"type": "text", "text": retry_suffix},
        ]
        draft = _llm_call(
            writer_system, retry_content,
            "writer-retry", source_uuid, max_tokens=64000,
        )
        if draft is None:
            print(f"[holistic] ERROR: writer retry failed for {source_uuid}")
            return None
        critique = {}

    # ── Step 3: Editor (with structural validation retry) ─────────────────────
    editor_content = [
        cached_document_block,
        {"type": "text", "text": (
            "\n\n[WRITER DRAFT]\n" + json.dumps(draft, indent=2) + "\n[END DRAFT]"
            + "\n\n[EVALUATOR CRITIQUE]\n" + json.dumps(critique, indent=2) + "\n[END CRITIQUE]"
        )},
    ]

    for attempt in range(max_retries + 1):
        print(f"[holistic:editor] {source_uuid} attempt {attempt + 1}")
        final = _llm_call(
            HOLISTIC_EDITOR_SYSTEM, editor_content,
            f"editor-{attempt}", source_uuid, max_tokens=64000,
        )
        if final is None:
            continue

        errors = _validate_synthesis_output(final, source_uuid=source_uuid, wiki_root=wiki_root)
        if not errors:
            _write_synthesis(final, wiki_root=wiki_root, source_uuid=source_uuid, source_rel_path=source_rel_path, run_date=run_date)
            return final

        print(f"[holistic:editor] Validation failed (attempt {attempt + 1}): {errors}")
        editor_content[-1]["text"] += (
            "\n\nYOUR PREVIOUS RESPONSE FAILED STRUCTURAL VALIDATION. Fix these errors:\n"
            + "\n".join(f"- {e}" for e in errors)
        )

    print(f"[holistic] ERROR: editor failed after {max_retries + 1} attempts for {source_uuid}")
    return None


def _replace_wiki_page_body(page_path: str, new_body: str) -> None:
    """Replace the body section of a wiki page, preserving frontmatter intact."""
    content = Path(page_path).read_text(encoding="utf-8")
    m = re.match(r"^(---\n.*?\n---\n)", content, re.DOTALL)
    frontmatter = m.group(1) if m else ""
    Path(page_path).write_text(frontmatter + "\n" + new_body.strip() + "\n", encoding="utf-8")


def _split_strategy_sections(body: str) -> tuple[str | None, str | None]:
    """Return (foundation_text, progress_text). Either is None if the page
    predates the split (legacy single-body page) or the section is absent."""
    fm = re.search(
        r"^##\s*Foundation\s*\n(.*?)(?=^##\s*Progress Synthesis\s*\n|\Z)",
        body, re.DOTALL | re.MULTILINE,
    )
    pm = re.search(r"^##\s*Progress Synthesis\s*\n(.*)\Z", body, re.DOTALL | re.MULTILINE)
    if not fm or not pm:
        return None, None
    return fm.group(1).strip(), pm.group(1).strip()


def _assemble_strategy_body(foundation: str, progress: str) -> str:
    return f"## Foundation\n\n{foundation}\n\n## Progress Synthesis\n\n{progress}\n"


def _write_synthesis(
    result: dict,
    wiki_root: str,
    source_uuid: str,
    source_rel_path: str,
    run_date: str,
) -> None:
    """Write validated synthesis to disk. Only called after _validate_synthesis_output passes."""
    ov = result["overview"]
    fm = dict(ov["frontmatter"])
    fm["last-updated"] = run_date

    page = build_wiki_page(
        page_type="overview",
        slug=ov["slug"],
        frontmatter=fm,
        body=ov["body"],
    )
    write_wiki_page(page, wiki_root=wiki_root, exist_ok=False)
    print(f"[holistic] Overview written: wiki/{ov['slug']}.md")

    append_index_entry(
        wiki_root=wiki_root,
        page_type="overview",
        slug=ov["slug"],
        title=fm.get("title", source_uuid),
        summary=fm.get("source-type", ""),
    )

    for sb in result.get("strategy_bodies", []):
        strat_path = Path(wiki_root) / (sb["slug"] + ".md")
        if not strat_path.exists():
            print(f"[holistic] WARNING: strategy stub missing: {strat_path} — skipping")
            continue
        existing = strat_path.read_text(encoding="utf-8")
        existing_body = re.sub(r"^---\n.*?\n---\n", "", existing, flags=re.DOTALL).strip()
        foundation, _ = _split_strategy_sections(existing_body)

        if foundation is None:
            raise RuntimeError(
                f"{strat_path} has no Foundation section. Run the one-time "
                f"Foundation migration (docs/architecture/strategy-foundation-progression.md) "
                f"before ingesting further sources."
            )

        new_body = _assemble_strategy_body(foundation, sb["body"])
        _replace_wiki_page_body(str(strat_path), new_body)
        print(f"[holistic] Progress Synthesis updated: {strat_path.name}")

    aliases = load_aliases(alias_registry_path)

    stubs_written = 0
    for sp in result.get("stub_pages", []):
        stub_slug = sp.get("slug", "")
        if not stub_slug:
            continue

        # Pass 1.5: resolve through alias registry before writing
        bare_key = stub_slug.split("/")[-1]  # "actors/office-of-sustainability" → "office-of-sustainability"
        title_hint = sp.get("title", "")
        canonical_path = (
            resolve_slug(bare_key, aliases)
            or resolve_slug_for_title(title_hint, aliases)
            or fuzzy_resolve_slug_for_title(title_hint, aliases)
        )
        if canonical_path:
            effective_slug = canonical_path
            print(f"[holistic:pass1.5] {stub_slug!r} → canonical {canonical_path!r}")
        else:
            effective_slug = stub_slug

        stub_path = Path(wiki_root) / (effective_slug + ".md")
        if stub_path.exists():
            existing = stub_path.read_text(encoding="utf-8")
            existing_body = re.sub(r"^---\n.*?\n---\n", "", existing, flags=re.DOTALL).strip()
            if re.sub(r"<!--.*?-->", "", existing_body, flags=re.DOTALL).strip():
                # Canonical page has real content — merge stub one-liner context in
                one_liner = sp.get("one-liner", "")
                if one_liner:
                    merged = _merge_pages(
                        canonical_slug=effective_slug,
                        existing_body=existing_body,
                        new_body=one_liner,
                        source_uuid=source_uuid,
                    )
                    _replace_wiki_page_body(str(stub_path), merged)
                    print(f"[holistic:pass1.5] Merged one-liner into existing {effective_slug}")
            continue  # canonical stub or real page already exists — skip creation

        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_fm = {
            "type": sp.get("type", "initiative"),
            "title": sp.get("title", ""),
            "source-first-seen": f"[[{source_rel_path}]]",
            "last-updated": run_date,
        }
        if sp.get("parent-strategy"):
            stub_fm["parent-strategy"] = sp["parent-strategy"]
        if sp.get("type") in ("initiative", "strategy"):
            stub_fm["projections"] = []
            stub_fm["outcomes"] = []
        stub_page = build_wiki_page(
            page_type=sp.get("type", "initiative"),
            slug=effective_slug,
            frontmatter=stub_fm,
            body=f"<!-- stub from Pass 1 holistic read ({source_uuid}) — {sp.get('one-liner', '')} -->",
        )
        write_wiki_page(stub_page, wiki_root=wiki_root, exist_ok=False)
        stubs_written += 1
    if stubs_written:
        print(f"[holistic] {stubs_written} stub pages created for Pass 2")

    candidates = result.get("topic_candidates", [])
    if candidates:
        meta_dir = Path(wiki_root) / "meta"
        meta_dir.mkdir(exist_ok=True)
        candidates_path = meta_dir / "topic-candidates.md"
        with candidates_path.open("a", encoding="utf-8") as f:
            for tc in candidates:
                f.write(
                    f"\n## {tc.get('title', 'Unknown')} | Source: {source_uuid} | {run_date}\n"
                    f"Rationale: {tc.get('rationale', '')}\n"
                    f"Resolution: [ ] Promote to wiki/topics/  [ ] Dismiss\n"
                )
        print(f"[holistic] {len(candidates)} topic candidates written to wiki/meta/topic-candidates.md")

    log_parts = [result.get("log_summary", f"Ingested {source_uuid}.")]
    log_parts.append(
        f"Pass 1: Writer→Evaluator→Editor complete. "
        f"{len(result.get('stub_pages', []))} stubs, "
        f"{len(candidates)} topic candidates."
    )
    append_log(
        wiki_root=wiki_root,
        message="\n".join(log_parts),
        source_uuid=source_uuid,
        run_date=run_date,
    )
