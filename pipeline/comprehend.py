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
from pipeline.llm import chat


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
  of: actor, initiative, location, technology, funding-event, meeting, political-event.
- retrieve-for-context: list of existing entity slugs whose page bodies should be loaded \
  as reference context during chunk-by-chunk extraction. Include entities in `extends` \
  and any other existing entities the source heavily references. Aim for 5-15 entities.
- theme-connections: list of 2-5 short strings describing cross-strategy patterns this \
  source surfaces (e.g. "Source ties grid capacity to building electrification timeline").

Use slug references from the digest's entity map. Do not invent slugs for existing entities. \
For `new-entities`, use kebab-case slugs that follow project conventions.

Return ONLY the JSON object. No preamble, no code fences, no commentary.
"""


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:-1]) if len(lines) > 2 else t
    return t.strip()


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
        max_tokens=4096,
        model_hint="synthesis",
        temperature=0.0,
    )
    parsed = json.loads(_strip_code_fence(raw))

    # Merge into plan skeleton (preserves source-uuid, generated-at, digest-rebuilt)
    for k in ("strategies-touched", "extends", "new-entities",
              "retrieve-for-context", "theme-connections"):
        if k in parsed:
            plan[k] = parsed[k]
    return plan
