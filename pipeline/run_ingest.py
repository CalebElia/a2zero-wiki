import json
from datetime import date
from pathlib import Path
from pipeline.bronze_to_silver import convert_annual_report
from pipeline.silver_to_gold import extract_quads_from_silver
from pipeline.post_ingest import run_post_ingest


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--uuid", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--silver-dir", default="silver/annual-reports")
    parser.add_argument("--quads-path", default="blackboard/quads.jsonl")
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument("--review-queue", default="review-queue.md")
    args = parser.parse_args()
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
