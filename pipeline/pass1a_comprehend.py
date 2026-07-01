"""Pass 1A — Comprehend → Integration Plan.

Reads wiki/digest.md plus the new source, produces a structured integration
plan that guides downstream passes (Writer→Evaluator→Editor + LDP).

See docs/architecture/comprehend-plan-write.md for design rationale.
"""
import json
from pathlib import Path


def empty_plan() -> dict:
    """Return the empty-plan skeleton used as fallback."""
    return {
        "source-uuid": "",
        "generated-at": "",
        "digest-rebuilt": "",
        "strategies-touched": [],
        "extends": [],
        "new-entities": [],
        "retrieve-for-context": [],
        "theme-connections": [],
    }


def write_integration_plan(plan: dict, plans_dir: str) -> str:
    """Write plan JSON to <plans_dir>/<source-uuid>.json. Returns absolute path."""
    out_dir = Path(plans_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{plan['source-uuid']}.json"
    out_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return str(out_path)


def load_integration_plan(plans_dir: str, source_uuid: str) -> dict:
    """Load plan from disk. Returns empty_plan() if file missing (graceful fallback)."""
    path = Path(plans_dir) / f"{source_uuid}.json"
    if not path.exists():
        return empty_plan()
    return json.loads(path.read_text(encoding="utf-8"))


import re
from datetime import datetime, timezone
from pipeline._llm import chat


_COMPREHEND_SYSTEM = """You are the Comprehend pass for the A2Zero knowledge wiki ingest pipeline.

You will receive:
1. The current wiki digest (compressed prior over what the wiki knows)
2. A new source document to be ingested

Your job: produce a structured integration plan that downstream extraction passes will use.

Return ONLY a JSON object with EXACTLY these keys:

- strategies-touched: list of strategy slugs (e.g. "strategies/strategy-1-renewable-grid") \
  that this source meaningfully affects
- extends: list of {slug, new-data} objects for EXISTING entities the source adds new \
  information to. The slug must reference a real entity from the digest. The new-data is \
  a one-sentence hint describing what the source contributes.
- new-entities: list of {slug, type, title, rationale} objects for entities NOT yet in \
  the wiki that the source introduces and that warrant a dedicated page. Type must be one \
  of: actor, initiative, location, technology, funding-event, meeting, political-event. \
  Keep `rationale` to ONE short sentence (under 20 words). Cap the list at 20 entities — \
  prioritize the most significant new entities; the LDP extraction pass will catch the rest.
- retrieve-for-context: list of existing entity slugs whose page bodies should be loaded \
  as reference context during chunk-by-chunk extraction. Include entities in `extends` \
  and any other existing entities the source heavily references. Aim for 5-15 entities.
- theme-connections: list of 2-5 short strings describing cross-strategy patterns this \
  source surfaces (e.g. "Source ties grid capacity to building electrification timeline").

For EXISTING entities (extends, retrieve-for-context): use the exact canonical slugs as they \
appear in the digest's entity map and narrative wikilinks (e.g. `actors/dte-energy`, \
`initiatives/sustainable-energy-utility`). Do not invent slug variants for entities the \
digest already names.

For NEW entities the source introduces that the wiki does not yet know about: actively \
identify and propose them in `new-entities`. Use kebab-case slugs that follow project \
conventions (e.g. `initiatives/electrification-expo-2023`). Do not over-constrain yourself \
to only entities already in the digest — surfacing genuinely new entities is part of \
your job.

Return ONLY the JSON object. No preamble, no code fences, no commentary.
"""


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:-1]) if len(lines) > 2 else t
    return t.strip()


def _repair_json(text: str) -> str:
    """Strip trailing commas before } or ] — catches the most common LLM JSON error."""
    return re.sub(r",\s*([}\]])", r"\1", text)


_REPAIR_SYSTEM = (
    "You are a JSON repair tool. The user will give you malformed JSON. "
    "Return ONLY the corrected JSON object with no preamble, no code fences, no commentary."
)


