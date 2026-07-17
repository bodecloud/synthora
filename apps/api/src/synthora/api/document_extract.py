"""Extract plain text from uploaded research documents."""

from __future__ import annotations

import io
from pathlib import Path


def extract_document_text(filename: str, data: bytes) -> str:
    """Return UTF-8 text from ``filename`` bytes.

    Supports ``.txt`` / ``.md`` / ``.csv`` / ``.html`` / ``.htm``,
    ``.pdf`` (pypdf), and ``.docx`` (python-docx).
    """
    name = (filename or "upload.txt").lower()
    suffix = Path(name).suffix

    if suffix in {".txt", ".md", ".markdown", ".csv", ".log"}:
        return data.decode("utf-8", errors="replace").strip()

    if suffix in {".html", ".htm"}:
        from synthora.adapters.page_fetch import html_to_text

        return html_to_text(data.decode("utf-8", errors="replace"))

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages).strip()

    if suffix == ".docx":
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text).strip()

    raise ValueError(
        f"unsupported file type '{suffix or name}'; "
        "use .txt, .md, .csv, .html, .pdf, or .docx"
    )
