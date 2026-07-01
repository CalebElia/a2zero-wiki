import json
from dataclasses import dataclass, field
from pathlib import Path
from pipeline._models import validate_quad


@dataclass
class LintReport:
    total_quads: int = 0
    confirmed_count: int = 0
    unverified_count: int = 0
    schema_errors: list[dict] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    dark_matter_ids: list[str] = field(default_factory=list)


def lint_quads(quads_path: str) -> LintReport:
    report = LintReport()
    p = Path(quads_path)
    if not p.exists():
        raise FileNotFoundError(f"quad_linter: quads file not found: {quads_path}")
    seen_ids: dict[str, int] = {}
    lines = p.read_text(encoding="utf-8").splitlines()
    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            quad = json.loads(line)
        except json.JSONDecodeError as e:
            report.schema_errors.append({"line": line_num, "error": str(e)})
            continue

        report.total_quads += 1

        errors = validate_quad(quad)
        if errors:
            report.schema_errors.append({
                "line": line_num,
                "id": quad.get("id", "unknown"),
                "errors": errors,
            })

        qid = quad.get("id", "")
        if qid:
            if qid in seen_ids:
                if qid not in report.duplicate_ids:
                    report.duplicate_ids.append(qid)
            seen_ids[qid] = line_num
            if quad.get("dark_matter") and qid not in report.dark_matter_ids:
                report.dark_matter_ids.append(qid)

        if quad.get("status") == "confirmed":
            report.confirmed_count += 1
        elif quad.get("status") == "unverified":
            report.unverified_count += 1

    return report