def _repair_via_llm(raw: str) -> str:
    """Ask the LLM to fix malformed JSON. Used as fallback after parse failure."""
    return chat(
        system=_REPAIR_SYSTEM,
        messages=[{"role": "user", "content": f"Fix this JSON:\n\n{raw}"}],
        max_tokens=4096,
        model_hint="synthesis",
        temperature=0.0,
    )


def _extract_digest_rebuilt(digest_content: str) -> str:
    """Pull the last-rebuilt date from digest frontmatter, or empty string."""
    m = re.search(r"^last-rebuilt:\s*['\"]?(\d{4}-\d{2}-\d{2})", digest_content, re.MULTILINE)
    return m.group(1) if m else ""


def build_integration_plan(
    source_content: str,
    source_uuid: str,
    digest_content: str | None,
    run_date: str,
) -> dict:
    """Comprehend LLM call: read digest + source, produce structured integration plan.

    Two failure modes per spec:
    - No digest (digest_content is None): silent fallback, no LLM call, returns empty plan
      stamped with source-uuid. This is the first-ingest path.
    - Digest present but LLM call fails: HARD FAIL — raises the exception. The caller
      (run_ingest.py) halts the ingest before any downstream tokens are spent.
    """
    plan = empty_plan()
    plan["source-uuid"] = source_uuid
    plan["generated-at"] = datetime.now(timezone.utc).isoformat()

    if digest_content is None:
        # First-ingest fallback: no digest exists yet
        return plan

    plan["digest-rebuilt"] = _extract_digest_rebuilt(digest_content)

    user_msg = (
        f"[WIKI DIGEST]\n{digest_content}\n[END DIGEST]\n\n"
        f"[NEW SOURCE — uuid={source_uuid}, ingest_date={run_date}]\n"
        f"{source_content}\n[END SOURCE]\n\n"
        "Produce the integration plan JSON now."
    )

    raw = chat(
        system=_COMPREHEND_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=8192,
        model_hint="synthesis",
        temperature=0.0,
    )
    cleaned = _repair_json(_strip_code_fence(raw))
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        debug_path = Path("blackboard") / f"_comprehend_raw_{source_uuid}.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(raw, encoding="utf-8")
        print(f"[comprehend] WARNING: JSON parse failed at {exc.lineno}:{exc.colno}.")
        print(f"[comprehend] Raw output dumped to {debug_path}")
        print(f"[comprehend] Bad context: ...{cleaned[max(0,exc.pos-80):exc.pos+80]!r}...")
        print("[comprehend] Attempting LLM repair...")
        repaired = _strip_code_fence(_repair_via_llm(cleaned))
        parsed = json.loads(repaired)

    # Merge into plan skeleton (preserves source-uuid, generated-at, digest-rebuilt)
    for k in ("strategies-touched", "extends", "new-entities",
              "retrieve-for-context", "theme-connections"):
        if k in parsed:
            plan[k] = parsed[k]
    return plan


from pipeline.phase_c_validate import _exists, _resolve_alias, SUPPRESS_SLUGS


