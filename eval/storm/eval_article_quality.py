#!/usr/bin/env python3
"""Evaluate full article quality against FreshWiki ground truth."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from eval.storm.metrics import score_article


def main() -> None:
    parser = argparse.ArgumentParser(description="STORM article quality eval")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--gt-dir", required=True)
    parser.add_argument("--pred-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pred-file-name", default="storm_gen_article_polished.txt")
    args = parser.parse_args()

    topics: list[str] = []
    with open(args.input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            topic = row.get("topic") or row.get("title") or ""
            if topic.strip():
                topics.append(topic.strip())

    gt_dir = Path(args.gt_dir)
    pred_dir = Path(args.pred_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str | float]] = []

    for topic in topics:
        slug = topic.replace(" ", "_")
        gt_path = gt_dir / slug / "article_gt.md"
        if not gt_path.exists():
            gt_path = gt_dir / f"{slug}.md"
        pred_path = pred_dir / slug / args.pred_file_name
        if not pred_path.exists():
            pred_path = pred_dir / topic / args.pred_file_name
        if not gt_path.exists() or not pred_path.exists():
            continue
        scores = score_article(
            pred_path.read_text(encoding="utf-8"),
            gt_path.read_text(encoding="utf-8"),
        )
        rows.append(
            {
                "topic": topic,
                "rouge_l": scores.rouge_l,
                "entity_recall": scores.entity_recall,
            }
        )

    out_csv = out_dir / "storm_article_quality.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["topic", "rouge_l", "entity_recall"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_csv}")


if __name__ == "__main__":
    main()
