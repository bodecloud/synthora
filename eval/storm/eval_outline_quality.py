#!/usr/bin/env python3
"""Evaluate outline quality against FreshWiki ground truth."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from eval.storm.metrics import score_outline


def main() -> None:
    parser = argparse.ArgumentParser(description="STORM outline quality eval")
    parser.add_argument("--input-path", required=True, help="CSV with topic column")
    parser.add_argument("--gt-dir", required=True, help="Ground truth FreshWiki dir")
    parser.add_argument("--pred-dir", required=True, help="Predictions directory")
    parser.add_argument("--pred-file-name", default="storm_gen_outline.txt")
    parser.add_argument("--result-output-path", required=True)
    args = parser.parse_args()

    topics: list[str] = []
    with open(args.input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            topic = row.get("topic") or row.get("title") or ""
            if topic.strip():
                topics.append(topic.strip())

    rows: list[dict[str, str | float]] = []
    gt_dir = Path(args.gt_dir)
    pred_dir = Path(args.pred_dir)
    for topic in topics:
        slug = topic.replace(" ", "_")
        gt_path = gt_dir / slug / "outline_gt.md"
        if not gt_path.exists():
            gt_path = gt_dir / f"{slug}.md"
        pred_path = pred_dir / slug / args.pred_file_name
        if not pred_path.exists():
            pred_path = pred_dir / topic / args.pred_file_name
        if not gt_path.exists() or not pred_path.exists():
            continue
        scores = score_outline(pred_path.read_text(encoding="utf-8"), gt_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "topic": topic,
                "heading_soft_recall": scores.heading_soft_recall,
                "heading_entity_recall": scores.heading_entity_recall,
            }
        )

    out = Path(args.result_output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["topic", "heading_soft_recall", "heading_entity_recall"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
