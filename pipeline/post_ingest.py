from pathlib import Path
from pipeline.quad_linter import LintReport


def generate_review_queue(
    report: LintReport,
    source_uuid: str,
    out_path: str,
    run_date: str,
):
    if not run_date:
        raise ValueError("run_date must be a non-empty ISO date string (e.g. '2026-06-18')")
    lines = [
        f"# Review Queue — {source_uuid} — {run_date}",
        "",
        "## Summary",
        f"- Total quads: {report.total_quads}",
        f"- Confirmed: {report.confirmed_count}",
        f"- Unverified: {report.unverified_count}",
        f"- Schema errors: {len(report.schema_errors)}",
        f"- Duplicate IDs: {len(report.duplicate_ids)}",
        f"- Dark matter quads: {len(report.dark_matter_ids)}",
        "",
    ]

    # 🔴 Urgent
    urgent = []
    if report.schema_errors:
        urgent.append("### Schema Errors")
        for e in report.schema_errors:
            qid = e.get("id", "unknown")
            errs = "; ".join(e.get("errors", [str(e.get("error", ""))]))
            urgent.append(f"- `{qid}` (line {e.get('line', '?')}): {errs}")
    if report.duplicate_ids:
        urgent.append("### Duplicate IDs")
        for qid in report.duplicate_ids:
            urgent.append(f"- `{qid}`")

    if urgent:
        lines.append("## 🔴 Urgent — Fix Before Merging")
        lines.extend(urgent)
        lines.append("")

    # 🟡 Normal
    normal = []
    if report.dark_matter_ids:
        normal.append("### Dark Matter — Known Outcomes, Missing Mechanism")
        normal.append("_Trigger source discovery for these quads._")
        for qid in report.dark_matter_ids:
            normal.append(f"- `{qid}`")
    if report.unverified_count > 0:
        normal.append(f"### Unverified Quads ({report.unverified_count})")
        normal.append("_Run: `duckdb -c \"SELECT id, subject, relation, object FROM read_ndjson('blackboard/quads.jsonl') WHERE status = 'unverified' ORDER BY date\"`_")

    if normal:
        lines.append("## 🟡 Normal — Review This Week")
        lines.extend(normal)
        lines.append("")

    # 🟢 Low
    lines.append("## 🟢 Low — Skim Confirmed Quads")
    lines.append(f"{report.confirmed_count} confirmed quads added from `{source_uuid}`.")
    lines.append(f"_Run: `duckdb -c \"SELECT date, subject, relation, object FROM read_ndjson('blackboard/quads.jsonl') WHERE list_contains(sources, '{source_uuid}') ORDER BY date\"`_")
    lines.append("")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


def run_post_ingest(quads_path: str, source_uuid: str, out_path: str, run_date: str):
    from pipeline.quad_linter import lint_quads
    report = lint_quads(quads_path)
    generate_review_queue(report=report, source_uuid=source_uuid,
                          out_path=out_path, run_date=run_date)
    return report
