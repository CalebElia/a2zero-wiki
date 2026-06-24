import re
import yaml
from datetime import datetime
from pathlib import Path


def _index_path(wiki_root: str) -> Path:
    return Path(wiki_root) / "index.md"


def _log_path(wiki_root: str) -> Path:
    return Path(wiki_root) / "log.md"


def _hot_path(wiki_root: str) -> Path:
    return Path(wiki_root) / "hot.md"


def append_index_entry(
    wiki_root: str,
    page_type: str,
    slug: str,
    title: str,
    summary: str = "",
) -> None:
    """Add one line to wiki/index.md under the correct type section."""
    idx = _index_path(wiki_root)
    idx.parent.mkdir(parents=True, exist_ok=True)

    line = f"- [[{slug}|{title}]]"
    if summary:
        line += f" — {summary}"

    if not idx.exists():
        idx.write_text(
            f"# Wiki Index\n\n_Updated automatically on ingest._\n\n## {page_type}\n\n{line}\n",
            encoding="utf-8",
        )
        return

    content = idx.read_text(encoding="utf-8")
    section_header = f"\n## {page_type}\n"
    if section_header in content:
        content = content.replace(section_header, section_header + f"\n{line}\n")
    else:
        content = content.rstrip("\n") + f"\n{section_header}\n{line}\n"
    idx.write_text(content, encoding="utf-8")


def append_log(
    wiki_root: str,
    message: str,
    source_uuid: str = "",
    run_date: str = "",
) -> None:
    """Append a timestamped entry to wiki/log.md (append-only)."""
    log = _log_path(wiki_root)
    log.parent.mkdir(parents=True, exist_ok=True)

    ts = run_date or datetime.utcnow().strftime("%Y-%m-%d")
    parts = [ts]
    if source_uuid:
        parts.append(source_uuid)
    header = " | ".join(parts)

    entry = f"\n## [{header}]\n\n{message}\n"

    is_new = not log.exists() or log.stat().st_size == 0
    with log.open("a", encoding="utf-8") as f:
        if is_new:
            f.write("# Ingest Log\n\nAppend-only record of all pipeline operations.\n")
        f.write(entry)


def update_hot(wiki_root: str, summary: str) -> None:
    """Overwrite wiki/hot.md with a fresh recent-context summary (~500 words)."""
    hot = _hot_path(wiki_root)
    hot.parent.mkdir(parents=True, exist_ok=True)
    hot.write_text(f"# Hot Cache\n\n{summary}\n", encoding="utf-8")


def rebuild_index(wiki_root: str) -> None:
    """Rebuild wiki/index.md from scratch by scanning all wiki pages."""
    wiki = Path(wiki_root)
    entries: dict[str, list[dict]] = {}
    infrastructure = {"index.md", "log.md", "hot.md"}

    for md_file in sorted(wiki.rglob("*.md")):
        if md_file.name in infrastructure:
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
            m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
            fm = yaml.safe_load(m.group(1)) if m else {}
            page_type = (fm or {}).get("type", "unknown")
            title = (fm or {}).get("title", md_file.stem)
            slug = str(md_file.relative_to(wiki).with_suffix(""))
            entries.setdefault(page_type, []).append({"slug": slug, "title": title})
        except Exception:
            pass

    total = sum(len(v) for v in entries.values())
    today = datetime.utcnow().strftime("%Y-%m-%d")
    lines = [
        "# Wiki Index\n\n",
        f"_{total} pages — last updated {today}_\n",
    ]
    for pt in sorted(entries):
        lines.append(f"\n## {pt}\n\n")
        for p in sorted(entries[pt], key=lambda x: x["title"]):
            lines.append(f"- [[{p['slug']}|{p['title']}]]\n")

    _index_path(wiki_root).write_text("".join(lines), encoding="utf-8")
    print(f"[wiki_index] Index updated: {total} pages across {len(entries)} types")
