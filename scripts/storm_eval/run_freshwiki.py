#!/usr/bin/env python3
"""Run Synthora deep_research on FreshWiki topics and export STORM eval artifacts."""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
from pathlib import Path

from scripts.storm_eval.export_storm_format import export_run_dir


async def _run_topic(api_url: str, topic: str, out_dir: Path) -> None:
    import httpx

    payload = {
        "question": topic,
        "pipeline_id": "deep_research",
        "config": {
            "allow_clarification": False,
            "max_react_tool_calls": 3,
            "max_discourse_turns": 4,
        },
    }
    async with httpx.AsyncClient(base_url=api_url, timeout=600.0) as client:
        start = await client.post("/api/v1/research", json=payload)
        start.raise_for_status()
        run_id = start.json()["run_id"]
        for _ in range(180):
            detail = await client.get(f"/api/v1/research/{run_id}")
            detail.raise_for_status()
            status = detail.json()["status"]
            if status in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(5)
        if status != "completed":
            raise RuntimeError(f"run {run_id} ended with {status}")
        report = await client.get(f"/api/v1/research/{run_id}/report")
        report.raise_for_status()
        body = report.json()
        export_run_dir(
            topic=topic,
            report_markdown=body.get("report_markdown") or "",
            outline_markdown=None,
            output_dir=out_dir,
        )
        print(f"exported {topic} -> {run_id}")


async def main_async(args: argparse.Namespace) -> None:
    topics: list[str] = []
    with open(args.topic_list, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            topic = (row.get("topic") or "").strip()
            if topic:
                topics.append(topic)
    topics = topics[: args.max_topics]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for topic in topics:
        try:
            await _run_topic(args.api_url, topic, out_dir)
        except Exception as exc:
            print(f"skip {topic}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--topic-list",
        default="eval/storm/data/FreshWiki/topic_list.csv",
    )
    parser.add_argument("--output-dir", default="eval/storm/results")
    parser.add_argument("--api-url", default=os.environ.get("SYNTHORA_API_URL", "http://localhost:8000"))
    parser.add_argument("--max-topics", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
