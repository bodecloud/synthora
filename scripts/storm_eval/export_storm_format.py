"""Export Synthora run artifacts to STORM eval file layout."""

from __future__ import annotations

import json
from pathlib import Path


def export_run_dir(
    *,
    topic: str,
    report_markdown: str,
    outline_markdown: str | None,
    output_dir: Path,
) -> Path:
    slug = topic.replace(" ", "_")
    run_dir = output_dir / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "storm_gen_article_polished.txt").write_text(
        report_markdown, encoding="utf-8"
    )
    if outline_markdown:
        (run_dir / "storm_gen_outline.txt").write_text(outline_markdown, encoding="utf-8")
    meta = {"topic": topic, "slug": slug}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return run_dir
