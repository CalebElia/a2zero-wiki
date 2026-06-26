import anthropic
import yaml
import pdfplumber
from pathlib import Path
from datetime import date


CLEAN_SYSTEM = """You are a document cleaning assistant for the A2Zero climate wiki pipeline.
You receive raw PDF-extracted text from an A2Zero annual report and return clean Markdown.
Rules:
- Preserve all substantive content; do not summarize or omit any programs, figures, names, or dates
- Fix PDF extraction artifacts (broken hyphenation, garbled characters, misplaced headers)
- Use ## for strategy headings, ### for sub-sections
- Remove page numbers, headers, footers, and repeated boilerplate
- Keep all dollar amounts, percentages, program names, and actor names exactly as written
- Do not add commentary or analysis
Return only the cleaned Markdown body, no frontmatter."""


def extract_pdf_text(pdf_path: str) -> str:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"Raw PDF not found: {pdf_path}")
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


_DEFAULT_CLIENT: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = anthropic.Anthropic()
    return _DEFAULT_CLIENT


def clean_with_llm(raw_text: str, uuid: str, client: anthropic.Anthropic | None = None) -> str:
    c = client or _get_client()
    response = c.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=CLEAN_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Document UUID: {uuid}\n\nRaw extracted text:\n\n{raw_text}",
            }
        ],
    )
    return response.content[0].text


def build_frontmatter(
    uuid: str,
    source_type: str,
    title: str,
    year: str | None,
    raw_path: str,
    ingest_date: str,
) -> dict:
    fm = {
        "uuid": uuid,
        "source_type": source_type,
        "title": title,
        "ingest_date": ingest_date,
        "raw_path": raw_path,
    }
    if year:
        fm["year"] = year
    return fm


def write_source(out_path: str, frontmatter: dict, body: str):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)
    content = f"---\n{fm_yaml}---\n\n{body}\n"
    Path(out_path).write_text(content, encoding="utf-8")


def convert_annual_report(
    pdf_path: str,
    uuid: str,
    year: str,
    out_path: str,
    title: str,
    ingest_date: str | None = None,
):
    if ingest_date is None:
        ingest_date = date.today().isoformat()
    raw = extract_pdf_text(pdf_path)
    body = clean_with_llm(raw, uuid=uuid)
    fm = build_frontmatter(
        uuid=uuid,
        source_type="annual-report",
        title=title,
        year=year,
        raw_path=pdf_path,
        ingest_date=ingest_date,
    )
    write_source(out_path, fm, body)
    return out_path
