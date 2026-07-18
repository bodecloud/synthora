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
  pre {{ background: #f3f1ea; padding: 0.75rem 1rem; overflow-x: auto; border-radius: 4px; }}
  pre code {{ background: transparent; padding: 0; }}
  a {{ color: #0e6f6a; }}
  blockquote {{ border-left: 3px solid #0e6f6a; margin-left: 0; padding-left: 1rem; color: #3d5059; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #d8d2c4; padding: 0.35rem 0.6rem; text-align: left; }}
  th {{ background: #f3f1ea; }}
  hr {{ border: none; border-top: 1px solid #d8d2c4; margin: 1.5rem 0; }}
  @media print {{ body {{ margin: 0.5in; max-width: none; }} }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def markdown_to_html(markdown: str) -> str:
    """Dependency-free Markdown -> HTML for report export.

    Covers headings, paragraphs, bullet/ordered lists, blockquotes, fenced
    code blocks, tables, bold/italic, inline code, and links.
    """
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    list_kind: str | None = None  # "ul" | "ol"

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            out.append(f"</{list_kind}>")
            list_kind = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            close_list()
            fence = stripped[3:].strip()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            code = html_lib.escape("\n".join(code_lines))
            lang = html_lib.escape(fence) if fence else ""
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{code}</code></pre>")
            continue

        if stripped.startswith("|") and "|" in stripped[1:]:
            close_list()
            table_rows: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_rows.append(lines[i].strip())
                i += 1
            if len(table_rows) >= 2 and re.match(r"^\|[-: |]+\|$", table_rows[1]):
                table_rows.pop(1)
            if table_rows:
                out.append("<table>")
                for row_idx, row in enumerate(table_rows):
                    cells = [c.strip() for c in row.strip("|").split("|")]
                    tag = "th" if row_idx == 0 else "td"
                    out.append("<tr>")
                    for cell in cells:
                        out.append(f"<{tag}>{_inline(cell)}</{tag}>")
                    out.append("</tr>")
                out.append("</table>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if re.match(r"^[-*]{3,}$", stripped):
            close_list()
            out.append("<hr />")
            i += 1
            continue

        if stripped.startswith(">"):
            close_list()
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").lstrip())
                i += 1
            out.append(
                f"<blockquote><p>{_inline(' '.join(quote_lines))}</p></blockquote>"
            )
            continue

        ordered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if ordered:
            if list_kind != "ol":
                close_list()
                out.append("<ol>")
                list_kind = "ol"
            out.append(f"<li>{_inline(ordered.group(2))}</li>")
            i += 1
            continue

        if stripped.startswith(("- ", "* ")):
            if list_kind != "ul":
                close_list()
                out.append("<ul>")
                list_kind = "ul"
            out.append(f"<li>{_inline(stripped[2:])}</li>")
            i += 1
            continue

        close_list()
        if not stripped:
            i += 1
            continue
        out.append(f"<p>{_inline(stripped)}</p>")
        i += 1

    close_list()
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


def _pdf_safe(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def markdown_to_pdf_bytes(markdown: str, *, title: str = "Report") -> bytes:
    """Render markdown to PDF bytes using fpdf2 HTML layout (no network)."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF()
    pdf.set_compression(False)
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
    body_html = markdown_to_html(markdown or "")
    if body_html.strip():
        pdf.write_html(_pdf_safe(body_html))
    out = pdf.output()
    return bytes(out)
