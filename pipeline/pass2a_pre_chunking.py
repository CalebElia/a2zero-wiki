"""HITL chunking gate.

Generates a proposed section map (mechanical, no LLM) plus a human-readable
preview. Human reviews/edits the proposed map, then runs `approve` to validate
and promote it. The orchestrator's source subcommand loads the approved map
instead of generating fresh.

See docs/architecture/chunking-gate.md for design rationale.
"""
import json
from pathlib import Path
from pipeline.pass2a_chunk_loop import parse_section_map


def generate_proposed_map(
    source_content: str,
    source_uuid: str,
    section_maps_dir: str,
    force: bool = False,
) -> tuple[str, str]:
    """Run parse_section_map, write proposed.json + preview.md.

    Refuses to run if <uuid>_approved.json already exists (unless force=True).
    Returns (proposed_json_path, preview_md_path).
    """
    maps_dir = Path(section_maps_dir)
    approved_path = maps_dir / f"{source_uuid}_approved.json"
    if approved_path.exists() and not force:
        raise FileExistsError(
            f"approved section map already exists for {source_uuid!r} at {approved_path}. "
            f"Pass force=True to regenerate (this will not delete the approved file)."
        )

    section_map = parse_section_map(source_content, source_uuid)
    section_map["approved"] = False

    maps_dir.mkdir(parents=True, exist_ok=True)
    proposed_path = maps_dir / f"{source_uuid}_proposed.json"
    preview_path = maps_dir / f"{source_uuid}_preview.md"

    proposed_path.write_text(
        json.dumps(section_map, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    preview = render_preview_markdown(section_map, source_content)
    preview_path.write_text(preview, encoding="utf-8")

    return str(proposed_path), str(preview_path)


def load_approved_map(source_uuid: str, section_maps_dir: str) -> dict | None:
    """Load <uuid>_approved.json. Returns None if missing."""
    path = Path(section_maps_dir) / f"{source_uuid}_approved.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def render_preview_markdown(section_map: dict, source_content: str) -> str:
    """Build the human-readable preview from a section map + source body."""
    lines_src = source_content.splitlines()
    sections = section_map.get("sections", [])
    chunks = [s for s in sections if s.get("is_chunk")]
    skipped = [s for s in sections if not s.get("is_chunk")]

    out = [
        f"# Chunk Preview: {section_map['document_uuid']}",
        "",
        f"**Total source lines:** {section_map.get('total_lines', '?')}",
        f"**Proposed chunks:** {len(chunks)}",
        f"**Skipped sections:** {len(skipped)}",
        "",
        "---",
        "",
    ]

    for i, s in enumerate(chunks, 1):
        start, end = s["line_start"], s["line_end"]
        body_lines = lines_src[start - 1:end]
        body_text = "\n".join(body_lines)
        char_count = len(body_text)
        token_estimate = char_count // 4
        preview = body_text[:200].replace("\n", " ").strip()
        if len(body_text) > 200:
            preview += "…"
        notes = s.get("notes") or "_none_"

        out.extend([
            f"## Chunk {i} — {s['title']}",
            f"- **Lines:** {start}–{end} (~{char_count} chars, ~{token_estimate} tokens)",
            f"- **Depth:** {s['depth']}",
            f"- **Notes:** {notes}",
            "",
            f"> {preview}",
            "",
            "---",
            "",
        ])

    if skipped:
        out.extend(["## Skipped Sections (is_chunk: false)", ""])
        for s in skipped:
            note = f" — {s['notes']}" if s.get("notes") else ""
            out.append(f"- depth {s['depth']}: **{s['title']}** (lines {s['line_start']}–{s['line_end']}){note}")
        out.append("")

    return "\n".join(out)


def validate_section_map(section_map: dict) -> list[str]:
    """Return list of validation errors (empty if valid)."""
    errors: list[str] = []

    if section_map.get("approved") is True:
        errors.append("section map is already approved (approved=true); cannot re-approve")

    total_lines = section_map.get("total_lines", 0)
    sections = section_map.get("sections", [])

    chunk_sections = [s for s in sections if s.get("is_chunk")]
    if not chunk_sections:
        errors.append("no sections marked is_chunk=true — at least one chunk required for extraction")

    for s in sections:
        start, end = s.get("line_start"), s.get("line_end")
        if start is None or end is None:
            errors.append(f"section {s.get('id', '?')!r}: line_start or line_end missing")
            continue
        if start > end:
            errors.append(
                f"section {s.get('id', '?')!r}: line_start ({start}) > line_end ({end})"
            )
        if start < 1 or end > total_lines:
            errors.append(
                f"section {s.get('id', '?')!r}: lines {start}-{end} outside bounds 1-{total_lines}"
            )

    # Check overlap among chunk sections only
    sorted_chunks = sorted(chunk_sections, key=lambda s: s.get("line_start", 0))
    for a, b in zip(sorted_chunks, sorted_chunks[1:]):
        a_end = a.get("line_end", 0)
        b_start = b.get("line_start", 0)
        if a_end >= b_start:
            errors.append(
                f"chunks {a.get('id', '?')!r} (ends {a_end}) and {b.get('id', '?')!r} "
                f"(starts {b_start}) overlap"
            )

    return errors


def approve_proposed_map(source_uuid: str, section_maps_dir: str) -> str:
    """Validate proposed.json, set approved=true, rename to approved.json.

    Returns the approved.json path. Raises FileNotFoundError if proposed is
    missing, or ValueError listing all validation errors if invalid.
    """
    maps_dir = Path(section_maps_dir)
    proposed_path = maps_dir / f"{source_uuid}_proposed.json"
    approved_path = maps_dir / f"{source_uuid}_approved.json"

    if not proposed_path.exists():
        raise FileNotFoundError(
            f"no proposed section map for {source_uuid!r} at {proposed_path}. "
            f"Run 'preflight' first."
        )

    section_map = json.loads(proposed_path.read_text(encoding="utf-8"))
    errors = validate_section_map(section_map)
    if errors:
        raise ValueError(
            f"section map for {source_uuid!r} is invalid:\n  - " + "\n  - ".join(errors)
        )

    section_map["approved"] = True
    approved_path.write_text(
        json.dumps(section_map, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    proposed_path.unlink()
    return str(approved_path)
