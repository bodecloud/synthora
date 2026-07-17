"""Report export (R-LDR-5): Markdown, self-contained HTML, and PDF bytes."""

from __future__ import annotations

import html as html_lib
import re

HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 46rem; margin: 3rem auto; line-height: 1.6; color: #1c2a30; padding: 0 1.5rem; }}
  h1, h2, h3 {{ font-family: Georgia, serif; letter-spacing: -0.01em; }}
  code {{ font-family: ui-monospace, monospace; background: #f3f1ea; padding: 0.1em 0.3em; border-radius: 3px; }}
  a {{ color: #0e6f6a; }}
  blockquote {{ border-left: 3px solid #0e6f6a; margin-left: 0; padding-left: 1rem; color: #3d5059; }}
  @media print {{ body {{ margin: 0.5in; max-width: none; }} }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def markdown_to_html(markdown: str) -> str:
    """Minimal dependency-free Markdown -> HTML for report export.

    Covers the subset our writers emit: headings, paragraphs, lists,
    bold/italic, inline code, and links.
    """
    lines = markdown.splitlines()
    out: list[str] = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            if in_list:
                out.append("</ul>")
                in_list = False
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if not stripped:
            continue
        out.append(f"<p>{_inline(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline(text: str) -> str:
    text = html_lib.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', text
    )
    return text


def render_html_document(markdown: str, *, title: str) -> str:
    return HTML_TEMPLATE.format(
        title=html_lib.escape(title), body=markdown_to_html(markdown)
    )


def _plain_from_markdown(markdown: str) -> str:
    """Strip common markdown markers for PDF core fonts."""
    text = re.sub(r"^#{1,6}\s+", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)
    return text


def _pdf_safe(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def markdown_to_pdf_bytes(markdown: str, *, title: str = "Report") -> bytes:
    """Render markdown to PDF bytes using fpdf2 (no network)."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(
        0,
        10,
        _pdf_safe(title or "Report"),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(4)
    pdf.set_font("Helvetica", size=11)
    body = _plain_from_markdown(markdown or "")
    for line in body.splitlines() or [""]:
        if not line.strip():
            pdf.ln(6)
            continue
        pdf.multi_cell(
            0,
            6,
            _pdf_safe(line),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    out = pdf.output()
    return bytes(out)