def validate_plan_slugs(plan: dict, wiki_root: str, aliases: dict) -> dict:
    """Strip ghost slugs from `extends` and `retrieve-for-context`.

    Reuses synthesis_validation helpers — applies alias resolution, suppress list,
    then drops anything whose page doesn't exist. `new-entities` is left alone
    (those slugs are intentionally for pages that DON'T exist yet).
    """
    cleaned = dict(plan)

    # extends: list of {slug, new-data} — filter on slug
    cleaned_extends = []
    seen_extends: set[str] = set()
    for item in plan.get("extends") or []:
        slug = item.get("slug", "")
        resolved = _resolve_alias(slug, aliases)
        if not resolved or resolved in SUPPRESS_SLUGS or resolved in seen_extends:
            continue
        if not _exists(resolved, wiki_root):
            continue
        seen_extends.add(resolved)
        cleaned_extends.append({**item, "slug": resolved})
    cleaned["extends"] = cleaned_extends

    # retrieve-for-context: list of slugs — filter directly
    cleaned_retrieve = []
    seen_retrieve: set[str] = set()
    for slug in plan.get("retrieve-for-context") or []:
        resolved = _resolve_alias(slug, aliases)
        if not resolved or resolved in SUPPRESS_SLUGS or resolved in seen_retrieve:
            continue
        if not _exists(resolved, wiki_root):
            continue
        seen_retrieve.add(resolved)
        cleaned_retrieve.append(resolved)
    cleaned["retrieve-for-context"] = cleaned_retrieve

    return cleaned


RETRIEVE_TOKEN_BUDGET = 30000  # ~4 chars/token heuristic → ~120k chars
_CHARS_PER_TOKEN = 4


def load_retrieved_bodies(plan: dict, wiki_root: str) -> dict[str, str]:
    """Load entity page bodies for slugs in `retrieve-for-context`, prioritized
    by `extends` then plan-mention frequency, capped at RETRIEVE_TOKEN_BUDGET.

    Returns dict mapping slug → body text. Pages whose load would exceed budget
    are silently dropped (long-tail entities fall back to existing _merge_pages).
    """
    extends_slugs = {e.get("slug", "") for e in plan.get("extends") or []}
    retrieve_slugs = plan.get("retrieve-for-context") or []

    # Mention frequency across plan fields (used as secondary priority)
    text_blob = json.dumps(plan)
    def _mention_count(slug: str) -> int:
        return text_blob.count(slug)

    # Sort: extends-first, then by mention frequency (desc), then by slug for stability
    ordered = sorted(
        retrieve_slugs,
        key=lambda s: (s not in extends_slugs, -_mention_count(s), s),
    )

    bodies: dict[str, str] = {}
    char_budget = RETRIEVE_TOKEN_BUDGET * _CHARS_PER_TOKEN
    used = 0
    for slug in ordered:
        page_path = Path(wiki_root) / f"{slug}.md"
        if not page_path.exists():
            continue
        try:
            raw = page_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Strip frontmatter; keep body only
        body = re.sub(r"^---\n.*?\n---\n", "", raw, flags=re.DOTALL).strip()
        body_len = len(body)
        is_extends = slug in extends_slugs
        if used + body_len > char_budget and not is_extends:
            continue  # drop overflow silently (extends always included)
        if is_extends and body_len > char_budget // 2:
            # Safety log: a single extends body is dominating the budget.
            # Worth checking if the page should be split or if Comprehend is
            # overreaching by extending a page that's grown unwieldy.
            print(
                f"[comprehend] WARNING: extends entity {slug!r} body is "
                f"{body_len} chars (~{body_len // _CHARS_PER_TOKEN} tokens) — "
                f"exceeds half the {RETRIEVE_TOKEN_BUDGET}-token budget. "
                f"Bypassing budget cap to honor extends-first contract."
            )
        bodies[slug] = body
        used += body_len
    return bodies


def log_ingest_stats(
    log_path: str,
    source_uuid: str,
    run_date: str,
    comprehend_skipped: bool,
    plan_size_bytes: int,
    extends_count: int,
    new_entities_count: int,
    retrieve_count: int,
    retrieved_chars: int,
) -> None:
    """Append one JSON line of per-ingest stats. Cheap monitoring for ingest health."""
    entry = {
        "source-uuid": source_uuid,
        "run-date": run_date,
        "comprehend-skipped": comprehend_skipped,
        "plan-size-bytes": plan_size_bytes,
        "extends-count": extends_count,
        "new-entities-count": new_entities_count,
        "retrieve-count": retrieve_count,
        "retrieved-chars": retrieved_chars,
    }
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
