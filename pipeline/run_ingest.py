import json
import re
import shutil
import yaml
from datetime import date
from pathlib import Path
from pipeline.raw_to_sources import convert_annual_report
from pipeline.wiki_pages import extract_quads_from_source
from pipeline.post_ingest import run_post_ingest
from pipeline.ldp import run_ldp_ingest
from pipeline.holistic_synthesizer import synthesize_source
from pipeline.wiki_index import rebuild_index, append_log as wiki_append_log


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
    return len(lines) > 150 and headings > 5


def run_source_ingest(
    source_path: str,
    uuid: str,
    title: str,
    quads_path: str,
    wiki_root: str,
    review_queue_path: str,
    section_maps_dir: str = "blackboard/section_maps",
    run_date: str | None = None,
    wiki_only: bool = False,
    quads_only: bool = False,
):
    """Ingest a source markdown file through the three-pass wiki pipeline.

    Pass 1 (holistic): full-document read → overview + strategy synthesis + index seed
    Pass 2 (chunked, conditional): section-by-section → initiative/actor/location pages
    Pass 3 (finalize): rebuild index.md; seal log.md
    """
    if run_date is None:
        run_date = date.today().isoformat()

    # ── Step 0: Copy source from prepared/ into wiki/sources/ ────────────────
    # Source files live in prepared/<type>/<uuid>.md (outside vault) until ingested.
    # Ingest is the gate: copying the file into wiki/sources/ makes it a vault node.
    _prepared = Path(source_path)
    _src_parts = _prepared.parts
    # Infer destination: replace leading "prepared/" with wiki_root/sources/
    # e.g. prepared/cap/cap-2020.md → wiki/sources/cap/cap-2020.md
    if _src_parts[0] == "prepared":
        _dest = Path(wiki_root) / "sources" / Path(*_src_parts[1:])
        _dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_prepared, _dest)

        # Inject YAML frontmatter if the prepared file doesn't have it.
        # Sources that were manually prepared with frontmatter (e.g. cap-2020) pass through unchanged.
        _copied = _dest.read_text(encoding="utf-8")
        if not _copied.startswith("---"):
            _type_dir = _src_parts[1]
            _source_type_map = {
                "annual-reports": "annual-report",
                "cap": "cap",
                "transcripts": "council-transcript",
                "news": "news",
                "research": "research",
            }
            _inferred_type = _source_type_map.get(_type_dir, _type_dir.rstrip("s"))
            _injected = (
                f"---\n"
                f"uuid: {uuid}\n"
                f"source_type: {_inferred_type}\n"
                f'title: "{title}"\n'
                f'ingest_date: "{run_date}"\n'
                f"---\n\n"
            )
            _dest.write_text(_injected + _copied, encoding="utf-8")

        vault_source_path = str(_dest)
    else:
        # Caller passed a path already inside the vault; use it directly.
        vault_source_path = source_path

    source_content = Path(vault_source_path).read_text(encoding="utf-8")
    # Wikilink path is vault-relative (strip wiki_root prefix + .md extension).
    _src = Path(vault_source_path)
    try:
        source_rel_path = str(_src.relative_to(wiki_root).with_suffix(""))
    except ValueError:
        source_rel_path = str(_src.with_suffix(""))

    # Extract source_type from frontmatter
    source_type = "unknown"
    m = re.match(r"^---\n(.*?)\n---\n", source_content, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1))
            if fm:
                source_type = fm.get("source_type", "unknown")
        except Exception:
            pass

    # ── Pass 1: Holistic synthesis (skipped for quads-only) ──────────────────
    def _build_entity_context(entities: list[dict]) -> str:
        """Build the known-entity + existing-page-body block for Pass 2 chunk headers."""
        if not entities:
            return ""
        lines = [
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "KNOWN ENTITIES FROM HOLISTIC READ",
            "These entities were identified from the full document by a prior holistic read.",
            "When you encounter any of them — even under a different name or abbreviation —",
            "populate the existing stub rather than creating a duplicate page.",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for e in entities:
            lines.append(
                f"  [[{e['slug']}|{e['title']}]] — {e.get('one-liner', '')}"
            )
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Include existing page bodies for READ-UNDERSTAND-INTEGRATE (Amendment A).
        # When a known entity already has real wiki content from a prior ingest,
        # show it in [EXISTING: slug] blocks so the LLM integrates rather than duplicates.
        existing_pages_block = ""
        for e in entities:
            slug = e.get("slug", "")
            if not slug:
                continue
            page_path = Path(wiki_root) / (slug + ".md")
            if not page_path.exists():
                continue
            try:
                content = page_path.read_text(encoding="utf-8")
                body = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL).strip()
                if re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip():
                    existing_pages_block += f"\n[EXISTING: {slug}]\n{body}\n[END EXISTING]\n"
            except (OSError, UnicodeDecodeError):
                pass

        if existing_pages_block:
            lines.append("\nEXISTING PAGE CONTENT — READ-UNDERSTAND-INTEGRATE:")
            lines.append(existing_pages_block)

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        return "\n".join(lines)

    # ── Pass 1A: Comprehend → integration plan ───────────────────────────────
    from pipeline.comprehend import (
        build_integration_plan,
        validate_plan_slugs,
        write_integration_plan,
        load_retrieved_bodies,
        log_ingest_stats,
    )
    from pipeline.alias_registry import load_aliases
    import time as _time

    digest_path = Path(wiki_root) / "digest.md"
    digest_content = digest_path.read_text(encoding="utf-8") if digest_path.exists() else None

    integration_plan = None
    retrieved_bodies: dict[str, str] = {}
    if not quads_only:
        comprehend_start = _time.time()
        # Hard-fail when digest exists; graceful fallback only when no digest at all.
        # build_integration_plan() raises if the LLM call fails with a digest present.
        integration_plan = build_integration_plan(
            source_content=source_content,
            source_uuid=uuid,
            digest_content=digest_content,
            run_date=run_date,
        )
        # Strip ghost slugs (reuses synthesis_validation machinery)
        _aliases = load_aliases("registry/entity_aliases.json")
        integration_plan = validate_plan_slugs(integration_plan, wiki_root, _aliases)
        # Persist plan for audit trail and for LDP to consume
        plans_dir = Path(wiki_root) / "integration-plans"
        plan_path = write_integration_plan(integration_plan, str(plans_dir))
        print(f"[ingest] {uuid}: integration plan written → {plan_path}")
        # Pre-load entity bodies for retrieve-for-context (token-budget capped)
        retrieved_bodies = load_retrieved_bodies(integration_plan, wiki_root)
        # Telemetry: per-ingest stats
        stats_path = Path(wiki_root) / "meta" / "ingest-stats.jsonl"
        log_ingest_stats(
            log_path=str(stats_path),
            source_uuid=uuid,
            run_date=run_date,
            comprehend_skipped=(digest_content is None),
            plan_size_bytes=len(json.dumps(integration_plan)),
            extends_count=len(integration_plan.get("extends", [])),
            new_entities_count=len(integration_plan.get("new-entities", [])),
            retrieve_count=len(integration_plan.get("retrieve-for-context", [])),
            retrieved_chars=sum(len(b) for b in retrieved_bodies.values()),
        )
        print(f"[ingest] {uuid}: comprehend took {_time.time() - comprehend_start:.1f}s "
              f"(extends={len(integration_plan.get('extends', []))}, "
              f"new={len(integration_plan.get('new-entities', []))}, "
              f"retrieve={len(integration_plan.get('retrieve-for-context', []))})")

    if quads_only:
        entity_context = ""
        print(f"[ingest] {uuid}: quads-only — skipping Pass 1 holistic synthesis")
    else:
        synthesis_result = synthesize_source(
            source_content=source_content,
            source_uuid=uuid,
            source_rel_path=source_rel_path,
            source_type=source_type,
            wiki_root=wiki_root,
            run_date=run_date,
            integration_plan=integration_plan,
            digest_content=digest_content,
        )
        known_entities: list[dict] = []
        if synthesis_result:
            known_entities = [
                sp for sp in synthesis_result.get("stub_pages", [])
                if sp.get("slug") and sp.get("title")
            ]
        entity_context = _build_entity_context(known_entities)

    # ── Pass 2: Extraction (conditional on document complexity) ───────────────
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
            quads_only=quads_only,
            entity_context=entity_context,
            integration_plan=integration_plan,
            retrieved_bodies=retrieved_bodies,
        )
    else:
        if not wiki_only:
            extract_quads_from_source(
                source_content=source_content,
                source_uuid=uuid,
                out_path=quads_path,
            )
        if not quads_only:
            from pipeline.wiki_writer import extract_wiki_pages_from_chunk
            body = re.sub(r"^---\n.*?\n---\n", "", source_content, flags=re.DOTALL).strip()
            _plan_ctx = ""
            if integration_plan or retrieved_bodies:
                _lines = []
                if integration_plan:
                    _lines.append("[INTEGRATION PLAN]\n" + json.dumps(integration_plan, indent=2) + "\n[END INTEGRATION PLAN]")
                if retrieved_bodies:
                    _lines.append("[RETRIEVED ENTITY PAGES]")
                    for _s, _b in retrieved_bodies.items():
                        _lines.append(f"--- {_s} ---\n{_b}")
                    _lines.append("[END RETRIEVED ENTITY PAGES]")
                _plan_ctx = "\n".join(_lines) + "\n"
            extract_wiki_pages_from_chunk(
                chunk_text=body,
                source_uuid=uuid,
                source_rel_path=source_rel_path,
                context_header=_plan_ctx + entity_context,
                source_type=source_type,
                wiki_root=wiki_root,
                run_date=run_date,
            )

    # ── Pass 3: Finalize index + log (skipped for quads-only) ────────────────
    if not quads_only:
        rebuild_index(wiki_root)
        wiki_append_log(
            wiki_root=wiki_root,
            message="Pass 3 complete — index rebuilt.",
            source_uuid=uuid,
            run_date=run_date,
        )
        # Seed alias registry with display titles for all entity pages first-seen
        # in this source.  On subsequent ingests, Pass 1.5 can fuzzy-match against
        # these titles and redirect to the canonical slug instead of creating
        # year-over-year name-drift duplicates.
        from pipeline.alias_registry import seed_aliases_from_ingest
        _source_wikilink = f"sources/{Path(source_path).stem}" if "/" not in source_rel_path else source_rel_path
        _seeded = seed_aliases_from_ingest(
            wiki_root=wiki_root,
            source_wikilink=source_rel_path,
            aliases_path="registry/entity_aliases.json",
        )
        if _seeded:
            print(f"[ingest] {uuid}: seeded {_seeded} alias entries for Pass 1.5 resolution")

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
    source_dir: str,
    quads_path: str,
    wiki_root: str,
    review_queue_path: str,
    run_date: str | None = None,
):
    if run_date is None:
        run_date = date.today().isoformat()

    # Step 1: Raw → Sources
    source_path = str(Path(source_dir) / f"{uuid}.md")
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
    extract_quads_from_source(
        source_content=source_content,
        source_uuid=uuid,
        out_path=quads_path,
    )
    # TODO: Pass 3 (wiki page extraction) not yet wired for PDF ingest path.
    # Wire it here once the annual-report source files are confirmed stable.

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

    # Source-first ingest (CAP, annual reports, etc. already in markdown)
    p_source = sub.add_parser("source", help="Ingest a pre-built source markdown file from prepared/")
    p_source.add_argument("--source", required=True, help="Path to source .md file in prepared/ (e.g. prepared/cap/cap-2020.md). Ingest copies it into wiki/sources/ automatically.")
    p_source.add_argument("--uuid", required=True)
    p_source.add_argument("--title", required=True)
    p_source.add_argument("--quads-path", default="blackboard/quads.jsonl")
    p_source.add_argument("--wiki-root", default="wiki")
    p_source.add_argument("--review-queue", default="review-queue.md")
    p_source.add_argument("--section-maps-dir", default="blackboard/section_maps")
    mode_group = p_source.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--wiki-only", action="store_true", default=False,
        help="Run Pass 1 + Pass 2 wiki extraction only; skip quad extraction and review-queue",
    )
    mode_group.add_argument(
        "--quads-only", action="store_true", default=False,
        help="Run Pass 2 quad extraction only; skip holistic synthesis, wiki writes, and Pass 3",
    )

    # PDF-first ingest (future use when raw PDF → prepared markdown pipeline is wired up)
    p_pdf = sub.add_parser("pdf", help="Ingest from PDF (raw → prepared → wiki)")
    p_pdf.add_argument("--pdf", required=True)
    p_pdf.add_argument("--uuid", required=True)
    p_pdf.add_argument("--year", required=True)
    p_pdf.add_argument("--title", required=True)
    p_pdf.add_argument("--source-dir", default="prepared/annual-reports")
    p_pdf.add_argument("--quads-path", default="blackboard/quads.jsonl")
    p_pdf.add_argument("--wiki-root", default="wiki")
    p_pdf.add_argument("--review-queue", default="review-queue.md")

    args = parser.parse_args()

    if args.command == "source":
        run_source_ingest(
            source_path=args.source,
            uuid=args.uuid,
            title=args.title,
            quads_path=args.quads_path,
            wiki_root=args.wiki_root,
            review_queue_path=args.review_queue,
            section_maps_dir=args.section_maps_dir,
            wiki_only=args.wiki_only,
            quads_only=args.quads_only,
        )
    elif args.command == "pdf":
        run_annual_report_ingest(
            pdf_path=args.pdf,
            uuid=args.uuid,
            year=args.year,
            title=args.title,
            source_dir=args.source_dir,
            quads_path=args.quads_path,
            wiki_root=args.wiki_root,
            review_queue_path=args.review_queue,
        )
    else:
        parser.print_help()
