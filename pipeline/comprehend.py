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
