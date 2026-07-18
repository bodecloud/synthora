"""Download FreshWiki subset from HuggingFace for STORM eval."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="eval/storm/data/FreshWiki",
        help="Directory for ground-truth articles",
    )
    parser.add_argument("--max-topics", type=int, default=100)
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit("pip install datasets") from exc

    ds = load_dataset("EchoShao8899/FreshWiki", split="train")
    topics: list[str] = []
    for i, row in enumerate(ds):
        if i >= args.max_topics:
            break
        title = row.get("title") or row.get("topic") or f"topic_{i}"
        slug = str(title).replace(" ", "_")
        topic_dir = out / slug
        topic_dir.mkdir(parents=True, exist_ok=True)
        article = row.get("text") or row.get("article") or row.get("content") or ""
        outline = row.get("outline") or ""
        (topic_dir / "article_gt.md").write_text(str(article), encoding="utf-8")
        if outline:
            (topic_dir / "outline_gt.md").write_text(str(outline), encoding="utf-8")
        topics.append(str(title))

    list_path = out / "topic_list.csv"
    with open(list_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["topic"])
        writer.writeheader()
        for t in topics:
            writer.writerow({"topic": t})
    print(f"Saved {len(topics)} topics under {out}")


if __name__ == "__main__":
    main()
