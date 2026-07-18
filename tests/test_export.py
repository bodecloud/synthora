"""U8: export endpoint snapshot behavior."""

from synthora.api.export import (
    markdown_to_html,
    markdown_to_pdf_bytes,
    render_html_document,
)

SAMPLE = """# Report Title

Intro paragraph with **bold**, *italic*, `code`, and [a link](https://example.com).

## Findings

- first finding [1]
- second finding [2]

## Sources
"""

RICH = """# Rich export

> A quoted insight

```python
def hello():
    return "world"
```

1. ordered one
2. ordered two

| Col A | Col B |
| --- | --- |
| a1 | b1 |

---

Final **note**.
"""


def test_markdown_to_html_structure():
    html = markdown_to_html(SAMPLE)
    assert "<h1>Report Title</h1>" in html
    assert "<h2>Findings</h2>" in html
    assert "<ul>" in html and "<li>first finding [1]</li>" in html
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<code>code</code>" in html
    assert '<a href="https://example.com">a link</a>' in html


def test_markdown_to_html_rich_features():
    html = markdown_to_html(RICH)
    assert "<blockquote>" in html
    assert "<pre><code" in html and "def hello" in html
    assert "<ol>" in html and "<li>ordered one</li>" in html
    assert "<table>" in html and "<th>Col A</th>" in html
    assert "<hr" in html


def test_html_document_escapes_title():
    doc = render_html_document("# x", title='<script>alert("t")</script>')
    assert "<script>alert" not in doc
    assert "&lt;script&gt;" in doc


def test_html_escapes_injected_markup():
    html = markdown_to_html("evil <img src=x onerror=alert(1)> text")
    assert "<img" not in html
    assert "&lt;img" in html


def test_markdown_to_pdf_bytes():
    pdf = markdown_to_pdf_bytes(SAMPLE, title="Report Title")
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 100


def test_markdown_to_pdf_preserves_structure():
    pdf = markdown_to_pdf_bytes(RICH, title="Rich export")
    assert pdf[:4] == b"%PDF"
    # fpdf2 embeds literal text from headings/list items in the PDF stream.
    blob = pdf.decode("latin-1", "replace")
    assert "Rich export" in blob
    assert "ordered one" in blob
