import re
import yaml
from datetime import date
from pathlib import Path
from pipeline.raw_to_sources import convert_annual_report
from pipeline.silver_to_gold import extract_quads_from_silver
from pipeline.post_ingest import run_post_ingest
from pipeline.ldp import run_ldp_ingest
from pipeline.plan_extractor import extract_plan_page


def _should_use_ldp(source_content: str) -> bool:
    m = re.match(r"^---\n(.*?)\n---\n", source_content, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1))
            if fm is not None and "ldp" in fm:
                return bool(fm["ldp"])
        except Exception:
            pass
    lines = source_content.splitlines()
    headings = sum(1 for line in lines if re.match(r"^#{1,4}\s", line))
    return len(lines) > 1000 and headings > 10


def run_silver_ingest(
    source_path: str,
    uuid: str,
    title: str,
    quads_path: str,
    wiki_root: str,
    review_queue_path: str,
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
    wiki_only: bool = False,
):
    """Ingest a pre-built source markdown file, auto-routing to LDP for long docs.

    wiki_only=True skips Pass 2 quad extraction and post-ingest reporting;
    only the plan extractor (Pass 1) and wiki writer (Pass 3) run.
    quads_path and review_queue_path are left completely untouched.
    """
    if run_date is None:
        run_date = date.today().isoformat()

    source_content = Path(source_path).read_text(encoding="utf-8")

    # Derive vault-relative path without extension for wikilink citations.
    # e.g. "sources/cap/cap-2020.md" → "sources/cap/cap-2020"
    source_rel_path = str(Path(source_path).with_suffix(""))

    # First pass: extract plan page (idempotent — skips if already exists).
    # Runs even in wiki_only mode: cheap, idempotent, needed for a clean vault.
    extract_plan_page(
        silver_content=source_content,
        source_uuid=uuid,
        source_rel_path=source_rel_path,
        wiki_root=wiki_root,
        run_date=run_date,
    )

    # Extract source_type from frontmatter once, before routing.
    source_type = "unknown"
    m = re.match(r"^---\n(.*?)\n---\n", source_content, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1))
            if fm:
                source_type = fm.get("source_type", "unknown")
        except Exception:
            pass

    if _should_use_ldp(source_content):
        run_ldp_ingest(
            source_content=source_content,
            uuid=uuid,
            title=title,
            quads_path=quads_path,
            source_rel_path=source_rel_path,
            wiki_root=wiki_root,
            source_type=source_type,
            section_maps_dir=section_maps_dir,
            run_date=run_date,
            wiki_only=wiki_only,
        )
    else:
        if not wiki_only:
            extract_quads_from_silver(
                silver_content=source_content,
                source_uuid=uuid,
                out_path=quads_path,
            )
        # Pass 3 for short docs (always runs)
        from pipeline.wiki_writer import extract_wiki_pages_from_chunk
        body = re.sub(r"^---\n.*?\n---\n", "", source_content, flags=re.DOTALL).strip()
        extract_wiki_pages_from_chunk(
            chunk_text=body,
            source_uuid=uuid,
            source_rel_path=source_rel_path,
            context_header="",  # short doc: no section context available
            source_type=source_type,
            wiki_root=wiki_root,
            run_date=run_date,
        )

    if wiki_only:
        print(f"[ingest] {uuid}: wiki-only run complete — quads and review-queue untouched")
        return None

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

    # Step 1: Raw → Sources
    source_path = str(Path(silver_dir) / f"{uuid}.md")
    convert_annual_report(
        pdf_path=pdf_path,
        uuid=uuid,
        year=year,
        out_path=source_path,
        title=title,
        ingest_date=run_date,
    )

    # Step 2: Sources → Quads (Pass 2)
    source_content = Path(source_path).read_text(encoding="utf-8")
    extract_quads_from_silver(
        silver_content=source_content,
        source_uuid=uuid,
        out_path=quads_path,
    )
    # TODO: Pass 3 (wiki page extraction) not yet wired for PDF ingest path.
    # Wire it here once the annual report silver files are confirmed stable.

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

    # Source-first ingest (CAP, annual reports already in markdown)
    p_silver = sub.add_parser("silver", help="Ingest a pre-built source markdown file")
    p_silver.add_argument("--source", required=True, help="Path to source .md file (e.g. sources/cap/cap-2020.md)")
    p_silver.add_argument("--uuid", required=True)
    p_silver.add_argument("--title", required=True)
    p_silver.add_argument("--quads-path", default="blackboard/quads.jsonl")
    p_silver.add_argument("--wiki-root", default="wiki")
    p_silver.add_argument("--review-queue", default="review-queue.md")
    p_silver.add_argument("--section-maps-dir", default="blackboard/section_maps")
    p_silver.add_argument(
        "--wiki-only", action="store_true", default=False,
        help="Run only Pass 1 (plan extractor) + Pass 3 (wiki writer); skip quad extraction and review-queue update",
    )

    # PDF-first ingest (future use when Bronze→Silver pipeline is complete)
    p_pdf = sub.add_parser("pdf", help="Ingest from PDF (Bronze→Silver→Gold)")
    p_pdf.add_argument("--pdf", required=True)
    p_pdf.add_argument("--uuid", required=True)
    p_pdf.add_argument("--year", required=True)
    p_pdf.add_argument("--title", required=True)
    p_pdf.add_argument("--silver-dir", default="sources/annual-reports")
    p_pdf.add_argument("--quads-path", default="blackboard/quads.jsonl")
    p_pdf.add_argument("--wiki-root", default="wiki")
    p_pdf.add_argument("--review-queue", default="review-queue.md")

    args = parser.parse_args()

    if args.command == "silver":
        run_silver_ingest(
            source_path=args.source,
            uuid=args.uuid,
            title=args.title,
            quads_path=args.quads_path,
            wiki_root=args.wiki_root,
            review_queue_path=args.review_queue,
            section_maps_dir=args.section_maps_dir,
            wiki_only=args.wiki_only,
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
