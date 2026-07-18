"""Tests for STORM eval metrics."""

from eval.storm.metrics import (
    extract_headings,
    heading_soft_recall,
    rouge_l_f1,
    score_article,
    score_outline,
)


def test_heading_soft_recall():
    pred = "# Intro\n## History\n## Future"
    gt = "# Introduction\n## History\n## Politics"
    scores = score_outline(pred, gt)
    assert scores.heading_soft_recall >= 0.33
    assert scores.heading_entity_recall > 0


def test_rouge_l_identical():
    text = "The quick brown fox jumps over the lazy dog."
    scores = score_article(text, text)
    assert scores.rouge_l == 1.0
    assert scores.entity_recall == 1.0


def test_extract_headings():
    assert extract_headings("# Title\n\nbody\n## Section") == ["title", "section"]
