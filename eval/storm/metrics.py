"""STORM-style evaluation metrics (ported concepts from stanford-oval/storm NAACL-2024 eval).

MIT-attributed algorithms; Synthora clean-room implementation for FreshWiki comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def normalize_heading(text: str) -> str:
    text = re.sub(r"^#+\s*", "", text.strip().lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def extract_headings(markdown: str) -> list[str]:
    headings: list[str] = []
    for line in markdown.splitlines():
        if line.strip().startswith("#"):
            headings.append(normalize_heading(line))
    return [h for h in headings if h]


def heading_soft_recall(pred_headings: list[str], gt_headings: list[str]) -> float:
    if not gt_headings:
        return 1.0 if not pred_headings else 0.0
    pred_set = {normalize_heading(h) for h in pred_headings}
    hits = sum(1 for h in gt_headings if normalize_heading(h) in pred_set)
    return hits / len(gt_headings)


def token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def entity_recall(pred: str, gt: str) -> float:
    """Jaccard-like overlap on alphanumeric tokens (lightweight entity proxy)."""
    gt_tokens = token_set(gt)
    if not gt_tokens:
        return 1.0
    pred_tokens = token_set(pred)
    return len(gt_tokens & pred_tokens) / len(gt_tokens)


def rouge_l_f1(pred: str, gt: str) -> float:
    """Longest-common-subsequence F1 on word tokens."""
    pred_tokens = re.findall(r"\w+", pred.lower())
    gt_tokens = re.findall(r"\w+", gt.lower())
    if not pred_tokens or not gt_tokens:
        return 0.0

    dp = [[0] * (len(gt_tokens) + 1) for _ in range(len(pred_tokens) + 1)]
    for i, p in enumerate(pred_tokens, 1):
        for j, g in enumerate(gt_tokens, 1):
            if p == g:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[-1][-1]
    if lcs == 0:
        return 0.0
    prec = lcs / len(pred_tokens)
    rec = lcs / len(gt_tokens)
    return 2 * prec * rec / (prec + rec)


@dataclass
class OutlineScores:
    heading_soft_recall: float
    heading_entity_recall: float


@dataclass
class ArticleScores:
    rouge_l: float
    entity_recall: float


def score_outline(pred_md: str, gt_md: str) -> OutlineScores:
    pred_h = extract_headings(pred_md)
    gt_h = extract_headings(gt_md)
    return OutlineScores(
        heading_soft_recall=heading_soft_recall(pred_h, gt_h),
        heading_entity_recall=entity_recall(" ".join(pred_h), " ".join(gt_h)),
    )


def score_article(pred_md: str, gt_md: str) -> ArticleScores:
    return ArticleScores(
        rouge_l=rouge_l_f1(pred_md, gt_md),
        entity_recall=entity_recall(pred_md, gt_md),
    )
