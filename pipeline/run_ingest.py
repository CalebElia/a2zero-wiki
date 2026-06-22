import re
import yaml
from datetime import date
from pathlib import Path
from pipeline.bronze_to_silver import convert_annual_report
from pipeline.silver_to_gold import extract_quads_from_silver
from pipeline.post_ingest import run_post_ingest
from pipeline.ldp import run_ldp_ingest


def _should_use_ldp(silver_content: str) -> bool:
    m = re.match(r"^---\n(.*?)\n---\n", silver_content, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1))
            if fm is not None and "ldp" in fm:
                return bool(fm["ldp"])
        except Exception:
            pass
    lines = silver_content.splitlines()
    headings = sum(1 for line in lines if re.match(r"^#{1,4}\s", line))
    return len(lines) > 1000 and headings > 10


def run_silver_ingest(
    silver_path: str,
    uuid: str,
    title: str,
    quads_path: str,
    wiki_root: str,
    review_queue_path: str,
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
):
    """Ingest a pre-built Silver markdown file, auto-routing to LDP for long docs."""
    if run_date is None:
        run_date = date.today().isoformat()

    silver_content = Path(silver_path).read_text(encoding="utf-8")

    if _should_use_ldp(silver_content):
        run_ldp_ingest(
            silver_content=silver_content,
            uuid=uuid,
            title=title,
            quads_path=quads_path,
            section_maps_dir=section_maps_dir,
            run_date=run_date,
        )
    else:
        extract_quads_from_silver(
            silver_content=silver_content,
            source_uuid=uuid,
            out_path=quads_path,
        )

    report = run_post_ingest(
        quads_path=quads_path,
        source_uuid=uuid,
        out_path=review_queue_path,
        run_date=run_date,
    )
    print(f"[ingest] {uuid}: {report.total_quads} quads, "
          f"{len(report.schema_errors)} errors, "
          f"{len(report.dark_matter_ids)} dark matter")
    return report


def run_annual_report_ingest(
    pdf_path: str,
    uuid: str,
    year: str,
    title: str,
    silver_dir: str,
    quads_path: str,
    wiki_root: str,
    review_queue_path: str,
    run_date: str | None = None,
):
    if run_date is None:
        run_date = date.today().isoformat()

    # Step 1: Bronze → Silver
    silver_path = str(Path(silver_dir) / f"{uuid}.md")
    convert_annual_report(
        pdf_path=pdf_path,
        uuid=uuid,
        year=year,
        out_path=silver_path,
        title=title,
        ingest_date=run_date,
    )

    # Step 2: Silver → Quads (Pass 2)
    silver_content = Path(silver_path).read_text(encoding="utf-8")
    extract_quads_from_silver(
        silver_content=silver_content,
        source_uuid=uuid,
        out_path=quads_path,
    )

    # Steps 3-6: Post-ingest (lint + review queue)
    report = run_post_ingest(
        quads_path=quads_path,
        source_uuid=uuid,
        out_path=review_queue_path,
        run_date=run_date,
    )

    print(f"[ingest] {uuid}: {report.total_quads} quads, "
          f"{len(report.schema_errors)} errors, "
          f"{len(report.dark_matter_ids)} dark matter")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A2Zero ingest pipeline")
    sub = parser.add_subparsers(dest="command")

    # Silver-first ingest (CAP, annual reports already in markdown)
    p_silver = sub.add_parser("silver", help="Ingest a pre-built Silver markdown file")
    p_silver.add_argument("--silver", required=True, help="Path to Silver .md file")
    p_silver.add_argument("--uuid", required=True)
    p_silver.add_argument("--title", required=True)
    p_silver.add_argument("--quads-path", default="blackboard/quads.jsonl")
    p_silver.add_argument("--wiki-root", default="wiki")
    p_silver.add_argument("--review-queue", default="review-queue.md")
    p_silver.add_argument("--section-maps-dir", default="blackboard/section_maps")

    # PDF-first ingest (future use when Bronze→Silver pipeline is complete)
    p_pdf = sub.add_parser("pdf", help="Ingest from PDF (Bronze→Silver→Gold)")
    p_pdf.add_argument("--pdf", required=True)
    p_pdf.add_argument("--uuid", required=True)
    p_pdf.add_argument("--year", required=True)
    p_pdf.add_argument("--title", required=True)
    p_pdf.add_argument("--silver-dir", default="silver/annual-reports")
    p_pdf.add_argument("--quads-path", default="blackboard/quads.jsonl")
    p_pdf.add_argument("--wiki-root", default="wiki")
    p_pdf.add_argument("--review-queue", default="review-queue.md")

    args = parser.parse_args()

    if args.command == "silver":
        run_silver_ingest(
            silver_path=args.silver,
            uuid=args.uuid,
            title=args.title,
            quads_path=args.quads_path,
            wiki_root=args.wiki_root,
            review_queue_path=args.review_queue,
            section_maps_dir=args.section_maps_dir,
        )
    elif args.command == "pdf":
        run_annual_report_ingest(
            pdf_path=args.pdf,
            uuid=args.uuid,
            year=args.year,
            title=args.title,
            silver_dir=args.silver_dir,
            quads_path=args.quads_path,
            wiki_root=args.wiki_root,
            review_queue_path=args.review_queue,
        )
    else:
        parser.print_help()
