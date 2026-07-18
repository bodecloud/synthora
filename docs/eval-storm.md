# STORM FreshWiki evaluation

Synthora reproduces the STORM paper evaluation workflow on the
[FreshWiki](https://huggingface.co/datasets/EchoShao8899/FreshWiki) benchmark
using clean-room generation (Synthora `deep_research` pipeline) and ported
metric scripts under `eval/storm/`.

We do **not** import the `knowledge_storm` PyPI package into the product
runtime; eval is a separate harness.

## Layout

```
eval/storm/
  metrics.py                 # heading recall, entity recall, ROUGE-L
  eval_outline_quality.py    # CLI: outline CSV vs ground truth
  eval_article_quality.py    # CLI: article CSV vs ground truth
  data/FreshWiki/            # downloaded topics + ground truth (gitignored)
  results/                   # Synthora exports per topic (gitignored)
scripts/storm_eval/
  download_freshwiki.py      # HF dataset → topic_list.csv + gt files
  export_storm_format.py     # map Synthora report → STORM filenames
  run_freshwiki.py           # batch enqueue deep_research via API
```

## Quick start (local)

```bash
uv sync
uv run pip install datasets   # only for download step

# 1. Download a subset (default 10 topics)
uv run python scripts/storm_eval/download_freshwiki.py --max-topics 10

# 2. Start Synthora (compose or dev stack)
docker compose up -d

# 3. Run batch generation (default 5 topics)
SYNTHORA_API_URL=http://localhost:8000 \
  uv run python scripts/storm_eval/run_freshwiki.py --max-topics 5

# 4. Score outlines and articles
uv run python eval/storm/eval_outline_quality.py \
  --pred-dir eval/storm/results \
  --gt-dir eval/storm/data/FreshWiki \
  --output eval/storm/outline_scores.csv

uv run python eval/storm/eval_article_quality.py \
  --pred-dir eval/storm/results \
  --gt-dir eval/storm/data/FreshWiki \
  --output eval/storm/article_scores.csv
```

Each topic directory under `eval/storm/results/<topic>/` contains:

- `storm_gen_outline.txt`
- `storm_gen_article_polished.txt`

These filenames match the STORM NAACL-2024 eval scripts.

## Metrics

| Metric | Script | Notes |
|---|---|---|
| Heading soft recall | `metrics.score_outline` | Normalized heading overlap |
| Heading entity recall | `metrics.score_outline` | Token overlap on headings |
| ROUGE-L F1 | `metrics.score_article` | Word-level LCS F1 |
| Entity recall | `metrics.score_article` | Token Jaccard proxy |

Prometheus rubric (`evaluation_prometheus.py`) is **optional** and requires GPU;
CI and nightly workflows use similarity metrics only.

## CI and nightly

- **PR CI:** `tests/test_storm_eval_metrics.py` (fixture pairs, no live API)
- **Nightly:** `.github/workflows/storm-eval-nightly.yml` — 5-topic subset with
  `SYNTHORA_MODEL_PROFILE=auto` when `OPENAI_API_KEY` is configured

Full 100-topic eval is manual (`workflow_dispatch` or local run with
`--max-topics 100`).

## Baseline comparison

STORM paper numbers are for reference only; Synthora uses a different runtime
(deep_research = ODR + STORM stages). Expect variance on first runs. Store
CSV outputs under `eval/storm/` for trend tracking across releases.
